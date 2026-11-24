"""
independent_check.py -- arithmetic re-check, written separately from analyze.py.

Run with:  .venv/bin/python -I scripts/independent_check.py

Recomputes three headline numbers straight from data/processed/analysis_members.csv with plain
pandas (it does NOT import analyze.py), and asserts each matches data/processed/summary.csv to 1e-9:
  1. the mean DW-NOMINATE dim1 of Republicans whose main-analysis group is lost_general (Q1);
  2. G0 = mean R - mean D over every analysed member (group is a departure group or returning);
  3. the gap among returning members only (all departures removed, Q2 item (v)).
Writes logs/independent_check.txt and exits 1 on any mismatch.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "data" / "processed" / "analysis_members.csv"
SUMMARY = ROOT / "data" / "processed" / "summary.csv"
LOG = ROOT / "logs" / "independent_check.txt"
TOLERANCE = 1e-9
# Written out here on purpose (not imported): the groups that count as "analysed".
ANALYSED = {"lost_general", "lost_primary", "retired", "ran_other_office", "returning"}


def rel(path):
    path = Path(path)
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def party_means(df):
    d = df.loc[df["party"] == "Democrat", "nominate_dim1"]
    r = df.loc[df["party"] == "Republican", "nominate_dim1"]
    return r.sum() / len(r), d.sum() / len(d), len(r), len(d)


def summary_value(summary, question, party, group, metric):
    row = summary[(summary["question"] == question) & (summary["scenario"] == "main") & (summary["party"] == party)
                  & (summary["group"] == group) & (summary["metric"] == metric)]
    if len(row) != 1:
        raise SystemExit(f"summary.csv has {len(row)} rows for {question}/{party}/{group}/{metric}")
    return float(row["value"].iloc[0])


def check(members_path=MEMBERS, summary_path=SUMMARY):
    """Returns (all_ok, lines)."""
    m = pd.read_csv(members_path)
    s = pd.read_csv(summary_path)
    lines = ["Independent arithmetic check (scripts/independent_check.py; does not import analyze.py)",
             f"inputs: {rel(members_path)} and {rel(summary_path)}", ""]
    analysed = m[m["group_main"].isin(ANALYSED)]

    lg = m[(m["party"] == "Republican") & (m["group_main"] == "lost_general")]["nominate_dim1"]
    r_g0, d_g0, nr0, nd0 = party_means(analysed)
    r_v, d_v, nrv, ndv = party_means(m[m["group_main"] == "returning"])
    checks = [
        ("Republican lost_general mean (Q1)", lg.sum() / len(lg) if len(lg) else float("nan"),
         summary_value(s, "Q1", "Republican", "lost_general", "mean_dim1"),
         f"sum {lg.sum():.9f} / n {len(lg)}"),
        ("G0 = R mean - D mean, all analysed", r_g0 - d_g0,
         summary_value(s, "Q2", "both", "G0 (all analysed)", "gap"),
         f"R {r_g0:.9f} (n {nr0}) - D {d_g0:.9f} (n {nd0})"),
        ("gap, returning only (all departures removed)", r_v - d_v,
         summary_value(s, "Q2", "both", "(v) returning only (all departures removed)", "gap"),
         f"R {r_v:.9f} (n {nrv}) - D {d_v:.9f} (n {ndv})"),
    ]
    all_ok = True
    for name, mine, theirs, how in checks:
        ok = abs(mine - theirs) <= TOLERANCE
        all_ok &= ok
        lines.append(f"{'MATCH' if ok else 'MISMATCH'}  {name}: independent {mine:.12f} vs summary.csv {theirs:.12f} "
                     f"(diff {abs(mine - theirs):.2e}); {how}")
    lines += ["", "RESULT: " + ("all three match to 1e-9" if all_ok else "MISMATCH -- see above")]
    return all_ok, lines


def main(members_path=MEMBERS, summary_path=SUMMARY, log_path=LOG):
    ok, lines = check(members_path, summary_path)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
