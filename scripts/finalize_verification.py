"""
finalize_verification.py -- turn the verification worksheet into data/interim/departures_verified.csv.

Run with:  .venv/bin/python -I scripts/finalize_verification.py [--force]

Refuses (listing the rows) if:
  - a row in check_order 1-7 has a blank ai_verified (unless notes say "no second source obtained", decision 21);
  - a row marked Y or N has an empty ai_second_source_url or ai_source_type;
  - a Blair row (check_order 1) still has a blank icpsr;
  - the output already exists and --force was not given;
  - analyze.py's input validation fails on the result (validation only -- no analysis).
The output has the draft's columns plus the decision-20 ai_* columns (the 3 helper columns dropped).
Values are copied as the worksheet holds them; correction / ai_correction are copied, never parsed.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet_common as W  # noqa: E402


def finalize(worksheet, out, baseline, force=False):
    """Returns (exit code, printed lines)."""
    lines = []
    if Path(out).exists() and not force:
        return 1, [f"REFUSING: {out} already exists. Re-run with --force to overwrite it."]
    ws = W.read_worksheet(worksheet)
    checks = [("check_order 1-7 rows with a blank ai_verified (and no decision-21 note)", W.blank_required(ws)),
              ("rows marked Y or N with an empty ai_second_source_url or ai_source_type", W.missing_second_source(ws)),
              ("Blair row (check_order 1) with a blank icpsr", W.blair_without_icpsr(ws))]
    failed = [(title, rows) for title, rows in checks if len(rows)]
    if failed:
        lines.append("REFUSING to write departures_verified.csv:")
        for title, rows in failed:
            lines.append(f"  {title}: {len(rows)}")
            lines += [f"    {W.label(r)}" for _, r in rows.iterrows()]
        return 1, lines
    missing = [c for c in W.analyze.REQUIRED_COLUMNS if c not in ws.columns]
    if missing:
        return 1, [f"REFUSING: worksheet is missing columns {missing}"]
    verified = ws[W.analyze.REQUIRED_COLUMNS].copy()

    lines.append("Rows by reason x ai_verified:")
    table = pd.crosstab(verified["reason"], verified["ai_verified"].replace("", "(blank)"), margins=True,
                        margins_name="Total")
    lines += ["  " + x for x in table.to_string().split("\n")]
    lines.append(f"Rows with an ai_correction noted: {(verified['ai_correction'] != '').sum()}")
    lines.append(f"Rows with ai_verified N (departure claim false -> member returning, decision 19): "
                 f"{(verified['ai_verified'] == 'N').sum()}")
    lines.append(f"Unresolved rows (decision 21): {len(W.unresolved(ws))}")

    problems = W.analyze.validate_departures(verified, pd.read_csv(baseline)["icpsr"])
    lines.append("analyze.py input validation (validation only, no analysis): "
                 + ("PASSED" if not problems else f"FAILED ({len(problems)} problems)"))
    lines += [f"  - {p}" for p in problems]
    if problems:
        lines.append(f"Nothing written. Fix the worksheet and run again.")
        return 1, lines
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    verified.to_csv(out, index=False)
    shown = Path(out).relative_to(W.ROOT) if Path(out).is_relative_to(W.ROOT) else out
    lines.append(f"Wrote {shown} ({len(verified)} rows, {len(verified.columns)} columns: draft order + ai_* columns)")
    return 0, lines


def main(argv=None, worksheet=W.WORKSHEET, out=W.VERIFIED, baseline=W.BASELINE):
    argv = sys.argv[1:] if argv is None else argv
    code, lines = finalize(worksheet, out, baseline, force="--force" in argv)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
