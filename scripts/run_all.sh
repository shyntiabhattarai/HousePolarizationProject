#!/usr/bin/env bash
# run_all.sh -- after verification: worksheet -> verified file -> baseline -> analysis -> page.
#
# Run from the project root:   bash scripts/run_all.sh            (first time)
#                              bash scripts/run_all.sh --force    (re-run after fixing the worksheet:
#                                                                  lets step 1 overwrite departures_verified.csv)
# Any arguments are passed to step 1 (finalize_verification.py) only.
# Stops at the first step that fails and says which one.

cd "$(dirname "$0")/.." || exit 1
PY=".venv/bin/python"

step() {
  local n="$1"; shift
  echo
  echo "=== Step $n: $* ==="
  if ! "$@"; then
    echo
    echo "STOPPED: step $n failed ($*). Nothing after it was run."
    exit 1
  fi
}

step 1 "$PY" -I scripts/finalize_verification.py "$@"
step 2 "$PY" -I build.py
step 3 "$PY" -I analyze.py
step 4 "$PY" -I make_artifact.py
echo
echo "All 4 steps finished. Next: read logs/analysis_phase3.txt, write notes/headline.md,"
echo "re-run: $PY -I make_artifact.py   then:   $PY -I scripts/package.py"
