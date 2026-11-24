"""Shared helpers for progress.py and finalize_verification.py (read-only functions).
Under decision 20 the check is recorded by the AI in the ai_* columns; the author columns stay blank."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze  # noqa: E402  (for REQUIRED_COLUMNS, read_departures, classify_source, validation)

WORKSHEET = ROOT / "data" / "interim" / "verification_worksheet.csv"
VERIFIED = ROOT / "data" / "interim" / "departures_verified.csv"
BASELINE = ROOT / "data" / "processed" / "house119_baseline.csv"
HELPERS = ["check_order", "check_reason", "search_link"]
MUST_CHECK = range(1, 8)          # check_order 1-7 must be verified; 8 may stay blank


def read_worksheet(path):
    ws = analyze.read_departures(path)          # every column as text, blanks stay ''
    ws["check_order"] = ws["check_order"].astype(int)
    return ws


def label(row):
    who = row["bioname"] or "(no name)"
    return f"order {row['check_order']}: icpsr={row['icpsr'] or 'BLANK'} {who} ({row['state_abbrev']}-{row['district_code']}, {row['reason'] or 'no reason'})"


# Decision 20: the AI's check is in ai_verified / ai_source_type / ai_second_source_url.
# Decision 21: a blank ai_verified is allowed only when notes say "no second source obtained".
def unresolved(ws):
    return ws[ws["check_order"].isin(MUST_CHECK) & (ws["ai_verified"] == "")
              & ws["notes"].str.contains(analyze.UNRESOLVED_NOTE, regex=False)]


def blank_required(ws):
    return ws[ws["check_order"].isin(MUST_CHECK) & (ws["ai_verified"] == "")
              & ~ws["notes"].str.contains(analyze.UNRESOLVED_NOTE, regex=False)]


def missing_second_source(ws):
    return ws[ws["ai_verified"].isin(["Y", "N"])
              & ((ws["ai_second_source_url"] == "") | (ws["ai_source_type"] == ""))]


def blair_without_icpsr(ws):
    return ws[(ws["check_order"] == 1) & (ws["icpsr"] == "")]
