"""
build.py -- load Voteview members data, filter to the 119th House, run
diagnostics, apply Shyntia's decisions (notes/decisions.md), compute the
baseline party means and tercile cutoffs, and write processed CSVs.

Run with:  .venv/bin/python build.py

Steps A-J are the Phase 1 diagnostics (unchanged). Steps K-O apply the
decisions recorded in notes/decisions.md. Step P (P1-P6) runs the Phase 2
completeness checks on data/interim/departures_draft.csv (no results).

Rules followed here:
  - Members are identified by icpsr (and, per decision 2 clarification A,
    bioguide_id for duplicates), never by name.
  - Nothing is imputed. Rows removed by a decision are kept in the output
    file with in_baseline = False and a flag saying why.
  - data/raw/ is read only; nothing there is ever written.
  - Everything printed also goes to logs/build_phase2.txt.
    (logs/build_phase1.txt is the frozen Phase 1 log, kept in git.)
"""

from pathlib import Path

import pandas as pd

RAW_FILE = Path("data/raw/HSall_members.csv")
OUT_FILE = Path("data/processed/house119_baseline.csv")
CUTOFFS_FILE = Path("data/processed/cutoffs.csv")
LOG_FILE = Path("logs/build_phase2.txt")
# Written by extract_departures.py from data/sources/ snapshots (step P checks them).
DRAFT_FILE = Path("data/interim/departures_draft.csv")
# Written by scripts/finalize_verification.py (AI cross-check, decision 20). Step M prefers it once it exists.
VERIFIED_FILE = Path("data/interim/departures_verified.csv")
STATUS_FILE = Path("data/interim/member_status_draft.csv")

CONGRESS = 119
CHAMBER = "House"
LOW_VOTES_THRESHOLD = 100
PARTY_NAMES = {100: "Democrat", 200: "Republican"}

# Non-voting delegates and the resident commissioner (clarification C in
# notes/decisions.md): American Samoa, DC, Guam, Northern Mariana Islands,
# Puerto Rico, U.S. Virgin Islands.
DELEGATE_STATES = ["AS", "DC", "GU", "MP", "PR", "VI"]

# Every line passed to log() is collected here, then written to LOG_FILE at the end.
LOG_LINES = []


def log(text=""):
    """Print to the terminal AND keep a copy for the log file."""
    print(text)
    LOG_LINES.append(str(text))


def header(title):
    log()
    log("=" * 70)
    log(title)
    log("=" * 70)


def member_line(row):
    """One readable line per member, used in every listing below."""
    return (f"  icpsr={row['icpsr']}  {row['bioname']}  "
            f"({row['state_abbrev']}-{row['district_code']:g}, party_code={row['party_code']:g})")


# ---------------------------------------------------------------- step a
def load_raw():
    header("STEP A: Load raw file")
    df = pd.read_csv(RAW_FILE)
    log(f"File: {RAW_FILE}")
    log(f"Total rows: {len(df)}")
    log(f"Columns ({len(df.columns)}):")
    for col in df.columns:
        log(f"  {col}")
    return df


# ---------------------------------------------------------------- step b
def filter_house119(df):
    header(f"STEP B: Filter to congress == {CONGRESS} and chamber == '{CHAMBER}'")
    in_congress = df[df["congress"] == CONGRESS]
    log(f"Rows with congress == {CONGRESS}: {len(in_congress)}")
    log(f"  chamber values in those rows: {in_congress['chamber'].value_counts().to_dict()}")
    house = in_congress[in_congress["chamber"] == CHAMBER].copy()
    log(f"Rows with congress == {CONGRESS} AND chamber == '{CHAMBER}': {len(house)}")
    counts = {"raw": len(df), "congress": len(in_congress), "house": len(house)}
    return house, counts


# ---------------------------------------------------------------- step c
def party_counts(house):
    header("STEP C: Counts by party_code")
    house["party"] = house["party_code"].map(PARTY_NAMES)
    unmapped = house["party"].isna()
    house.loc[unmapped, "party"] = "Other (code " + house.loc[unmapped, "party_code"].map("{:g}".format) + ")"

    for code, n in house["party_code"].value_counts(dropna=False).sort_index().items():
        label = PARTY_NAMES.get(code, "NOT MAPPED")
        log(f"  party_code {code:g} = {label}: {n}")

    others = house[unmapped]
    log(f"Members with a party_code other than 100/200: {len(others)} (kept, NOT dropped)")
    for _, row in others.iterrows():
        log(member_line(row))
    return house


# ---------------------------------------------------------------- step d
def duplicate_icpsr(house):
    header("STEP D: icpsr values appearing more than once")
    is_dup = house["icpsr"].duplicated(keep=False)
    log(f"Rows whose icpsr appears more than once: {is_dup.sum()} (NOT deduplicated)")
    for _, row in house[is_dup].sort_values("icpsr").iterrows():
        log(member_line(row))
    return is_dup


# ---------------------------------------------------------------- step e
def missing_scores(house):
    header("STEP E: Missing nominate_dim1")
    is_missing = house["nominate_dim1"].isna()
    log(f"Rows with missing nominate_dim1: {is_missing.sum()} (NOT imputed)")
    for _, row in house[is_missing].iterrows():
        log(member_line(row))
    return is_missing


# ---------------------------------------------------------------- step f
def low_votes(house):
    header(f"STEP F: nominate_number_of_votes < {LOW_VOTES_THRESHOLD} (low-precision scores)")
    # A missing vote count is NOT counted as low here; those rows already show up in step E.
    is_low = house["nominate_number_of_votes"] < LOW_VOTES_THRESHOLD
    log(f"Rows with fewer than {LOW_VOTES_THRESHOLD} scaled votes: {is_low.sum()}")
    for _, row in house[is_low].sort_values("nominate_number_of_votes").iterrows():
        log(f"{member_line(row)}  votes={row['nominate_number_of_votes']:g}")
    log(f"Rows with missing nominate_number_of_votes: {house['nominate_number_of_votes'].isna().sum()}")
    return is_low


# ---------------------------------------------------------------- step g
def left_mid_congress(house):
    header("STEP G: Can the data identify members who left mid-Congress?")

    # 1. occupancy: Voteview's field for the order of members holding one seat.
    n_occ = house["occupancy"].notna().sum()
    log(f"'occupancy' non-missing in {n_occ} of {len(house)} rows.")
    if n_occ == 0:
        log("  -> occupancy is empty for the 119th House, so the file CANNOT tell us")
        log("     the order in which members held a seat.")

    # 2. died: a death year. The 119th Congress began January 3, 2025, so a death
    #    year of 2025 or later means the member died during this Congress.
    died_during = house["died"] >= 2025
    log(f"'died' year >= 2025 (died during the 119th): {died_during.sum()} rows -> flagged left_midterm")
    for _, row in house[died_during].iterrows():
        log(f"{member_line(row)}  died={row['died']:g}")

    # 3. Seats listed with more than one member (state + district). This shows that
    #    a seat changed hands, but not why or when.
    seat_size = house.groupby(["state_abbrev", "district_code"])["icpsr"].transform("count")
    shared = seat_size > 1
    log(f"Rows in a seat (state_abbrev + district_code) held by more than one member: "
        f"{shared.sum()} -> flagged shared_seat")
    for _, row in house[shared].sort_values(["state_abbrev", "district_code"]).iterrows():
        log(member_line(row))

    log()
    log("CONCLUSION: The file identifies DEATHS during the Congress (via 'died').")
    log("It has NO column for resignations or end-of-service dates, so it CANNOT")
    log("identify members who resigned. shared_seat shows a seat changed hands,")
    log("but the file cannot say which member left or why.")
    return died_during, shared


# ---------------------------------------------------------------- step h
def provisional_baseline(house):
    header("STEP H: PHASE 1 PROVISIONAL BASELINE (before decisions; kept for comparison)")
    log("Every 119th House row with a non-missing nominate_dim1, party_code 100 or 200.")
    log("Nothing removed for duplicates, low votes, or mid-Congress departure.")
    scored = house[house["nominate_dim1"].notna()]
    d = scored[scored["party_code"] == 100]["nominate_dim1"]
    r = scored[scored["party_code"] == 200]["nominate_dim1"]
    log(f"  Democrat mean nominate_dim1:   {d.mean():.4f}   (n = {len(d)})")
    log(f"  Republican mean nominate_dim1: {r.mean():.4f}   (n = {len(r)})")
    log(f"  Gap (R mean - D mean):         {r.mean() - d.mean():.4f}")
    return len(d), len(r)


# ---------------------------------------------------------------- step k
def resolve_duplicates(house):
    """Decision 2 (+ clarification A): rows sharing an icpsr OR a bioguide_id
    are the same member. Keep the row with the larger nominate_number_of_votes."""
    header("STEP K: Decision 2 -- resolve duplicate members (same icpsr or same bioguide_id)")
    keep = pd.Series(True, index=house.index)
    resolved = pd.Series(False, index=house.index)

    for key in ["icpsr", "bioguide_id"]:
        candidates = house[keep & house[key].notna()]
        dup_rows = candidates[candidates[key].duplicated(keep=False)]
        log(f"Groups of rows sharing the same {key}: {dup_rows[key].nunique()}")
        for value, group in dup_rows.groupby(key):
            most_votes = group["nominate_number_of_votes"].max()
            winners = group[group["nominate_number_of_votes"] == most_votes]
            winner = winners.index[0]
            if len(winners) > 1:
                log(f"  WARNING: tie on vote count for {key}={value}; kept the first row. NEEDS A DECISION.")
            for i, row in group.iterrows():
                action = "KEPT (duplicate_resolved)" if i == winner else "DROPPED (duplicate_dropped)"
                log(f"{member_line(row)}  votes={row['nominate_number_of_votes']:g}  -> {action}")
                if i != winner:
                    keep[i] = False
            resolved[winner] = True
    return keep, resolved


# ---------------------------------------------------------------- step l
def baseline_membership(house, keep):
    """Decision 3 (missing scores), decision 5 (non-D/R), clarification C (delegates)."""
    header("STEP L: Decisions 3 and 5 + delegates -- who is in the baseline and the party means")

    is_missing = house["nominate_dim1"].isna()
    log(f"Decision 3: rows with missing nominate_dim1, EXCLUDED from the baseline: {(keep & is_missing).sum()}")
    for _, row in house[keep & is_missing].iterrows():
        log(member_line(row))

    is_delegate = house["state_abbrev"].isin(DELEGATE_STATES)
    log(f"Clarification C: delegates / resident commissioner (kept in data, "
        f"EXCLUDED from party means and cutoffs): {(keep & is_delegate).sum()}")
    for _, row in house[keep & is_delegate].iterrows():
        log(member_line(row))

    is_dr = house["party_code"].isin([100, 200])
    log(f"Decision 5: kept rows that are not Democrat/Republican (kept in data, "
        f"EXCLUDED from party means): {(keep & ~is_dr).sum()}")
    for _, row in house[keep & ~is_dr].iterrows():
        log(member_line(row))

    in_baseline = keep & ~is_missing
    in_means = in_baseline & ~is_delegate & is_dr
    log(f"Rows in baseline: {in_baseline.sum()}   Rows in party means: {in_means.sum()}")
    return in_baseline, in_means, is_delegate


# ---------------------------------------------------------------- step m
def decision1_status(house):
    """Decision 1 (applied per decision 9): members who died or resigned before Nov. 3, 2026
    are excluded from the baseline. The list is the resigned_died rows of the VERIFIED
    departures file when it exists (rows with ai_verified = N do not count; decisions 19-20), otherwise of the
    DRAFT file. Using the verified file keeps cutoffs.csv in step with analyze.py, which
    re-applies decision 1 from the verified rows and stops if the cutoffs differ (decision 18)."""
    header("STEP M: Decision 1 -- held a seat on November 3, 2026 (applied, decision 9)")
    source = VERIFIED_FILE if VERIFIED_FILE.exists() else DRAFT_FILE
    if not source.exists():
        log("  no departures file found: decision 1 NOT applied (run extract_departures.py).")
        return pd.Series("pending_decision1", index=house.index), pd.Series(False, index=house.index)
    dep = pd.read_csv(source, dtype=str, keep_default_na=False)
    # decision 20: the verified file records the AI's check in ai_verified (the draft has no such column)
    flag = dep["ai_verified"].str.strip() if "ai_verified" in dep.columns else pd.Series("", index=dep.index)
    rows = dep[(dep["reason"] == "resigned_died") & (flag != "N")]
    left_ids = pd.to_numeric(rows["icpsr"], errors="coerce").dropna().astype(int)
    left = house["icpsr"].isin(left_ids)
    label = "VERIFIED (AI cross-check, decision 20)" if source == VERIFIED_FILE else "UNVERIFIED draft"
    log(f"Members who left office before Nov. 3, 2026 (resigned_died rows in {source}, "
        f"{label}): {len(left_ids)}; found in the 119th House file: {left.sum()}")
    for _, row in house[left].iterrows():
        log(f"{member_line(row)}  -> EXCLUDED (left_before_nov3)")
    status = pd.Series("held_seat_nov3", index=house.index)
    status[left] = "left_before_nov3"
    log("Every other row: baseline_status = 'held_seat_nov3' (not on the left-early list).")
    return status, left


# ---------------------------------------------------------------- step n
def baseline_means(house, in_means):
    header("STEP N: BASELINE PARTY MEANS (decision 1 applied; departures file not yet verified)")
    scored = house[in_means]
    d = scored[scored["party_code"] == 100]["nominate_dim1"]
    r = scored[scored["party_code"] == 200]["nominate_dim1"]
    log(f"  Democrat mean nominate_dim1:   {d.mean():.4f}   (n = {len(d)})")
    log(f"  Republican mean nominate_dim1: {r.mean():.4f}   (n = {len(r)})")
    log(f"  Gap (R mean - D mean):         {r.mean() - d.mean():.4f}")
    return len(d), len(r)


# ---------------------------------------------------------------- step o
def tercile_cutoffs(house, in_means):
    """Decision 6: moderate R = lowest third of R scores; moderate D = highest third of D scores."""
    header("STEP O: Decision 6 -- tercile cutoffs for 'moderate' (recomputed on the decision-1 baseline, decision 10)")
    scored = house[in_means]
    d = scored[scored["party_code"] == 100]["nominate_dim1"]
    r = scored[scored["party_code"] == 200]["nominate_dim1"]

    # pandas default quantile method = linear interpolation between sorted values.
    r_cut = r.quantile(1 / 3)
    d_cut = d.quantile(2 / 3)

    is_r = in_means & (house["party_code"] == 200)
    is_d = in_means & (house["party_code"] == 100)
    moderate = pd.Series("", index=house.index)
    moderate[is_r] = (house.loc[is_r, "nominate_dim1"] <= r_cut).map({True: "yes", False: "no"})
    moderate[is_d] = (house.loc[is_d, "nominate_dim1"] >= d_cut).map({True: "yes", False: "no"})

    n_mod_r = (moderate[is_r] == "yes").sum()
    n_mod_d = (moderate[is_d] == "yes").sum()
    log(f"  Republican cutoff (1/3 quantile): {r_cut:.4f}  (exact {float(r_cut)!r}); "
        f"moderate if nominate_dim1 <= cutoff: {n_mod_r} of {len(r)}")
    log(f"  Democrat cutoff (2/3 quantile):   {d_cut:.4f}  (exact {float(d_cut)!r}); "
        f"moderate if nominate_dim1 >= cutoff: {n_mod_d} of {len(d)}")

    cutoffs = pd.DataFrame([
        {"party": "Republican", "quantile": "1/3", "cutoff": r_cut, "n_party": len(r),
         "n_moderate": n_mod_r, "rule": "moderate if nominate_dim1 <= cutoff",
         "method": "pandas Series.quantile, linear interpolation",
         "status": "decision 10: recomputed on decision-1 baseline, 2026-11-23"},
        {"party": "Democrat", "quantile": "2/3", "cutoff": d_cut, "n_party": len(d),
         "n_moderate": n_mod_d, "rule": "moderate if nominate_dim1 >= cutoff",
         "method": "pandas Series.quantile, linear interpolation",
         "status": "decision 10: recomputed on decision-1 baseline, 2026-11-23"},
    ])
    cutoffs.to_csv(CUTOFFS_FILE, index=False)
    log(f"Wrote {CUTOFFS_FILE}")
    return moderate


# ---------------------------------------------------------------- step i
def write_output(house, flags):
    header("STEP I: Write processed file")
    flag_text = []
    for i in house.index:
        names = [name for name, mask in flags.items() if mask.loc[i]]
        flag_text.append(";".join(names))
    house["flags"] = flag_text

    # The 9 Phase 1 columns first, then the columns added for the decisions.
    cols = ["icpsr", "bioname", "state_abbrev", "district_code", "party_code", "party",
            "nominate_dim1", "nominate_number_of_votes", "flags",
            "bioguide_id", "in_baseline", "in_party_means", "moderate", "baseline_status"]
    house[cols].to_csv(OUT_FILE, index=False)
    log(f"Wrote {len(house)} rows to {OUT_FILE}")
    for name, mask in flags.items():
        log(f"  rows flagged {name}: {mask.sum()}")
    log(f"  rows with no flags: {(house['flags'] == '').sum()}")
    return len(house)


# ---------------------------------------------------------------- step j
def row_accounting(counts, n_final, house, keep, left, in_baseline, in_means, is_delegate, n_d, n_r):
    header("STEP J: ROW ACCOUNTING")
    log(f"Rows in raw file:                          {counts['raw']}")
    log(f"  removed: congress != {CONGRESS}:                {counts['raw'] - counts['congress']}")
    log(f"Rows after congress == {CONGRESS}:                 {counts['congress']}")
    log(f"  removed: chamber != '{CHAMBER}' (Senate/President): {counts['congress'] - counts['house']}")
    log(f"Rows after chamber == '{CHAMBER}':              {counts['house']}")
    log(f"Rows in {OUT_FILE}: {n_final} (every row is written; see in_baseline / in_party_means)")
    log()
    # Each excluded row is counted once, under the FIRST reason that applies, in this order.
    n_dup = (~keep).sum()
    n_left = (keep & left).sum()
    n_missing = (keep & ~left & ~in_baseline).sum()
    n_delegate = (in_baseline & is_delegate).sum()
    n_other = (in_baseline & ~is_delegate & ~in_means).sum()
    log(f"Rows in baseline (in_baseline = True): {in_baseline.sum()}")
    log(f"  not in baseline: duplicate_dropped (decision 2): {n_dup}")
    log(f"  not in baseline: left office before Nov. 3, 2026 (decision 1): {n_left}")
    log(f"  not in baseline: missing nominate_dim1 (decision 3): {n_missing}")
    log(f"Rows in party means (in_party_means = True): {in_means.sum()} "
        f"= Democrats {n_d} + Republicans {n_r}")
    log(f"  in baseline but not in means: delegate (clarification C): {n_delegate}")
    log(f"  in baseline but not in means: not D/R (decision 5): {n_other}")
    total = n_d + n_r + n_dup + n_left + n_missing + n_delegate + n_other
    log(f"  check: {n_d} + {n_r} + {n_dup} + {n_left} + {n_missing} + {n_delegate} + {n_other} = {total} "
        f"(should equal {n_final})")


# ---------------------------------------------------------------- step p
# Totals the saved sources STATE in their own text (House only), for check P2.
# Each entry: reason -> (Democrats, Republicans, where the source says it).
SOURCE_TOTALS = {
    "retired": (15, 17, "not-running page (as of Oct. 2, 2026): 'Thirty-two U.S. House incumbents "
                        "— 15 Democrats and 17 Republicans — are retiring from public office.'"),
    "ran_other_office": (8, 20, "not-running page: 16 for Senate (7 D, 9 R) + 10 for governor (all R) "
                                "+ 1 for attorney general (R) + 1 for state legislature (D)"),
    "resigned_died": (7, 5, "not-running page: 'Twelve U.S. House incumbents—seven Democrats and five "
                            "Republicans—left office early or announced resignations.'"),
    "lost_primary": (7, 4, "not-running page: 'Eleven U.S. House incumbents—seven Democrats and four "
                           "Republicans—lost re-election.' (all 11 rows are primaries)"),
}


def departures_checks(house):
    """Phase 2 completeness checks on the DRAFT departures file. Counts and lists only:
    no party means, gaps or tests are computed here (those wait for Phase 3)."""
    if not DRAFT_FILE.exists():
        header("STEP P: departures checks SKIPPED (run extract_departures.py first)")
        return
    draft = pd.read_csv(DRAFT_FILE)
    status = pd.read_csv(STATUS_FILE)
    draft["reason_or_uncalled"] = draft["reason"]

    header("STEP P1: departures_draft.csv -- counts by party x reason (UNVERIFIED draft)")
    table = pd.crosstab(draft["reason_or_uncalled"], draft["party"], margins=True, margins_name="Total")
    for line in table.to_string().split("\n"):
        log("  " + line)

    header("STEP P2: draft counts vs. totals stated in the saved sources")
    for reason, (n_d, n_r, quote) in SOURCE_TOTALS.items():
        rows = draft[draft["reason"] == reason]
        d, r = (rows["party"] == "Democrat").sum(), (rows["party"] == "Republican").sum()
        verdict = "MATCH" if (d, r) == (n_d, n_r) else "DIFFERS"
        log(f"  {reason}: draft D={d} R={r}; source D={n_d} R={n_r} -> {verdict}")
        log(f"      source: {quote}")
        if verdict == "DIFFERS":
            extra = rows[~rows["source_file"].str.contains("not-running")]
            for _, x in extra.iterrows():
                log(f"      extra row not from the not-running page: icpsr={x['icpsr']} {x['bioname']} "
                    f"({x['source_file']})")
    lost = draft[draft["reason"] == "lost_general"]
    log(f"  lost_general: draft D={(lost['party'] == 'Democrat').sum()} "
        f"R={(lost['party'] == 'Republican').sum()} (total {len(lost)})")
    log("      NO saved source states a total of general-election defeats. The results page's")
    log("      timeline covers only 250 of 431 calls (none before 12:04 AM Nov. 4), and the")
    log("      elections-2026 page's 'Eleven incumbents ... lost re-election in the general")
    log("      elections' sentence sits in a paragraph about 2024 (220-215 majority), so it is")
    log("      NOT used. lost_general rows come from the 50 state pages' winner check marks.")
    with_tl = lost["notes"].str.contains("results-page timeline: ")
    log(f"      lost_general rows also confirmed by a timeline 'was defeated' line: {with_tl.sum()} "
        f"of {len(lost)}; the other {(~with_tl).sum()} rest on the state page alone (confidence medium).")
    log("  Uncalled: results page (last updated Nov. 19, 2026) says '4 uncalled' and the")
    log("      table says '4 (1 D, 3 R held before)'. The draft has "
        f"{draft['status'].eq('uncalled').sum()} uncalled incumbent rows (reason = pending), all R-held; see P4.")
    log("  Decision 11 ('called' = AP call or official/certified state result): every lost_general")
    log(f"      row ({len(lost)}) currently rests on a Ballotpedia winner check mark only. None has a saved")
    log("      AP or state source yet, so none yet meets decision 11's definition of 'called'.")
    log("  Redistricting: the results page lists 9 states with new 2026 maps (CA, FL, NC, TN, TX")
    log("      voluntarily; OH by state law; AL, LA, UT by litigation). The elections-2026 page")
    log("      ('As of July 26, 2026') also lists Missouri. Discrepancy NOT resolved from sources.")

    header("STEP P3: baseline members whose 2026 status could not be determined")
    unknown = status[status["departure_reasons"].isna() & status["general_results"].isna()]
    log(f"  Members checked (all scored, non-delegate, non-duplicate 119th members, incl. those who "
        f"left early): {len(status)}; status undetermined: {len(unknown)}")
    for _, x in unknown.iterrows():
        log(f"  icpsr={x['icpsr']}  {x['bioname']}  ({x['state_abbrev']}-{x['district_code']:g})")
    counts = status["general_results"].fillna("(not on a Nov. 3 general ballot)").value_counts()
    log("  2026 general-election result found on the state pages (incumbents only):")
    for value, n in counts.items():
        log(f"    {value}: {n}")

    header("STEP P4: uncalled races (status = uncalled)")
    for _, x in draft[draft["status"] == "uncalled"].iterrows():
        log(f"  icpsr={x['icpsr']}  {x['bioname']}  ({x['party']})  {x['notes']}")
    log("  Also on the Louisiana page with NO winner yet: LA-5 and LA-6, both open seats")
    log("  (Letlow ran for Senate; Fields ran for the state legislature), so no incumbent row.")

    header("STEP P5: row accounting for departures_draft.csv")
    from_list = draft["source_file"].str.contains("not-running").sum()
    manual = draft["notes"].str.startswith("MANUAL").sum()
    log(f"  Rows from the not-running page's 4 House tables: {from_list} "
        f"(source totals 32 + 28 + 12 + 11 = 83)")
    log(f"  Rows from state pages (incumbents who lost or are uncalled): {len(draft) - from_list - manual}")
    log(f"  Rows added by hand from a snapshot (notes start 'MANUAL'): {manual}")
    log(f"  Rows written: {len(draft)}; rows dropped: 0")
    log(f"  Rows with blank icpsr: {draft['icpsr'].isna().sum()}; "
        f"icpsr appearing twice: {draft['icpsr'].dropna().duplicated().sum()}; "
        f"icpsr not in baseline: {(~draft['icpsr'].dropna().isin(house['icpsr'])).sum()}")
    log(f"  Confidence: {draft['confidence'].value_counts().to_dict()}")
    log("  Not searched (clarification C): the 6 delegates / resident commissioner.")

    header("STEP P6: resigned_died rows vs. decision 1 (left before Nov. 3 -> not in baseline)")
    left = draft[draft["reason"] == "resigned_died"].merge(
        house[["icpsr", "in_baseline", "in_party_means", "baseline_status"]], on="icpsr", how="left")
    for _, x in left.iterrows():
        ok = (not x["in_baseline"]) and (not x["in_party_means"])
        log(f"  icpsr={x['icpsr']}  {x['bioname']}  in_baseline={x['in_baseline']}  "
            f"in_party_means={x['in_party_means']}  baseline_status={x['baseline_status']}  "
            f"-> {'EXCLUDED, OK' if ok else 'NOT EXCLUDED -- PROBLEM'}")
    n_ok = (~left["in_baseline"].astype(bool) & ~left["in_party_means"].astype(bool)).sum()
    log(f"  -> {n_ok} of {len(left)} resigned_died members excluded from the baseline and party means.")


def main():
    df = load_raw()
    house, counts = filter_house119(df)
    house = party_counts(house)
    is_dup = duplicate_icpsr(house)
    is_missing = missing_scores(house)
    is_low = low_votes(house)
    died_during, shared = left_mid_congress(house)
    provisional_baseline(house)

    keep, resolved = resolve_duplicates(house)
    in_baseline, in_means, is_delegate = baseline_membership(house, keep)
    house["baseline_status"], left = decision1_status(house)
    in_baseline = in_baseline & ~left
    in_means = in_means & ~left
    n_d, n_r = baseline_means(house, in_means)
    house["moderate"] = tercile_cutoffs(house, in_means)
    house["in_baseline"] = in_baseline
    house["in_party_means"] = in_means

    flags = {
        "duplicate_icpsr": is_dup,
        "duplicate_resolved": resolved,
        "duplicate_dropped": ~keep,
        "missing_score": is_missing,
        "low_votes": is_low,
        "left_midterm": died_during,
        "shared_seat": shared,
        "non_dr_party": ~house["party_code"].isin([100, 200]),
        "delegate": is_delegate,
        "left_before_nov3": left,
    }
    n_final = write_output(house, flags)
    row_accounting(counts, n_final, house, keep, left, in_baseline, in_means, is_delegate, n_d, n_r)
    departures_checks(house)

    LOG_FILE.write_text("\n".join(LOG_LINES) + "\n")
    print(f"\n(log written to {LOG_FILE})")


if __name__ == "__main__":
    main()
