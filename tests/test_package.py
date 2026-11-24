"""
Tests for scripts/package.py on a SYNTHETIC project tree in a temp folder (never the real docs/).

Run with:  .venv/bin/python -I -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package as PK  # noqa: E402

PLOTLY = (ROOT / "vendor" / "plotly-cartesian-4.3.0.min.js").read_text(encoding="utf-8")
GOOD_PAGE = ('<!doctype html><html><body><h1>Synthetic finished page</h1>'
             f'<script id="plotly-bundle">{PLOTLY}</script></body></html>')


def make_tree(tmp, page=GOOD_PAGE):
    """A minimal fake project: every required file and folder, plus things that must be excluded."""
    root = Path(tmp) / "proj"
    for f in PK.FILES:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text("synthetic\n")
    for folder in PK.FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / "kept.txt").write_text("synthetic\n")
        (root / folder / ".DS_Store").write_text("x")
        (root / folder / "__pycache__").mkdir()
        (root / folder / "__pycache__" / "x.pyc").write_text("x")
    for skipped in [".venv/x", "preview/index_FIXTURES.html", ".idea/x", ".git/x", "transcripts/x", "submission/old.zip"]:
        (root / skipped).parent.mkdir(parents=True, exist_ok=True)
        (root / skipped).write_text("x")
    (root / PK.RAW_CSV).write_text("icpsr,bioname\n1,SYNTHETIC\n")
    if page is not None:
        (root / "docs" / "index.html").write_text(page, encoding="utf-8")
    else:
        (root / "docs" / "index.html").unlink()
    return root


def run(root, out, argv=()):
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        code = PK.main(list(argv), root=root, out=out)
    return code, buf.getvalue()


class TestPackage(unittest.TestCase):

    def test_refuses_missing_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            code, text = run(make_tree(tmp, page=None), out)
            self.assertEqual(code, 1)
            self.assertIn("docs/index.html is missing", text)
            self.assertFalse(out.exists())

    def test_refuses_synthetic_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            code, text = run(make_tree(tmp, GOOD_PAGE.replace("<h1>", "<h1>SYNTHETIC TEST DATA ")), out)
            self.assertEqual(code, 1)
            self.assertIn("SYNTHETIC TEST DATA", text)
            self.assertFalse(out.exists())

    def test_refuses_pending_headline(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            code, text = run(make_tree(tmp, GOOD_PAGE.replace("<h1>", "<h1>[HEADLINE PENDING] ")), out)
            self.assertEqual(code, 1)
            self.assertIn("[HEADLINE PENDING]", text)
            self.assertFalse(out.exists())

    def test_builds_with_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            code, text = run(make_tree(tmp), out)
            self.assertEqual(code, 0, text)
            names = zipfile.ZipFile(out).namelist()
            for required in ["README_FIRST.txt", "index.html", "docs/index.html", "README.md",
                             "data/raw/SOURCES.md", "scripts/kept.txt", "data/interim/kept.txt"]:
                self.assertIn(required, names)
            self.assertFalse([n for n in names if any(p in n for p in
                              [".venv", "preview", ".idea", "__pycache__", ".git/", "transcripts",
                               "submission", ".DS_Store"])], names)
            self.assertNotIn(PK.RAW_CSV, names)
            self.assertIn("Unpacked index.html self-contained: YES", text)
            self.assertIn("NOT included", text)

    def test_include_raw_csv_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            code, text = run(make_tree(tmp), out, ["--include-raw-csv"])
            self.assertEqual(code, 0, text)
            self.assertIn(PK.RAW_CSV, zipfile.ZipFile(out).namelist())

    def test_flags_a_page_that_is_not_self_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.zip"
            page = GOOD_PAGE.replace("</body>", "<script>fetch('https://example.org');</script></body>")
            code, text = run(make_tree(tmp, page), out)
            self.assertEqual(code, 1)
            self.assertIn("self-contained: NO", text)


if __name__ == "__main__":
    unittest.main()
