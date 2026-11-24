"""
progress.py -- how far the verification (the AI's cross-check under decision 20) has got.
READ-ONLY: it changes nothing.

Run with:  .venv/bin/python -I scripts/progress.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet_common as W  # noqa: E402


def report(ws):
    lines = [f"Worksheet: {len(ws)} rows"]
    lines.append("Done (Y or N) vs. remaining, by check_order:")
    for order, part in ws.groupby("check_order"):
        done = part["ai_verified"].isin(["Y", "N"]).sum()
        lines.append(f"  {order}: {done:3d} done, {len(part) - done:3d} remaining   ({part['check_reason'].iloc[0]})")
    lines.append(f"ai_verified Y: {(ws['ai_verified'] == 'Y').sum()}   ai_verified N: {(ws['ai_verified'] == 'N').sum()}   "
                 f"unresolved (decision 21): {len(W.unresolved(ws))}")
    blank = W.blank_required(ws)
    lines.append(f"Still blank in check_order 1-7: {len(blank)}")
    for order, part in blank.groupby("check_order"):
        names = "; ".join(f"{r['bioname']} ({r['state_abbrev']}-{r['district_code']})" for _, r in part.iterrows())
        lines.append(f"  {order}: {names}")
    missing = W.missing_second_source(ws)
    lines.append(f"Verified but ai_second_source_url or ai_source_type empty: {len(missing)}")
    lines += [f"  {W.label(r)}" for _, r in missing.iterrows()]
    lg = ws[(ws["reason"] == "lost_general") & (ws["ai_verified"] == "Y")]
    lines.append(f"lost_general rows with ai_verified Y: {len(lg)} (decisions 17 + 22: state, ap or news_reporting_ap)")
    for _, r in lg.iterrows():
        kind = r["ai_source_type"] or "none"
        flag = ("ok" if kind in W.analyze.COUNTED_SOURCE_TYPES
                else "FLAG: not state/ap/news_reporting_ap -> will be DEMOTED by decision 17")
        lines.append(f"  {W.label(r)}: {kind} -- {flag}")
    return lines


def main(path=W.WORKSHEET):
    print("\n".join(report(W.read_worksheet(path))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
