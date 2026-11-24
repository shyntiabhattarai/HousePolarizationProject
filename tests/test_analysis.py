"""
Tests for analyze.py, run on SYNTHETIC fixtures only (tests/fixtures/). No real data.

Run with:  .venv/bin/python -I -m unittest discover -s tests -t . -v

The synthetic world (tests/fixtures/members.csv + departures.csv):
  Republicans 101..108 have dim1 0.1, 0.2, ..., 0.8.  Democrats 201..206 have -0.1 ... -0.6.
  Never in B: 301 (delegate), 302 (resigned_died row -> decision 1), 303 (duplicate_dropped),
              304 (party 328, not D/R).
  So B = 8 R + 6 D = 14 members.
  Cutoffs on B (pandas linear interpolation):
    R 1/3 quantile of 0.1..0.8: position 7 * 1/3 = 2.333 -> 0.3 + 0.333 * 0.1 = 0.33333
        -> moderate R = 101, 102, 103 (dim1 <= 0.3333)
    D 2/3 quantile of -0.6..-0.1: position 5 * 2/3 = 3.333 -> -0.3 + 0.333 * 0.1 = -0.26667
        -> moderate D = 201, 202 (dim1 >= -0.2667)
  Departure rows: 101 lost_general Y AP, 102 lost_general Y state (.gov), 105 lost_general Y
  Ballotpedia (decision 17 demotes), 107 lost_general Y AP + same_party_general,
  103 pending Y, 106 retired (blank = sampled out), 302 resigned_died (blank),
  201 lost_general N (decision 19: did NOT leave -> returning), 202 lost_primary Y,
  203 ran_other_office Y.
  Main analysis removes 103 (pending) and 105 (demoted) from B, leaving
  R: 101, 102, 104, 106, 107, 108   and   D: 201, 202, 203, 204, 205, 206.
"""

import contextlib
import io
import itertools
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze as A  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def load():
    """B, departures-with-roles and the main analysed set, exactly as main() builds them."""
    base = A.read_baseline(FIX / "members.csv")
    dep = A.assign_roles(A.read_departures(FIX / "departures.csv"))
    B, _, _, _ = A.build_B(base, dep)
    B = A.add_moderate(B, A.compute_cutoffs(B))
    return base, dep, B


def analysed(B, dep, scenario="main"):
    return A.in_analysis(B, A.assign_groups(B, dep, scenario))


def quiet(func, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        result = func(*args, **kwargs)
    return result, out.getvalue()


class TestAnalysis(unittest.TestCase):

    # Test 1. Main analysed set:
    #   R mean = (0.1 + 0.2 + 0.4 + 0.6 + 0.7 + 0.8) / 6 = 2.8 / 6 = 0.4666666667
    #   D mean = (-0.1 - 0.2 - 0.3 - 0.4 - 0.5 - 0.6) / 6 = -2.1 / 6 = -0.35   (201 is N -> returning)
    #   G0 = 0.4666666667 - (-0.35) = 0.8166666667
    def test_1_party_means_and_gap(self):
        _, dep, B = load()
        s = A.gap_stats(analysed(B, dep))
        self.assertEqual((s["n_r"], s["n_d"]), (6, 6))
        self.assertAlmostEqual(s["mean_r"], 2.8 / 6, delta=1e-9)
        self.assertAlmostEqual(s["mean_d"], -0.35, delta=1e-9)
        self.assertAlmostEqual(s["gap"], 2.8 / 6 + 0.35, delta=1e-9)

    # Test 2. Remove lost_general only (101, 102, 107; no Democrat counts as lost_general):
    #   R = (0.4 + 0.6 + 0.8) / 3 = 0.6;  D unchanged = -0.35;  gap = 0.95
    #   change = 0.95 - 0.8166666667 = 0.1333333333
    # All departures removed (v): R returning 104, 108 = 0.6;
    #   D returning 201, 204, 205, 206 = -1.6 / 4 = -0.4;  gap = 1.0, change = 0.1833333333
    def test_2_removing_a_group_changes_gap(self):
        _, dep, B = load()
        df = analysed(B, dep)
        g0 = A.gap_stats(df)["gap"]
        without_lg = A.gap_stats(df[df["group"] != "lost_general"])
        self.assertAlmostEqual(without_lg["gap"] - g0, 0.95 - (2.8 / 6 + 0.35), delta=1e-9)
        returning = A.gap_stats(df[df["group"] == "returning"])
        self.assertAlmostEqual(returning["mean_r"], 0.6, delta=1e-9)
        self.assertAlmostEqual(returning["mean_d"], -0.4, delta=1e-9)
        self.assertAlmostEqual(returning["gap"], 1.0, delta=1e-9)

    # Test 3. Member 103 is pending:
    #   main -> excluded_pending (out of B entirely); Scenario A -> lost_general; Scenario B -> returning.
    #   Scenario A R lost_general = 101, 102, 103, 107 -> mean (0.1+0.2+0.3+0.7)/4 = 0.325
    #   Scenario B R returning = 103, 104, 108 -> mean (0.3+0.4+0.8)/3 = 0.5
    #   Other roles: 105 excluded_demoted, 201 returning (N, decision 19), 106 retired, 202 lost_primary.
    def test_3_pending_handling(self):
        _, dep, B = load()
        g = {s: dict(zip(B["icpsr"], A.assign_groups(B, dep, s))) for s in ("main", "A", "B")}
        self.assertEqual((g["main"][103], g["A"][103], g["B"][103]),
                         ("excluded_pending", "lost_general", "returning"))
        self.assertEqual((g["main"][105], g["main"][201], g["main"][106], g["main"][202]),
                         ("excluded_demoted", "returning", "retired", "lost_primary"))
        dfa, dfb = analysed(B, dep, "A"), analysed(B, dep, "B")
        lga = dfa[(dfa["party_code"] == A.REP) & (dfa["group"] == "lost_general")]
        self.assertAlmostEqual(lga["nominate_dim1"].mean(), 0.325, delta=1e-9)
        retb = dfb[(dfb["party_code"] == A.REP) & (dfb["group"] == "returning")]
        self.assertAlmostEqual(retb["nominate_dim1"].mean(), 0.5, delta=1e-9)
        self.assertNotIn(103, set(analysed(B, dep)["icpsr"]))

    # Test 4. 8 Republicans 0.1..0.8, k = 3, observed draw {0.1, 0.3, 0.5}, mean 0.3 (sum 0.9).
    #   Triples of distinct values (in tenths) from 1..8 with sum <= 9:
    #   (1,2,3) (1,2,4) (1,2,5) (1,2,6) (1,3,4) (1,3,5) (2,3,4) = 7 of C(8,3) = 56
    #   exact one-sided p = 7 / 56 = 0.125
    # Second case = the fixture's main test: R = {.1,.2,.4,.6,.7,.8}, k = 3, observed mean 1/3
    #   (sum 1.0): {.1,.2,.4}=0.7 {.1,.2,.6}=0.9 {.1,.2,.7}=1.0 -> 3 of C(6,3) = 20 -> p = 0.15
    def test_4_permutation_matches_exact_enumeration(self):
        for values, observed, hand in [(np.arange(1, 9) / 10, 0.3, 7 / 56),
                                       (np.array([.1, .2, .4, .6, .7, .8]), 1 / 3, 3 / 20)]:
            combos = list(itertools.combinations(values, 3))
            exact = sum(np.mean(c) <= observed + 1e-9 for c in combos) / len(combos)
            self.assertAlmostEqual(exact, hand, delta=1e-12)
            means, _ = A.permutation_draws(values, np.zeros(len(values), bool), 3)
            p = A.permutation_p(means, observed, "le")
            print(f"\n    [test 4] {len(values)} values, k=3: exact p = {exact:.4f}, "
                  f"permutation p (10,000 draws) = {p:.4f}", end="")
            self.assertLess(abs(p - exact), 0.02)

    # Test 5. Hypergeometric tail P(X >= x):
    #   N=6, K=2, k=3, x=2: only x=2 is possible above 1 -> C(2,2)*C(4,1)/C(6,3) = 4/20 = 0.2
    #   N=8, K=3, k=3, x=1: 1 - P(X=0) = 1 - C(5,3)/C(8,3) = 1 - 10/56 = 46/56 = 0.8214285714
    def test_5_hypergeometric(self):
        self.assertAlmostEqual(A.hypergeom_tail(6, 2, 3, 2), 0.2, delta=1e-12)
        self.assertAlmostEqual(A.hypergeom_tail(8, 3, 3, 1), 46 / 56, delta=1e-12)

    # Test 6. Each validation rule fails when it should.
    def test_6_validation_rules(self):
        base, _, B = load()
        raw = A.read_departures(FIX / "departures.csv")
        self.assertEqual(A.validate_departures(raw, base["icpsr"]), [])     # fixture itself is valid
        with self.subTest("blank ai_verified on lost_general (no decision-21 note)"):
            bad = raw.copy()
            bad.loc[bad["icpsr"] == "101", "ai_verified"] = ""
            self.assertTrue(any("blank" in p for p in A.validate_departures(bad, base["icpsr"])))
        with self.subTest("duplicate icpsr"):
            bad = pd.concat([raw, raw[raw["icpsr"] == "202"]], ignore_index=True)
            self.assertTrue(any("more than once" in p for p in A.validate_departures(bad, base["icpsr"])))
        with self.subTest("icpsr missing from the baseline"):
            bad = raw.copy()
            bad.loc[bad["icpsr"] == "202", "icpsr"] = "999"
            self.assertTrue(any("not in the baseline" in p for p in A.validate_departures(bad, base["icpsr"])))
        with self.subTest("cutoff mismatch (decision 18)"):
            cuts = A.compute_cutoffs(B)
            saved = pd.DataFrame({"party": ["Republican", "Democrat"],
                                  "cutoff": [cuts["Republican"] + 1e-6, cuts["Democrat"]]})
            self.assertEqual(len(A.check_cutoffs(cuts, saved)), 1)
            saved["cutoff"] = [cuts["Republican"], cuts["Democrat"]]
            self.assertEqual(A.check_cutoffs(cuts, saved), [])
        with self.subTest("decision 17 demotes a Ballotpedia second source"):
            roles = dict(zip(A.assign_roles(raw)["icpsr"], A.assign_roles(raw)["role"]))
            self.assertEqual(roles[105], "excluded_demoted")
            self.assertEqual((roles[101], roles[102]), ("lost_general", "lost_general"))
            self.assertEqual(A.classify_source("https://ballotpedia.org/x"), "other")
        with self.subTest("ai_verified not in {Y, N, blank}"):
            bad = raw.copy()
            bad.loc[bad["icpsr"] == "202", "ai_verified"] = "yes"
            self.assertTrue(any("must be Y, N or blank" in p for p in A.validate_departures(bad, base["icpsr"])))

    # Test 7. Guard: no verified file -> exit 0, "VERIFICATION PENDING", no files written.
    #   Also: analyze.py never names the draft departures file.
    def test_7_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            code, out = quiet(A.main, verified_path=tmp / "departures_verified.csv",
                              baseline_path=FIX / "members.csv", cutoffs_path=tmp / "none.csv",
                              out_dir=tmp / "out", log_path=tmp / "log.txt", run_tests=False)
            self.assertEqual(code, 0)
            self.assertIn("VERIFICATION PENDING", out)
            self.assertEqual(list(tmp.iterdir()), [])
        self.assertNotIn("departures_draft", (ROOT / "analyze.py").read_text())

    # Test 8. Same seed -> identical draws; different seed -> different draws.
    def test_8_determinism(self):
        values = np.arange(1, 21) / 20
        mod = values < 0.3
        a = A.permutation_draws(values, mod, 5)
        b = A.permutation_draws(values, mod, 5)
        c = A.permutation_draws(values, mod, 5, seed=1)
        self.assertTrue(np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]))
        self.assertFalse(np.array_equal(a[0], c[0]))

    # Test 9 (extra). End-to-end on the synthetic fixtures in a temp folder: all four outputs
    #   are written and summary.csv holds G0 = 0.8166666667 for the main scenario. With a wrong
    #   cutoffs file, main() stops (exit 1) and writes no summary (decision 18).
    def test_9_end_to_end_on_fixtures(self):
        _, _, B = load()
        cuts = A.compute_cutoffs(B)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            good = tmp / "cutoffs.csv"
            pd.DataFrame({"party": list(cuts), "cutoff": list(cuts.values())}).to_csv(good, index=False)
            code, _ = quiet(A.main, verified_path=FIX / "departures.csv", baseline_path=FIX / "members.csv",
                            cutoffs_path=good, out_dir=tmp / "out", log_path=tmp / "out" / "log.txt",
                            run_tests=False)
            self.assertEqual(code, 0)
            names = {p.name for p in (tmp / "out").iterdir()}
            self.assertEqual(names, {"summary.csv", "analysis_members.csv", "permutation_draws_R.csv",
                                     "gap_combinations.csv", "log.txt"})
            s = pd.read_csv(tmp / "out" / "summary.csv")
            g0 = s[(s["scenario"] == "main") & (s["group"] == "G0 (all analysed)") & (s["metric"] == "gap")]
            self.assertAlmostEqual(float(g0["value"].iloc[0]), 2.8 / 6 + 0.35, delta=1e-9)
            self.assertIn(A.VALIDATION_PASSED, (tmp / "out" / "log.txt").read_text())
            keys = s[["question", "scenario", "party", "group", "metric"]]
            self.assertFalse(keys.duplicated().any(), "summary.csv keys must be unique")
            self.assertEqual(len(pd.read_csv(tmp / "out" / "permutation_draws_R.csv")), A.N_DRAWS)

            bad = tmp / "bad_cutoffs.csv"
            pd.DataFrame({"party": list(cuts), "cutoff": [v + 0.01 for v in cuts.values()]}).to_csv(bad, index=False)
            code, out = quiet(A.main, verified_path=FIX / "departures.csv", baseline_path=FIX / "members.csv",
                              cutoffs_path=bad, out_dir=tmp / "out2", log_path=tmp / "log2.txt", run_tests=False)
            self.assertEqual(code, 1)
            self.assertIn("decision 18", out)
            self.assertFalse((tmp / "out2").exists())

    # Test 10 (extra). analyze.py expects exactly the draft's column schema.
    def test_10_schema_matches_extractor(self):
        import extract_departures
        self.assertEqual(A.DRAFT_COLUMNS, extract_departures.DRAFT_COLUMNS)
        self.assertEqual(A.REQUIRED_COLUMNS, extract_departures.DRAFT_COLUMNS + A.AI_COLUMNS)   # decision 20


    # Test 11. Decision 19: N = the person did NOT leave.
    #   (a) Fixture row 201 (lost_general, N): 201 is in B and its group is "returning".
    #   (b) Mark 302's resigned_died row N: decision 1 no longer excludes 302, so 302 is back in B
    #       (B grows from 14 to 15 members) and its group is "returning".
    def test_11_decision19_N_means_returning(self):
        base, dep, B = load()
        self.assertEqual(dict(zip(B["icpsr"], A.assign_groups(B, dep, "main")))[201], "returning")
        raw = A.read_departures(FIX / "departures.csv")
        raw.loc[raw["icpsr"] == "302", ["ai_verified", "ai_source_type", "ai_second_source_url"]] = [
            "N", "federal_gov", "https://clerk.synthetic-test.gov/302"]
        dep2 = A.assign_roles(raw)
        B2, left, _, restored = A.build_B(base, dep2)
        self.assertEqual((len(B), len(B2)), (14, 15))
        self.assertNotIn(302, left)
        self.assertEqual(restored, {302})
        self.assertEqual(dict(zip(B2["icpsr"], A.assign_groups(B2, dep2, "main")))[302], "returning")


    # Test 12. Decision 20: the author columns must stay blank and verified_by must be "ai".
    def test_12_decision20_adit_columns_blank(self):
        base, _, _ = load()
        raw = A.read_departures(FIX / "departures.csv")
        for col in A.AUTHOR_COLUMNS:
            bad = raw.copy()
            bad.loc[bad["icpsr"] == "202", col] = "Y" if col == "verified_by_author" else "x"
            self.assertTrue(any("must stay blank" in p for p in A.validate_departures(bad, base["icpsr"])), col)
        bad = raw.copy()
        bad.loc[bad["icpsr"] == "202", "verified_by"] = "someone_else"
        self.assertTrue(any("must be 'ai'" in p for p in A.validate_departures(bad, base["icpsr"])))
        bad = raw.copy()                                       # type must agree with the URL host
        bad.loc[bad["icpsr"] == "202", "ai_source_type"] = "ap"
        self.assertTrue(any("URL host" in p for p in A.validate_departures(bad, base["icpsr"])))

    # Test 13. Decision 21: a blank ai_verified on lost_general / lost_primary / pending is accepted only
    #   with the note "no second source obtained"; that member is then removed from B (excluded_unresolved).
    #   Fixture 202 (lost_primary, D -0.2) made unresolved -> main D analysed: 201, 203..206 =
    #   (-0.1-0.3-0.4-0.5-0.6)/5 = -0.38.
    def test_13_decision21_unresolved_removed_from_B(self):
        base, _, _ = load()
        raw = A.read_departures(FIX / "departures.csv")
        raw.loc[raw["icpsr"] == "202", ["ai_verified", "ai_source_type", "ai_second_source_url"]] = ["", "", ""]
        self.assertTrue(any("blank" in p for p in A.validate_departures(raw, base["icpsr"])))   # no note -> fail
        raw.loc[raw["icpsr"] == "202", "notes"] = "no second source obtained (synthetic)"
        self.assertEqual(A.validate_departures(raw, base["icpsr"]), [])
        dep = A.assign_roles(raw)
        B, *_ = A.build_B(base, dep)
        B = A.add_moderate(B, A.compute_cutoffs(B))
        groups = dict(zip(B["icpsr"], A.assign_groups(B, dep, "main")))
        self.assertEqual(groups[202], "excluded_unresolved")
        df = analysed(B, dep)
        self.assertNotIn(202, set(df["icpsr"]))
        self.assertAlmostEqual(A.gap_stats(df)["mean_d"], -0.38, delta=1e-9)

    # Test 14. Decision 22: news_reporting_ap counts in the main analysis (107 is lost_general), but the
    #   state_sources_only check counts ONLY state .gov sources, so it removes 107 (news_reporting_ap)
    #   AND 101 (ap) from B: R lost_general = 102 only -> k 1, mean 0.2;
    #   a Ballotpedia ('other') source never counts (105 demoted in both).
    def test_14_decision22_state_sources_only(self):
        _, dep, B = load()
        main = dict(zip(B["icpsr"], A.assign_groups(B, dep, "main")))
        state = dict(zip(B["icpsr"], A.assign_groups(B, dep, "main", role_column="role_state_only")))
        self.assertEqual((main[107], state[107]), ("lost_general", "excluded_demoted"))
        self.assertEqual((main[105], state[105]), ("excluded_demoted", "excluded_demoted"))
        df = A.in_analysis(B, A.assign_groups(B, dep, "main", role_column="role_state_only"))
        lg = df[(df["party_code"] == A.REP) & (df["group"] == "lost_general")]
        self.assertEqual(sorted(lg["icpsr"]), [102])
        self.assertAlmostEqual(lg["nominate_dim1"].mean(), 0.2, delta=1e-9)
        self.assertEqual(state[101], "excluded_demoted")


    # Test 15. Decision 23: certified_or_ap_only counts only ai_call_basis certified_state or ap_call.
    #   Fixture: 101 ap_call (0.1), 102 unofficial_state (0.2), 107 ap_call (0.7) -> R lost_general
    #   = 101, 107 -> k 2, mean (0.1 + 0.7) / 2 = 0.4; 102 removed from B in that check only.
    #   Also: a lost_general Y row with no call basis is demoted in the MAIN analysis, and the call
    #   basis must agree with the source type.
    def test_15_decision23_certified_or_ap_only(self):
        base, dep, B = load()
        g = dict(zip(B["icpsr"], A.assign_groups(B, dep, "main", role_column="role_certified_or_ap")))
        self.assertEqual((g[101], g[102], g[107]), ("lost_general", "excluded_demoted", "lost_general"))
        df = A.in_analysis(B, A.assign_groups(B, dep, "main", role_column="role_certified_or_ap"))
        lg = df[(df["party_code"] == A.REP) & (df["group"] == "lost_general")]
        self.assertAlmostEqual(lg["nominate_dim1"].mean(), 0.4, delta=1e-9)
        raw = A.read_departures(FIX / "departures.csv")
        raw.loc[raw["icpsr"] == "102", "ai_call_basis"] = ""
        self.assertEqual(dict(zip(A.assign_roles(raw)["icpsr"], A.assign_roles(raw)["role"]))[102], "excluded_demoted")
        raw.loc[raw["icpsr"] == "102", "ai_call_basis"] = "ap_call"          # state source + ap_call: invalid
        self.assertTrue(any("ap_call" in p for p in A.validate_departures(raw, base["icpsr"])))


class TestGapCombinations(unittest.TestCase):
    """Part 1 tests: gap_combinations.csv on the fixtures (5 scenarios x 16 = 80 rows)."""

    @classmethod
    def setUpClass(cls):
        _, cls.dep, cls.B = load()
        cuts = A.compute_cutoffs(cls.B)
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        pd.DataFrame({"party": list(cuts), "cutoff": list(cuts.values())}).to_csv(tmp / "c.csv", index=False)
        code, _ = quiet(A.main, verified_path=FIX / "departures.csv", baseline_path=FIX / "members.csv",
                        cutoffs_path=tmp / "c.csv", out_dir=tmp, log_path=tmp / "log.txt", run_tests=False)
        assert code == 0
        cls.combos = pd.read_csv(tmp / "gap_combinations.csv")
        cls.summary = pd.read_csv(tmp / "summary.csv")
        main_df = analysed(cls.B, cls.dep)
        spg = set(cls.dep.loc[cls.dep["notes"].str.contains("same_party_general"), "icpsr"])
        cls.frames = {"main": main_df, "scenario_A": analysed(cls.B, cls.dep, "A"),
                      "scenario_B": analysed(cls.B, cls.dep, "B"),
                      "no_low_votes": main_df[~main_df["flags"].str.contains("low_votes")],
                      "no_same_party_general": main_df[~main_df["icpsr"].isin(spg)]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def summary_value(self, scenario, group, metric="gap"):
        s = self.summary
        row = s[(s["question"] == "Q2") & (s["scenario"] == scenario) & (s["group"] == group) & (s["metric"] == metric)]
        self.assertEqual(len(row), 1, (scenario, group, metric))
        return float(row["value"].iloc[0])

    # (a) Every one of the 80 rows equals a direct recompute from the analysed members.
    def test_a_each_combination_matches_direct_recompute(self):
        self.assertEqual(len(self.combos), 80)
        for _, row in self.combos.iterrows():
            df = self.frames[row["scenario"]]
            removed = [g for g in A.DEPARTURE_GROUPS if row[g] == 1]
            s = A.gap_stats(df[~df["group"].isin(removed)])
            self.assertAlmostEqual(row["gap"], s["gap"], delta=1e-12)
            self.assertEqual((row["n_D"], row["n_R"]), (s["n_d"], s["n_r"]))

    # (b) All-off row = G0 (delta 0). Main fixture G0 = 2.8/6 + 0.35 = 0.8166666667.
    def test_b_all_off_equals_G0(self):
        off = self.combos[(self.combos[A.DEPARTURE_GROUPS] == 0).all(axis=1)]
        for _, row in off.iterrows():
            self.assertAlmostEqual(row["gap"], self.summary_value(row["scenario"], "G0 (all analysed)"), delta=1e-12)
            self.assertAlmostEqual(row["delta_gap"], 0.0, delta=1e-12)
        main = off[off["scenario"] == "main"]["gap"].iloc[0]
        self.assertAlmostEqual(main, 2.8 / 6 + 0.35, delta=1e-9)

    # (c) All-on row = Q2 item (v). Main fixture (v) gap = 0.6 - (-0.4) = 1.0.
    def test_c_all_on_equals_Q2_v(self):
        on = self.combos[(self.combos[A.DEPARTURE_GROUPS] == 1).all(axis=1)]
        for _, row in on.iterrows():
            self.assertAlmostEqual(row["gap"], self.summary_value(
                row["scenario"], "(v) returning only (all departures removed)"), delta=1e-12)
        self.assertAlmostEqual(on[on["scenario"] == "main"]["gap"].iloc[0], 1.0, delta=1e-9)

    # (e) analysis_members.csv has one group column per page scenario, and the members it marks
    #     as analysed (a departure group or returning) are exactly that scenario's analysed set,
    #     with the same groups -- so the dot plot always agrees with the panel numbers.
    #     e.g. scenario A: pending member 103 -> lost_general; no_low_votes: 104 -> excluded_low_votes.
    def test_e_member_group_columns_match_scenarios(self):
        m = pd.read_csv(Path(self.tmp.name) / "analysis_members.csv")
        for scenario, frame in self.frames.items():
            col = m.set_index("icpsr")[f"group_{scenario}"]
            analysed_ids = set(col[col.isin(A.IN_ANALYSIS)].index)
            self.assertEqual(analysed_ids, set(frame["icpsr"]), scenario)
            for _, r in frame.iterrows():
                self.assertEqual(col[r["icpsr"]], r["group"], (scenario, r["icpsr"]))
        col = m.set_index("icpsr")
        self.assertEqual(col.loc[103, "group_scenario_A"], "lost_general")
        self.assertEqual(col.loc[104, "group_no_low_votes"], "excluded_low_votes")
        self.assertEqual(col.loc[107, "group_no_same_party_general"], "excluded_same_party_general")

    # (d) Single-group rows = Q2 items (i)-(iv) (main scenario; robustness runs only report (v)).
    #   e.g. lost_general only: R (0.4+0.6+0.8)/3 = 0.6, D -0.35 -> gap 0.95.
    def test_d_single_group_rows_equal_Q2_i_to_iv(self):
        main = self.combos[self.combos["scenario"] == "main"]
        for g in A.DEPARTURE_GROUPS:
            mask = (main[g] == 1) & (main[[x for x in A.DEPARTURE_GROUPS if x != g]] == 0).all(axis=1)
            self.assertAlmostEqual(main[mask]["gap"].iloc[0], self.summary_value("main", f"without {g}"), delta=1e-12)
        lg = main[(main["lost_general"] == 1) & (main[["lost_primary", "retired", "ran_other_office"]] == 0).all(axis=1)]
        self.assertAlmostEqual(lg["gap"].iloc[0], 0.95, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
