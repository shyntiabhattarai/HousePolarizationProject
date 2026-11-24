"""
analyze.py -- Phase 3: answer Q1 and Q2 from the VERIFIED departures file only.

Run with:  .venv/bin/python -I analyze.py

Reads:   data/interim/departures_verified.csv   (from scripts/finalize_verification.py; the ONLY departures input.
                                                In the final run its rows were cross-checked by the AI -- decision 20)
         data/processed/house119_baseline.csv    (from build.py)
         data/processed/cutoffs.csv              (from build.py; checked under decision 18)
Writes (only after validation passes):
         data/processed/summary.csv              one row per number (long format)
         data/processed/analysis_members.csv     every member of B with their group per scenario
         data/processed/permutation_draws_R.csv  the 10,000 permutation draws (main Q1 test)
         data/processed/gap_combinations.csv     Q2 gap for every on/off combination of the 4
                                                 departure groups x 5 scenarios (for the page)
         logs/analysis_phase3.txt                everything printed, incl. the validation report

GUARD: if the verified file does not exist, this script runs the test suite, prints
"VERIFICATION PENDING: no results computed" and exits with code 0. It writes nothing.

Definitions (notes/decisions.md; Phase 3 spec; Shyntia's answers on 2026-11-23):
  B           scored, party D or R, not a delegate, not a dropped duplicate, and not a
              member who left before Nov. 3 (decision 1, from the verified resigned_died rows).
  removed     lost_general rows demoted by decision 17 and (main analysis) pending members
              are taken out of B entirely.
  returning   members of B with no counted departure. A row marked N means the person did
              NOT leave (decision 19): that member is returning, whatever the row's reason.
  moderate    decision 6, with cutoffs recomputed from B every run (decision 18).
Only pandas, numpy and the standard library are used.
"""

import itertools
import math
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

VERIFIED_FILE = Path("data/interim/departures_verified.csv")
BASELINE_FILE = Path("data/processed/house119_baseline.csv")
CUTOFFS_FILE = Path("data/processed/cutoffs.csv")
OUT_DIR = Path("data/processed")
LOG_FILE = Path("logs/analysis_phase3.txt")

SEED = 20261103
N_DRAWS = 10_000
CUTOFF_TOLERANCE = 1e-12          # decision 18: any difference larger than this stops the run
AGREE_TOLERANCE = 0.02            # permutation vs. exact p-values should be this close
DEM, REP = 100, 200
PARTY_NAME = {DEM: "Democrat", REP: "Republican"}

# Same columns, same order, as extract_departures.DRAFT_COLUMNS (a test checks this).
DRAFT_COLUMNS = ["icpsr", "bioname", "state_abbrev", "district_code", "party", "reason",
                 "status", "source_file", "source_url", "source_type", "accessed",
                 "confidence", "notes", "verified_by_author", "second_source_url", "correction"]
# Decision 20: the AI's check is recorded in these columns; the three author columns stay blank.
AI_COLUMNS = ["verified_by", "ai_verified", "ai_source_type", "ai_call_basis", "ai_second_source_url",
              "ai_second_source_file", "ai_correction"]
# Decision 23: how a lost_general row's call is established.
CALL_BASES = {"", "ap_call", "certified_state", "unofficial_state"}
COUNTED_CALL_BASES = {"ap_call", "certified_state", "unofficial_state"}
REQUIRED_COLUMNS = DRAFT_COLUMNS + AI_COLUMNS
AUTHOR_COLUMNS = ["verified_by_author", "second_source_url", "correction"]
# Decisions 17 + 22 (amended): sources that make a lost_general row count as called.
COUNTED_SOURCE_TYPES = {"ap", "state", "news_reporting_ap"}
SOURCE_TYPES = {"", "ap", "state", "news_reporting_ap", "federal_gov", "other"}   # other: recorded, never counted
UNRESOLVED_NOTE = "no second source obtained"          # decision 21
REASONS = {"lost_general", "lost_primary", "retired", "ran_other_office", "resigned_died", "pending"}
MUST_VERIFY = {"lost_general", "lost_primary", "pending"}           # blank = hard fail unless decision 21
MAY_BE_SAMPLED = {"retired", "ran_other_office", "resigned_died"}    # blank = sampled out
DEPARTURE_GROUPS = ["lost_general", "lost_primary", "retired", "ran_other_office"]
IN_ANALYSIS = set(DEPARTURE_GROUPS) | {"returning"}
# Scenario names used everywhere (summary.csv, gap_combinations.csv, the page).
COMBO_SCENARIOS = ["main", "scenario_A", "scenario_B", "no_low_votes", "no_same_party_general"]
VALIDATION_PASSED = "VALIDATION PASSED"   # make_artifact.py looks for this exact line


# ------------------------------------------------------------------ reporting
class Report:
    """Collects every printed line (for the log) and every number (for summary.csv)."""

    def __init__(self, echo=True):
        self.lines, self.rows, self.echo = [], [], echo

    def log(self, text=""):
        if self.echo:
            print(text)
        self.lines.append(str(text))

    def header(self, title):
        self.log()
        self.log("=" * 72)
        self.log(title)
        self.log("=" * 72)

    def add(self, question, scenario, party, group, metric, n, value, notes=""):
        """One number per (question, scenario, party, group, metric). The same key written twice
        with the same value is kept once (e.g. the returning mean, shown next to every group);
        the same key with a DIFFERENT value is a bug and stops the run."""
        key = (question, scenario, party, group, metric)
        for row in self.rows:
            if (row["question"], row["scenario"], row["party"], row["group"], row["metric"]) == key:
                same = (row["value"] == value) or (pd.isna(row["value"]) and pd.isna(value))
                if not (same and row["n"] == n):
                    raise ValueError(f"summary key {key} written twice with different values")
                return
        self.rows.append({"question": question, "scenario": scenario, "party": party,
                          "group": group, "metric": metric, "n": n, "value": value, "notes": notes})


# ------------------------------------------------------------------ inputs
def read_departures(path):
    """Read every column as text so blanks stay blank ('' rather than NaN)."""
    dep = pd.read_csv(path, dtype=str, keep_default_na=False)
    dep.columns = [c.strip() for c in dep.columns]
    for col in dep.columns:
        dep[col] = dep[col].str.strip()
    return dep


def read_baseline(path):
    base = pd.read_csv(path)
    base["flags"] = base["flags"].fillna("").astype(str)
    return base


def _is_int(text):
    return text.isdigit()


def validate_departures(dep, baseline_icpsr):
    """Return a list of problems (empty = valid). Each problem names the CSV row."""
    missing = [c for c in REQUIRED_COLUMNS if c not in dep.columns]
    if missing:
        return [f"missing columns: {missing}"]
    problems = []
    known = {int(x) for x in baseline_icpsr}
    for i, r in dep.iterrows():
        where = f"CSV line {i + 2} (icpsr={r['icpsr'] or 'BLANK'}, {r['bioname']}, reason={r['reason']})"
        for col in AUTHOR_COLUMNS:                                   # decision 20
            if r[col] != "":
                problems.append(f"{where}: {col} must stay blank in this run (decision 20)")
        if r["verified_by"] != "ai":
            problems.append(f"{where}: verified_by = {r['verified_by']!r}; must be 'ai' (decision 20)")
        if r["ai_verified"] not in ("Y", "N", ""):
            problems.append(f"{where}: ai_verified = {r['ai_verified']!r}; must be Y, N or blank")
        if r["reason"] not in REASONS:
            problems.append(f"{where}: reason {r['reason']!r} is not one of {sorted(REASONS)}")
        if r["reason"] in MUST_VERIFY and r["ai_verified"] == "" and UNRESOLVED_NOTE not in r["notes"]:
            problems.append(f"{where}: ai_verified is blank; it must be Y or N for {r['reason']} "
                            f"(or notes must say '{UNRESOLVED_NOTE}', decision 21)")
        problems += [f"{where}: {p}" for p in source_type_problems(r)]
        basis = r["ai_call_basis"]
        if basis not in CALL_BASES:
            problems.append(f"{where}: ai_call_basis {basis!r} is not one of {sorted(CALL_BASES - {''})}")
        elif basis == "ap_call" and r["ai_source_type"] not in ("ap", "news_reporting_ap"):
            problems.append(f"{where}: ai_call_basis 'ap_call' needs ai_source_type ap or news_reporting_ap")
        elif basis in ("certified_state", "unofficial_state") and r["ai_source_type"] != "state":
            problems.append(f"{where}: ai_call_basis {basis!r} needs ai_source_type 'state'")
        if not _is_int(r["icpsr"]):
            problems.append(f"{where}: icpsr is blank or not a whole number")
        elif int(r["icpsr"]) not in known:
            problems.append(f"{where}: icpsr {r['icpsr']} is not in the baseline file")
    ids = dep["icpsr"][dep["icpsr"] != ""]
    for value in sorted(set(ids[ids.duplicated()])):
        lines = [str(i + 2) for i in dep.index[dep["icpsr"] == value]]
        problems.append(f"icpsr {value} appears more than once (CSV lines {', '.join(lines)})")
    return problems


def source_type_problems(r):
    """ai_source_type must be a known type and agree with the URL host (decisions 20, 22)."""
    kind, url = r["ai_source_type"], r["ai_second_source_url"]
    if kind not in SOURCE_TYPES:
        return [f"ai_source_type {kind!r} is not one of {sorted(SOURCE_TYPES - {''})}"]
    host_class = classify_source(url) if url else ""
    if kind in ("ap", "state") and host_class != kind:
        return [f"ai_source_type {kind!r} but the URL host is classed {host_class or 'empty'!r}"]
    host = (urlparse(str(url)).hostname or "").lower()
    if kind == "federal_gov" and (r["reason"] != "resigned_died" or not host.endswith(".gov")):
        return ["ai_source_type 'federal_gov' is allowed only for resigned_died rows with a .gov URL"]
    if kind in ("news_reporting_ap", "other") and host_class != "other":
        return [f"ai_source_type {kind!r} needs a non-government, non-AP URL"]
    if r["ai_verified"] in ("Y", "N") and (kind == "" or url == ""):
        return ["ai_verified is Y/N but ai_source_type or ai_second_source_url is empty"]
    return []


def classify_source(url):
    """'ap', 'state' or 'other' from the URL's host (Shyntia's rule, 2026-11-23)."""
    host = (urlparse(str(url).strip()).hostname or "").lower()
    if host in ("apnews.com", "ap.org") or host.endswith(".apnews.com") or host.endswith(".ap.org"):
        return "ap"
    if host.endswith(".gov") or host.endswith(".us"):
        return "state"
    return "other"


def assign_roles(dep):
    """Add source_class and role to each row. role is what the row means in the analysis:
    returning_N (decision 19: the departure claim is false), excluded_unresolved (decision 21),
    excluded_demoted (decision 17 as amended by 22), pending, or the reason itself.
    Decision 20: the AI's columns (ai_verified, ai_source_type, ai_second_source_url) are used."""
    dep = dep.copy()
    dep["icpsr"] = dep["icpsr"].astype(int)
    dep["source_class"] = dep["ai_source_type"].replace("", "none")

    def role(r, counted=COUNTED_SOURCE_TYPES, bases=COUNTED_CALL_BASES):
        if r["ai_verified"] == "N":
            return "returning_N"
        if r["reason"] in MUST_VERIFY and r["ai_verified"] == "":
            return "excluded_unresolved"                       # decision 21
        if r["reason"] == "lost_general" and not (
                r["ai_verified"] == "Y" and r["ai_source_type"] in counted and r["ai_call_basis"] in bases):
            return "excluded_demoted"                          # decisions 17, 22, 23
        return r["reason"]
    dep["role"] = dep.apply(role, axis=1)
    # decision 22 robustness: only state .gov sources count for lost_general
    dep["role_state_only"] = dep.apply(lambda r: role(r, {"state"}), axis=1)
    # decision 23 robustness: only certified state results or AP-cited calls count
    dep["role_certified_or_ap"] = dep.apply(lambda r: role(r, bases={"certified_state", "ap_call"}), axis=1)
    dep["sampled_out"] = dep["reason"].isin(MAY_BE_SAMPLED) & (dep["ai_verified"] == "")
    return dep


def build_B(base, dep):
    """B before any scenario: decision 1 is re-applied from the VERIFIED resigned_died rows.
    A resigned_died row marked N (decision 19: did not leave) does not exclude the member, who
    stays in B as returning. Returns (B, left_ids, added, restored)."""
    eligible = (base["nominate_dim1"].notna() & base["party_code"].isin([DEM, REP])
                & ~base["flags"].str.contains("delegate")
                & ~base["flags"].str.contains("duplicate_dropped"))
    left_ids = set(dep.loc[(dep["reason"] == "resigned_died") & (dep["ai_verified"] != "N"), "icpsr"])
    B = base[eligible & ~base["icpsr"].isin(left_ids)].copy()
    draft_left = set(base.loc[base["baseline_status"] == "left_before_nov3", "icpsr"])
    return B, left_ids, left_ids - draft_left, draft_left - left_ids


def compute_cutoffs(B):
    """Decision 6 cutoffs, same rule as build.py step O (pandas linear interpolation)."""
    r = B.loc[B["party_code"] == REP, "nominate_dim1"]
    d = B.loc[B["party_code"] == DEM, "nominate_dim1"]
    return {"Republican": float(r.quantile(1 / 3)), "Democrat": float(d.quantile(2 / 3))}


def check_cutoffs(computed, saved):
    """Decision 18: list every party whose recomputed cutoff differs from cutoffs.csv."""
    problems = []
    for party, value in computed.items():
        row = saved[saved["party"] == party]
        if len(row) != 1:
            problems.append(f"{party}: no single row in cutoffs.csv")
        elif abs(float(row["cutoff"].iloc[0]) - value) > CUTOFF_TOLERANCE:
            problems.append(f"{party}: cutoffs.csv = {float(row['cutoff'].iloc[0])!r}, "
                            f"recomputed from B = {value!r}")
    return problems


def add_moderate(B, cuts):
    B = B.copy()
    is_r = B["party_code"] == REP
    B["moderate"] = np.where(is_r, B["nominate_dim1"] <= cuts["Republican"],
                             B["nominate_dim1"] >= cuts["Democrat"])
    return B


def assign_groups(B, dep, scenario, role_column="role"):
    """Group of every member of B under scenario 'main', 'A' (pending lose) or 'B' (pending win)."""
    role = dict(zip(dep["icpsr"], dep[role_column]))
    pending_to = {"main": "excluded_pending", "A": "lost_general", "B": "returning"}[scenario]

    def group(icpsr):
        r = role.get(icpsr)
        if r is None or r == "returning_N":       # decision 19: N = did not leave
            return "returning"
        if r == "pending":
            return pending_to
        return r
    return B["icpsr"].map(group)


def in_analysis(B, groups):
    """Members actually analysed: those whose group is a departure group or returning."""
    df = B.copy()
    df["group"] = groups.values
    return df[df["group"].isin(IN_ANALYSIS)]


# ------------------------------------------------------------------ statistics
def permutation_draws(values, moderate, k, n_draws=N_DRAWS, seed=SEED):
    """Draw k members WITHOUT replacement n_draws times. Returns (means, moderate counts)."""
    values = np.asarray(values, dtype=float)
    moderate = np.asarray(moderate, dtype=bool)
    rng = np.random.default_rng(seed)
    means, counts = np.empty(n_draws), np.empty(n_draws, dtype=int)
    for i in range(n_draws):
        pick = rng.choice(len(values), size=k, replace=False)
        means[i] = values[pick].mean()
        counts[i] = moderate[pick].sum()
    return means, counts


def permutation_p(draws, observed, direction):
    """One-sided p = (draws at least as extreme + 1) / (number of draws + 1).
    direction 'le': extreme = at or below observed; 'ge': at or above. A tolerance of 1e-9
    keeps a draw that equals the observed value from being missed by rounding."""
    draws = np.asarray(draws, dtype=float)
    hits = (draws <= observed + 1e-9).sum() if direction == "le" else (draws >= observed - 1e-9).sum()
    return (int(hits) + 1) / (len(draws) + 1)


def hypergeom_tail(N, K, k, x):
    """P(at least x moderates among k drawn without replacement from N members, K of them
    moderate) = sum over i = x .. min(k, K) of C(K, i) * C(N - K, k - i) / C(N, k)."""
    return sum(math.comb(K, i) * math.comb(N - K, k - i) for i in range(x, min(k, K) + 1)) / math.comb(N, k)


def gap_stats(df):
    d = df.loc[df["party_code"] == DEM, "nominate_dim1"]
    r = df.loc[df["party_code"] == REP, "nominate_dim1"]
    return {"sum_d": d.sum(), "n_d": len(d), "mean_d": d.mean(), "sum_r": r.sum(), "n_r": len(r),
            "mean_r": r.mean(), "gap": r.mean() - d.mean()}


# ------------------------------------------------------------------ Q1
def q1(df, party_code, group, scenario, rep, label, items=4, min_k=0, keep_draws=False):
    """Q1 items 1-4 for one party and one departure group. Returns the mean draws if asked."""
    party = df[df["party_code"] == party_code]
    leaving, staying = party[party["group"] == group], party[party["group"] == "returning"]
    pname, k = PARTY_NAME[party_code], len(leaving)
    rep.log(f"-- {pname}s, group = {group}   [{label}]")
    for name, part in [(group, leaving), ("returning", staying), ("baseline (all analysed)", party)]:
        mean = part["nominate_dim1"].mean() if len(part) else float("nan")
        rep.log(f"   mean dim1, {name:24s}: {mean: .4f}   (n = {len(part)})")
        rep.add("Q1", scenario, pname, name.split(" ")[0], "mean_dim1", len(part), mean, label)
    share_leaving = leaving["moderate"].mean() if k else float("nan")
    share_base = party["moderate"].mean()
    rep.log(f"   share moderate, {group}: {share_leaving:.4f} ({int(leaving['moderate'].sum())} of {k}); "
            f"baseline: {share_base:.4f} ({int(party['moderate'].sum())} of {len(party)})")
    rep.add("Q1", scenario, pname, group, "share_moderate", k, share_leaving, label)
    rep.add("Q1", scenario, pname, "baseline", "share_moderate", len(party), share_base, label)
    if k == 0:
        rep.log("   no members in this group: nothing to test")
        return None
    if k < min_k:
        rep.log(f"   k = {k} < {min_k}: too few to test")
        rep.add("Q1", scenario, pname, group, "test", k, float("nan"), "too few to test")
        return None
    # Republicans: moderate = LOW dim1 -> 'le'. Democrats: moderate = HIGH dim1 -> 'ge'.
    direction = "le" if party_code == REP else "ge"
    means, counts = permutation_draws(party["nominate_dim1"], party["moderate"], k)
    observed = leaving["nominate_dim1"].mean()
    p_mean = permutation_p(means, observed, direction)
    rep.add("Q1", scenario, pname, group, "k", k, k, label)
    rep.log(f"   permutation test on the mean ({N_DRAWS} draws of k = {k}, seed {SEED}, "
            f"'{'<=' if direction == 'le' else '>='} observed'): p = {p_mean:.4f}")
    rep.add("Q1", scenario, pname, group, "perm_p_mean", k, p_mean, label)
    if items >= 4:
        x = int(leaving["moderate"].sum())
        p_count = permutation_p(counts, x, "ge")
        p_exact = hypergeom_tail(len(party), int(party["moderate"].sum()), k, x)
        agree = abs(p_count - p_exact) <= AGREE_TOLERANCE
        rep.log(f"   moderate count >= {x}: permutation p = {p_count:.4f}; exact hypergeometric p = "
                f"{p_exact:.4f} -> {'agree' if agree else 'DISAGREE BY MORE THAN 0.02 -- CHECK'}")
        rep.add("Q1", scenario, pname, group, "perm_p_moderate_count", k, p_count, label)
        rep.add("Q1", scenario, pname, group, "exact_p_moderate_count", k, p_exact, label)
    return means if keep_draws else None


def q1_members_listing(df, rep):
    """The k Republican lost_general members, for checking the mean by hand."""
    rows = df[(df["party_code"] == REP) & (df["group"] == "lost_general")].sort_values("nominate_dim1")
    rep.log(f"Republican lost_general members (k = {len(rows)}), for averaging by hand:")
    for _, r in rows.iterrows():
        rep.log(f"   icpsr={r['icpsr']}  {r['bioname']}  {r['state_abbrev']}-{r['district_code']:g}  "
                f"dim1={r['nominate_dim1']:.3f}  moderate={'yes' if r['moderate'] else 'no'}")
    if len(rows):
        rep.log(f"   sum = {rows['nominate_dim1'].sum():.6f}; / {len(rows)} = {rows['nominate_dim1'].mean():.6f}")


# ------------------------------------------------------------------ Q2
def q2(df, scenario, rep, label, only_all=False, arithmetic=False):
    """Gap (R mean - D mean) for G0 and after removing each departure group."""
    g0 = gap_stats(df)
    cases = [("G0 (all analysed)", df)]
    if not only_all:
        cases += [(f"without {g}", df[df["group"] != g]) for g in DEPARTURE_GROUPS]
    cases.append(("(v) returning only (all departures removed)", df[df["group"] == "returning"]))
    for name, part in cases:
        s = gap_stats(part)
        rep.log(f"   {name:46s} D {s['mean_d']: .4f} (n={s['n_d']})  R {s['mean_r']: .4f} (n={s['n_r']})  "
                f"gap {s['gap']:.4f}  change {s['gap'] - g0['gap']:+.4f}")
        for metric, value, n in [("mean_D", s["mean_d"], s["n_d"]), ("mean_R", s["mean_r"], s["n_r"]),
                                 ("gap", s["gap"], s["n_d"] + s["n_r"]),
                                 ("gap_change_from_G0", s["gap"] - g0["gap"], s["n_d"] + s["n_r"])]:
            rep.add("Q2", scenario, "both" if "gap" in metric else metric[-1], name, metric, n, value, label)
    if not only_all:
        rep.log("   NOTE: the one-group-at-a-time changes do not add up to the all-together change (v);")
        rep.log("   removing several groups changes both party means at once, so this is expected.")
    if arithmetic:
        for name, part in [cases[0], cases[-1]]:
            s = gap_stats(part)
            rep.log(f"   Arithmetic, {name}:")
            rep.log(f"     D: sum {s['sum_d']:.6f} / n {s['n_d']} = mean {s['mean_d']:.6f}")
            rep.log(f"     R: sum {s['sum_r']:.6f} / n {s['n_r']} = mean {s['mean_r']:.6f}")
            rep.log(f"     gap = {s['mean_r']:.6f} - ({s['mean_d']:.6f}) = {s['gap']:.6f}")


def gap_combinations(frames):
    """Q2 for every on/off combination of the 4 departure groups, per scenario.
    A group set to 1 is REMOVED: all zeros = G0, all ones = Q2 (v)."""
    rows = []
    for scenario, df in frames.items():
        g0 = gap_stats(df)
        for flags in itertools.product([0, 1], repeat=len(DEPARTURE_GROUPS)):
            removed = [g for g, f in zip(DEPARTURE_GROUPS, flags) if f]
            s = gap_stats(df[~df["group"].isin(removed)])
            rows.append({"scenario": scenario, **dict(zip(DEPARTURE_GROUPS, flags)),
                         "mean_D": s["mean_d"], "mean_R": s["mean_r"], "gap": s["gap"],
                         "delta_gap": s["gap"] - g0["gap"], "n_D": s["n_d"], "n_R": s["n_r"],
                         "delta_mean_D": s["mean_d"] - g0["mean_d"],
                         "delta_mean_R": s["mean_r"] - g0["mean_r"]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ main
def run_test_suite():
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


def main(verified_path=VERIFIED_FILE, baseline_path=BASELINE_FILE, cutoffs_path=CUTOFFS_FILE,
         out_dir=OUT_DIR, log_path=LOG_FILE, run_tests=True):
    verified_path, out_dir, log_path = Path(verified_path), Path(out_dir), Path(log_path)

    # ---- GUARD: no verified file -> tests only, no results, nothing written
    if not verified_path.exists():
        ok = run_test_suite() if run_tests else True
        print(f"\nVERIFICATION PENDING: no results computed ({verified_path} not found)")
        if not ok:
            print("TEST SUITE FAILED -- see above.")
            return 1
        return 0

    rep = Report()

    def stop(reason, problems):
        rep.log(f"STOPPED: {reason}. No results computed.")
        for p in problems:
            rep.log(f"  - {p}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(rep.lines) + "\n")
        return 1

    base = read_baseline(baseline_path)
    dep = read_departures(verified_path)

    rep.header("VALIDATION: departures_verified.csv")
    problems = validate_departures(dep, base["icpsr"])
    if problems:
        return stop("departures file failed validation", problems)
    dep = assign_roles(dep)
    rep.log(f"Rows: {len(dep)}. ai_verified: {dep['ai_verified'].replace('', '(blank)').value_counts().to_dict()}; "
            f"ai_source_type: {dep['ai_source_type'].replace('', '(none)').value_counts().to_dict()}")
    for _, r in dep[dep["sampled_out"]].iterrows():
        rep.log(f"  unverified_sampled_out: icpsr={r['icpsr']} {r['bioname']} ({r['reason']}) -- counted")
    for _, r in dep[dep["role"] == "returning_N"].iterrows():
        rep.log(f"  ai_verified = N (decision 19: did NOT leave) -> row ignored, member RETURNING: "
                f"icpsr={r['icpsr']} {r['bioname']} (row said {r['reason']})")
    for _, r in dep[dep["role"] == "excluded_unresolved"].iterrows():
        rep.log(f"  UNRESOLVED (decision 21: no second source obtained) -> removed from B: "
                f"icpsr={r['icpsr']} {r['bioname']} ({r['reason']})")
    for metric, value in [("n_rows", len(dep)), ("n_verified_Y", int((dep["ai_verified"] == "Y").sum())),
                          ("n_verified_N", int((dep["ai_verified"] == "N").sum())),
                          ("n_sampled_out", int(dep["sampled_out"].sum())),
                          ("n_unresolved", int((dep["role"] == "excluded_unresolved").sum())),
                          ("n_rows_state_second_source", int((dep["ai_source_type"] == "state").sum())),
                          ("n_rows_news_reporting_ap_second_source", int((dep["ai_source_type"] == "news_reporting_ap").sum())),
                          ("n_rows_ap_second_source", int((dep["ai_source_type"] == "ap").sum())),
                          ("n_rows_federal_gov_second_source", int((dep["ai_source_type"] == "federal_gov").sum())),
                          ("n_lost_general_demoted", int((dep["role"] == "excluded_demoted").sum()))]:
        rep.add("validation", "main", "both", "departures", metric, value, value)
    rep.log("Decision 17 as amended by 22 and 23 -- every lost_general row (counted only if ai_verified Y + "
            "ai_source_type state, ap or news_reporting_ap + ai_call_basis set):")
    for _, r in dep[dep["reason"] == "lost_general"].iterrows():
        verdict = "COUNTED" if r["role"] == "lost_general" else (
            "DEMOTED (reported separately, removed from B)" if r["role"] == "excluded_demoted"
            else "UNRESOLVED (decision 21, removed from B)" if r["role"] == "excluded_unresolved"
            else "N -> member RETURNING (decision 19)")
        rep.log(f"  icpsr={r['icpsr']} {r['bioname']}: ai_verified={r['ai_verified'] or '(blank)'}, "
                f"{r['ai_source_type'] or 'no source'} / {r['ai_call_basis'] or 'no call basis'} "
                f"'{r['ai_second_source_url']}' -> {verdict}")

    rep.header("BASELINE B: decision 1 re-applied from verified resigned_died rows")
    B, left_ids, added, restored = build_B(base, dep)
    rep.log(f"Members excluded under decision 1: {len(left_ids)}")
    rep.log(f"  change vs. the draft-based exclusion in {baseline_path}: "
            f"newly excluded {sorted(added) or 'none'}; no longer excluded {sorted(restored) or 'none'}")
    rep.log(f"B: {len(B)} members ({(B['party_code'] == DEM).sum()} D, {(B['party_code'] == REP).sum()} R)")

    cuts = compute_cutoffs(B)
    problems = check_cutoffs(cuts, pd.read_csv(cutoffs_path))
    rep.log(f"Cutoffs recomputed from B: R {cuts['Republican']!r}, D {cuts['Democrat']!r}")
    if problems:
        return stop("decision 18 -- recomputed cutoffs differ from cutoffs.csv (record the change, "
                    "re-run build.py, then re-run this)", problems)
    rep.log("Cutoffs match cutoffs.csv (decision 18).")
    rep.log(VALIDATION_PASSED)
    for party, value in cuts.items():
        rep.add("cutoffs", "main", party, "B", "cutoff", int((B["party_code"] == (REP if party == "Republican" else DEM)).sum()), value)
    B = add_moderate(B, cuts)

    groups = {s: assign_groups(B, dep, s) for s in ("main", "A", "B")}
    main_df = in_analysis(B, groups["main"])
    removed = B[~groups["main"].isin(IN_ANALYSIS).values]
    rep.log(f"Removed from B in the main analysis: {len(removed)}")
    for _, r in removed.iterrows():
        rep.log(f"  icpsr={r['icpsr']} {r['bioname']}: {groups['main'][r.name]}")
    rep.log(f"Analysed in main: {len(main_df)} ({(main_df['party_code'] == DEM).sum()} D, "
            f"{(main_df['party_code'] == REP).sum()} R). Groups: {main_df['group'].value_counts().to_dict()}")

    # ---- Q1
    rep.header("Q1 (main): did the wave disproportionately remove moderate Republicans?")
    q1_members_listing(main_df, rep)
    draws_R = q1(main_df, REP, "lost_general", "main", rep, "MAIN TEST", keep_draws=True)
    rep.header("Q1 (main), EXPLORATORY: other departure reasons, Republicans")
    for g in DEPARTURE_GROUPS[1:]:
        q1(main_df, REP, g, "main", rep, "EXPLORATORY")
    rep.header("Q1 (main): Democrats mirror (moderate = high dim1; tested only if k >= 5)")
    k_d = ((main_df["party_code"] == DEM) & (main_df["group"] == "lost_general")).sum()
    q1(main_df, DEM, "lost_general", "main", rep, "EXPLORATORY" if k_d < 5 else "DEMOCRAT MIRROR", min_k=5)
    for g in DEPARTURE_GROUPS[1:]:
        q1(main_df, DEM, g, "main", rep, "EXPLORATORY", min_k=5)

    # ---- Q2
    rep.header("Q2 (main): does the party gap widen among returning members?")
    q2(main_df, "main", rep, "MAIN", arithmetic=True)

    # ---- robustness
    rep.header("ROBUSTNESS (each: Q1 items 1-3 for R lost_general, and Q2 (v))")
    spg = set(dep.loc[dep["notes"].str.contains("same_party_general"), "icpsr"])
    direct = dep[(dep["reason"] == "lost_general") & (dep["ai_verified"] == "Y")
                 & dep["ai_source_type"].isin(sorted(COUNTED_SOURCE_TYPES))
                 & dep["ai_call_basis"].isin(sorted(COUNTED_CALL_BASES))]
    same = set(direct["icpsr"]) == set(main_df.loc[main_df["group"] == "lost_general", "icpsr"])
    state_only = in_analysis(B, assign_groups(B, dep, "main", role_column="role_state_only"))
    cert_or_ap = in_analysis(B, assign_groups(B, dep, "main", role_column="role_certified_or_ap"))
    variants = [
        ("no_low_votes", main_df[~main_df["flags"].str.contains("low_votes")], "low_votes members removed"),
        ("no_same_party_general", main_df[~main_df["icpsr"].isin(spg)],
         f"same_party_general members removed: {sorted(spg) or 'none'}"),
        ("scenario_A", in_analysis(B, groups["A"]), "every pending incumbent counted as lost_general"),
        ("scenario_B", in_analysis(B, groups["B"]), "every pending incumbent counted as returning"),
        ("state_sources_only", state_only, "decision 22: lost_general counted only with a state .gov "
         "second source; rows sourced to news_reporting_ap are removed from B"),
        ("certified_or_ap_only", cert_or_ap, "decision 23: lost_general counted only with a certified state "
         "result or an AP-cited call; rows resting on unofficial state results are removed from B"),
        ("decision17_check", main_df, "decision 17 (as amended by 22, 23) filter re-derived directly from the "
         f"ai_* columns: {'MATCHES the main analysis' if same else 'DOES NOT MATCH -- CHECK'}"),
    ]
    frames = {"main": main_df}
    for name, df, note in variants:
        frames[name] = df
        rep.log()
        rep.log(f"## {name}: {note}")
        q1(df, REP, "lost_general", name, rep, name, items=3)
        q2(df, name, rep, name, only_all=True)

    # ---- outputs
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rep.rows).to_csv(out_dir / "summary.csv", index=False)
    members = B[["icpsr", "bioname", "state_abbrev", "district_code", "party", "nominate_dim1",
                 "moderate", "flags"]].copy()
    members["group_main"] = groups["main"].values
    members["group_scenario_A"] = groups["A"].values
    members["group_scenario_B"] = groups["B"].values
    # The two robustness scenarios shown on the page: same groups as main, except members that
    # check removes from the analysis (exactly the members missing from its frame above).
    in_main = members["group_main"].isin(IN_ANALYSIS)
    members["group_no_low_votes"] = members["group_main"].where(
        ~(in_main & members["flags"].str.contains("low_votes")), "excluded_low_votes")
    members["group_no_same_party_general"] = members["group_main"].where(
        ~(in_main & members["icpsr"].isin(spg)), "excluded_same_party_general")
    info = dep.set_index("icpsr")[["reason", "status", "verified_by", "ai_verified", "ai_source_type", "ai_call_basis",
                                   "source_url", "ai_second_source_url", "notes"]]
    members = members.join(info, on="icpsr").rename(columns={"notes": "departure_notes"})
    members.to_csv(out_dir / "analysis_members.csv", index=False)
    gap_combinations({s: frames[s] for s in COMBO_SCENARIOS}).to_csv(
        out_dir / "gap_combinations.csv", index=False)
    pd.DataFrame({"draw": range(1, N_DRAWS + 1) if draws_R is not None else [],
                  "mean_dim1": draws_R if draws_R is not None else []}).to_csv(
        out_dir / "permutation_draws_R.csv", index=False)
    rep.log()
    rep.log(f"Wrote {out_dir / 'summary.csv'} ({len(rep.rows)} rows), {out_dir / 'analysis_members.csv'}, "
            f"{out_dir / 'gap_combinations.csv'}, "
            f"{out_dir / 'permutation_draws_R.csv'}, {log_path}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(rep.lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
