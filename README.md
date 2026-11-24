# Hollowing the Middle? The 2026 Wave and House Polarization

PSCI 4319, UT Dallas · Shyntia Bhattarai

**Live page:** https://shyntiabhattarai.github.io/HousePolarizationProject/ (built from `docs/index.html`)

## Research question

Did the November 3, 2026 U.S. House elections disproportionately remove moderate Republicans?
And among 119th-Congress House members who will return in the 120th, does the gap between party
means on DW-NOMINATE dimension 1 mechanically widen?

## Data

- **Scores:** Voteview `HSall_members.csv`
  (https://voteview.com/static/data/out/members/HSall_members.csv). The download date and SHA-256
  are in `data/raw/SOURCES.md`.
- **Departures:** Ballotpedia snapshots plus state election pages and news reports of AP race calls,
  saved as raw files in `data/sources/` and listed with URL, date and SHA-256 in `data/sources/SOURCES.md`.
- **Plotly.js:** pinned cartesian bundle in `vendor/`, inlined into the page (`vendor/VENDOR.md`).

## How to rebuild

From the project root, using the project's virtual environment (pandas and numpy only):

```
.venv/bin/python -I extract_departures.py   # Ballotpedia snapshots -> data/interim/departures_draft.csv
bash scripts/run_all.sh --force               # worksheet -> verified file -> baseline -> analysis -> page
.venv/bin/python -I scripts/independent_check.py
.venv/bin/python -I scripts/package.py        # -> submission/HousePolarization_submission.zip
```

`run_all.sh` runs `scripts/finalize_verification.py`, `build.py`, `analyze.py` and
`make_artifact.py` in order and stops at the first step that fails.

Tests: `.venv/bin/python -I -m unittest discover -s tests -t . -v`

`.venv/bin/python -I make_artifact.py --fixtures` builds a preview from made-up test data into
`preview/` (git-ignored, marked SYNTHETIC on the page).

## Outputs

| File                                      | What it holds                                                                          |
| ----------------------------------------- | -------------------------------------------------------------------------------------- |
| `data/processed/house119_baseline.csv`    | every 119th House member, with baseline flags                                          |
| `data/processed/cutoffs.csv`              | the pre-registered "moderate" cutoffs                                                  |
| `data/interim/departures_verified.csv`    | the departures used by the analysis                                                    |
| `data/interim/verification_worksheet.csv` | the departures with the second-source check per row                                    |
| `data/interim/decision23_margins.csv`     | the call test for every general-election loss                                          |
| `data/processed/summary.csv`              | every reported number, one per row                                                     |
| `data/processed/gap_combinations.csv`     | party means and gap for every on/off combination of departure groups                   |
| `data/processed/analysis_members.csv`     | every analysed member, with group per scenario                                         |
| `data/processed/permutation_draws_R.csv`  | the 10,000 random draws behind the Q1 p-value                                          |
| `logs/`                                   | the output of each script, including `ai_verification.txt` and `independent_check.txt` |
| `docs/index.html`                         | the self-contained web page served by GitHub Pages                                     |

## Method and decisions

Pre-registered definitions and every judgment call are in `notes/decisions.md`. The AI
collaboration record is in `notes/ai_log.md`.
