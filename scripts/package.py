"""
package.py -- build submission/HousePolarization_submission.zip from the finished project.

Run with:  .venv/bin/python -I scripts/package.py [--include-raw-csv]

Refuses if docs/index.html is missing, or still says "SYNTHETIC TEST DATA" or
"[HEADLINE PENDING]", or a required item is missing. The ZIP's top level holds
README_FIRST.txt and index.html (a copy of docs/index.html, for double-clicking).
The raw Voteview CSV (data/raw/HSall_members.csv) is left out unless --include-raw-csv is
given; data/raw/SOURCES.md gives its URL and SHA-256 instead. After building, the ZIP is
unpacked into a temp folder and its index.html is checked for being self-contained.
"""

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import make_artifact  # noqa: E402  (for self_contained_problems)

OUT = ROOT / "submission" / "HousePolarization_submission.zip"
RAW_CSV = "data/raw/HSall_members.csv"
FILES = ["docs/index.html", "README.md", "build.py", "analyze.py", "make_artifact.py",
         "extract_departures.py", "requirements.txt", "site_config.json", "data/raw/SOURCES.md"]
FOLDERS = ["scripts", "templates", "tests", "vendor", "notes", "logs",
           "data/sources", "data/interim", "data/processed"]
SKIP_PARTS = {".venv", "preview", ".idea", "__pycache__", ".git", "transcripts", "submission"}
SKIP_NAMES = {".DS_Store"}
README_FIRST = "Double-click index.html to view the artifact (works offline). See README.md for how to rebuild.\n"


def refusal_problems(root):
    page = Path(root) / "docs" / "index.html"
    if not page.exists():
        return ["docs/index.html is missing (run make_artifact.py in real mode first)"]
    text = page.read_text(encoding="utf-8")
    problems = []
    if "SYNTHETIC TEST DATA" in text:
        problems.append("docs/index.html contains 'SYNTHETIC TEST DATA' (a fixture build)")
    if "[HEADLINE PENDING]" in text:
        problems.append("docs/index.html contains '[HEADLINE PENDING]' (write notes/headline.md, then rebuild)")
    for item in FILES + FOLDERS:
        if not (Path(root) / item).exists():
            problems.append(f"required item missing: {item}")
    return problems


def members(root, include_raw):
    """(path inside the ZIP, file on disk) for everything that goes in."""
    root = Path(root)
    chosen = [(f, root / f) for f in FILES]
    for folder in FOLDERS:
        for path in sorted((root / folder).rglob("*")):
            rel = path.relative_to(root)
            if path.is_file() and not (set(rel.parts) & SKIP_PARTS) and path.name not in SKIP_NAMES:
                chosen.append((rel.as_posix(), path))
    if include_raw:
        chosen.append((RAW_CSV, root / RAW_CSV))
    chosen.append(("index.html", root / "docs" / "index.html"))
    return chosen


def build(root=ROOT, out=OUT, include_raw=False):
    """Returns (exit code, printed lines)."""
    root, out = Path(root), Path(out)
    lines = []
    raw = root / RAW_CSV
    if raw.exists():
        state = "INCLUDED (--include-raw-csv)" if include_raw else "NOT included (cite URL + SHA-256 in data/raw/SOURCES.md)"
        lines.append(f"Raw Voteview CSV {RAW_CSV}: {raw.stat().st_size:,} bytes -- {state}")
    problems = refusal_problems(root)
    if problems:
        return 1, lines + ["REFUSING to build the submission ZIP:"] + [f"  - {p}" for p in problems]
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README_FIRST.txt", README_FIRST)
        for arcname, path in members(root, include_raw):
            z.write(path, arcname)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out) as z:
        z.extractall(tmp)
        names = sorted(z.namelist())
        total = sum(i.file_size for i in z.infolist())
        index = Path(tmp) / "index.html"
        if not index.exists():
            return 1, lines + ["ERROR: index.html is not at the top of the unpacked ZIP"]
        problems = make_artifact.self_contained_problems(index.read_text(encoding="utf-8"))
        bad_parts = [n for n in names if set(Path(n).parts) & SKIP_PARTS or Path(n).name in SKIP_NAMES]
    lines.append(f"Files in the ZIP ({len(names)}):")
    lines += [f"  {n}" for n in names]
    lines.append(f"Unpacked size: {total:,} bytes; ZIP size: {out.stat().st_size:,} bytes")
    lines.append("Unpacked index.html self-contained: " + ("YES" if not problems else f"NO -- {problems}"))
    if bad_parts:
        lines.append(f"ERROR: excluded paths found in the ZIP: {bad_parts}")
    lines.append(f"Wrote {out.relative_to(root) if out.is_relative_to(root) else out}")
    return (0 if not problems and not bad_parts else 1), lines


def main(argv=None, root=ROOT, out=OUT):
    argv = sys.argv[1:] if argv is None else argv
    code, lines = build(root, out, include_raw="--include-raw-csv" in argv)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
