"""
draw_sample.py -- choose the 15 retired / ran_other_office / resigned_died rows Shyntia verifies.

Run with:  .venv/bin/python -I scripts/draw_sample.py

Population: every row of data/interim/departures_draft.csv whose reason is retired,
ran_other_office or resigned_died. Draw: random.seed(20261123), then
random.sample(sorted list of icpsr, 15). Writes data/interim/verification_sample.csv.
The draft is only read, never changed.
"""

import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data" / "interim" / "departures_draft.csv"
OUT = ROOT / "data" / "interim" / "verification_sample.csv"
SEED = 20261123
SAMPLE_SIZE = 15
SAMPLED_REASONS = ["retired", "ran_other_office", "resigned_died"]


def draw(draft):
    population = sorted(int(x) for x in draft.loc[draft["reason"].isin(SAMPLED_REASONS), "icpsr"])
    random.seed(SEED)
    return population, random.sample(population, SAMPLE_SIZE)


def main():
    draft = pd.read_csv(DRAFT)
    population, chosen = draw(draft)
    print(f"Python {sys.version.split()[0]}; random.seed({SEED}); "
          f"random.sample(sorted icpsr list of {len(population)}, {SAMPLE_SIZE})")
    rows = draft.set_index("icpsr").loc[chosen, ["bioname", "state_abbrev", "district_code", "reason"]]
    rows = rows.reset_index()
    rows.insert(0, "draw_order", range(1, SAMPLE_SIZE + 1))
    for _, r in rows.iterrows():
        print(f"  {r['draw_order']:2d}. icpsr={r['icpsr']}  {r['bioname']}  "
              f"({r['state_abbrev']}-{r['district_code']:g})  {r['reason']}")
    rows.to_csv(OUT, index=False)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
