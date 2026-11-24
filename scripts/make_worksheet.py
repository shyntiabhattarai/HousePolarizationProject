"""
make_worksheet.py -- build Shyntia's verification worksheet from the DRAFT departures file.

Run with:  .venv/bin/python -I scripts/make_worksheet.py   (after scripts/draw_sample.py)

Writes data/interim/verification_worksheet.csv: every draft column, plus check_order,
check_reason and search_link, sorted by check_order and then state. The draft is only read.
verified_by_author, second_source_url and correction are left EMPTY (decision 20). The ai_* columns
are added (verified_by = "ai"; the rest empty) for the AI's cross-check. Nothing is looked up here.
Refuses to overwrite an existing worksheet (it holds Shyntia's work) unless run with --force.
"""

import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data" / "interim" / "departures_draft.csv"
SAMPLE = ROOT / "data" / "interim" / "verification_sample.csv"
BASELINE = ROOT / "data" / "processed" / "house119_baseline.csv"
OUT = ROOT / "data" / "interim" / "verification_worksheet.csv"
HELPERS = ["check_order", "check_reason", "search_link"]
AI_COLUMNS = ["verified_by", "ai_verified", "ai_source_type", "ai_call_basis", "ai_second_source_url",
              "ai_second_source_file", "ai_correction"]          # decision 20 (same list as analyze.AI_COLUMNS)

# Members singled out by icpsr (never by name).
FOXX = 20521                  # NC-5, close race, supported by the state page only
NAME_MATCHED = {22336, 20529}  # Kiley (CA-3 -> CA-6, ran as No party preference), Al Green (TX-9 -> TX-18)

REASON_TEXT = {
    1: "Blair: is he in the baseline, did he hold the seat on Nov 3, did he lose a 2026 primary?",
    2: "pending race: needs an AP or official state call (decisions 11, 12, 16)",
    3: "close race (NC-5): supported by the Ballotpedia state page only",
    4: "matched by name within the state because the 2026 district differs from the 119th",
    5: "lost_general: counted only with an AP or state second source (decision 17)",
    6: "lost_primary: confirm with a second source",
    7: "random sample of retired / ran_other_office / resigned_died (scripts/draw_sample.py)",
    8: "not sampled: may stay blank",
}


def check_order(row, sampled):
    if row["reason"] == "pending":
        return 2
    if row["icpsr"] == FOXX:
        return 3
    if row["icpsr"] in NAME_MATCHED:
        return 4
    if row["reason"] == "lost_general":
        return 5
    if row["reason"] == "lost_primary":
        return 6
    return 7 if row["icpsr"] in sampled else 8


def search_link(bioname, state, district):
    query = f"{bioname} {state}-{int(float(district))} 2026 election results AP"
    return "https://www.google.com/search?q=" + quote_plus(query)


def build(draft, sampled, baseline):
    ws = draft.copy()
    ws["check_order"] = [check_order(r, sampled) for _, r in ws.iterrows()]
    # Blair (check_order 1): only bioname, state_abbrev, district_code and notes are filled.
    # The display name is the baseline's GA-13 member who held the seat on Nov 3 (exactly one).
    ga13 = baseline[(baseline["state_abbrev"] == "GA") & (baseline["district_code"] == 13)
                    & (baseline["baseline_status"] == "held_seat_nov3")]
    if len(ga13) != 1:
        raise SystemExit(f"expected one GA-13 member holding the seat in the baseline, found {len(ga13)}")
    blair = {c: "" for c in draft.columns}
    blair.update({"bioname": ga13["bioname"].iloc[0], "state_abbrev": "GA", "district_code": 13,
                  "notes": "verify: in baseline? held seat Nov 3? lost 2026 primary? "
                           "If not departing, delete this row.", "check_order": 1})
    ws = pd.concat([pd.DataFrame([blair]), ws], ignore_index=True)
    ws["check_reason"] = ws["check_order"].map(REASON_TEXT)
    ws["search_link"] = [search_link(r["bioname"], r["state_abbrev"], r["district_code"]) for _, r in ws.iterrows()]
    for col in ["verified_by_author", "second_source_url", "correction"] + AI_COLUMNS:
        ws[col] = ""
    ws["verified_by"] = "ai"
    ws["district_code"] = ws["district_code"].astype(float).astype(int)
    ws = ws.sort_values(["check_order", "state_abbrev", "district_code"], kind="stable")
    return ws[list(draft.columns) + AI_COLUMNS + HELPERS]


def main(argv):
    if OUT.exists() and "--force" not in argv:
        print(f"REFUSING: {OUT.relative_to(ROOT)} already exists (it may hold your verification work). "
              "Use --force only if you really want to rebuild it from the draft.")
        return 1
    draft = pd.read_csv(DRAFT)
    sampled = set(pd.read_csv(SAMPLE)["icpsr"])
    ws = build(draft, sampled, pd.read_csv(BASELINE))
    ws.to_csv(OUT, index=False)
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(ws)} rows")
    for order, n in ws["check_order"].value_counts().sort_index().items():
        print(f"  check_order {order}: {n:3d} rows  ({REASON_TEXT[order]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
