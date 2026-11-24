"""
Tests for scripts/finalize_verification.py and scripts/progress.py, on SYNTHETIC worksheets
built from tests/fixtures/ in temp folders. The real worksheet is never read or written.

Run with:  .venv/bin/python -I -m unittest discover -s tests -t . -v
"""

import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import finalize_verification as F  # noqa: E402
import progress as P  # noqa: E402
import worksheet_common as W  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
ORDER = {"pending": 2, "lost_general": 5, "lost_primary": 6}


def good_worksheet():
    """The fixture departures as a fully verified worksheet: every check_order 1-7 row has
    Y or N plus a second source; the two blank sampled-out rows sit in check_order 8."""
    ws = W.analyze.read_departures(FIX / "departures.csv")
    ws["check_order"] = [8 if r["ai_verified"] == "" else ORDER.get(r["reason"], 7) for _, r in ws.iterrows()]
    ws["check_reason"] = "synthetic"
    ws["search_link"] = "https://www.google.com/search?q=synthetic"
    # helper columns deliberately NOT last, to prove the output order comes from the draft schema
    return ws[["check_order"] + W.analyze.REQUIRED_COLUMNS + ["check_reason", "search_link"]]


class TestFinalize(unittest.TestCase):

    def run_finalize(self, ws, tmp, force=False, existing=False):
        tmp = Path(tmp)
        ws_path, out = tmp / "worksheet.csv", tmp / "departures_verified.csv"
        ws.to_csv(ws_path, index=False)
        if existing:
            out.write_text("old file\n")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = F.main(["--force"] if force else [], worksheet=ws_path, out=out, baseline=FIX / "members.csv")
        return code, buf.getvalue(), out

    def test_success_and_column_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(good_worksheet(), tmp)
            self.assertEqual(code, 0, text)
            result = pd.read_csv(out, dtype=str, keep_default_na=False)
            self.assertEqual(list(result.columns), W.analyze.REQUIRED_COLUMNS)   # draft order + ai_* (decision 20)
            self.assertEqual((result[W.analyze.AUTHOR_COLUMNS] == "").all().all(), True)
            self.assertEqual(len(result), 10)
            self.assertIn("validation (validation only, no analysis): PASSED", text)
            self.assertIn("Rows with ai_verified N (departure claim false", text)

    def test_refuses_blank_verified_in_order_1_to_7(self):
        ws = good_worksheet()
        ws.loc[ws["icpsr"] == "101", "ai_verified"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(ws, tmp)
            self.assertEqual(code, 1)
            self.assertIn("blank ai_verified (and no decision-21 note): 1", text)
            self.assertIn("icpsr=101", text)
            self.assertFalse(out.exists())

    def test_refuses_Y_or_N_without_second_source(self):
        for mark in ["Y", "N"]:
            ws = good_worksheet()
            ws.loc[ws["icpsr"] == "202", ["ai_verified", "ai_second_source_url"]] = [mark, ""]
            with tempfile.TemporaryDirectory() as tmp, self.subTest(mark=mark):
                code, text, out = self.run_finalize(ws, tmp)
                self.assertEqual(code, 1)
                self.assertIn("empty ai_second_source_url or ai_source_type: 1", text)
                self.assertFalse(out.exists())

    def test_refuses_blair_row_with_blank_icpsr(self):
        ws = good_worksheet()
        blair = {c: "" for c in ws.columns}
        blair.update({"check_order": 1, "bioname": "SYNTHETIC, Blair", "state_abbrev": "ZZ", "district_code": "13",
                      "verified_by": "ai", "ai_verified": "Y", "ai_source_type": "ap",
                      "ai_second_source_url": "https://apnews.com/synthetic"})
        ws = pd.concat([pd.DataFrame([blair]), ws], ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(ws, tmp)
            self.assertEqual(code, 1)
            self.assertIn("Blair row (check_order 1) with a blank icpsr: 1", text)
            self.assertFalse(out.exists())

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(good_worksheet(), tmp, existing=True)
            self.assertEqual(code, 1)
            self.assertIn("--force", text)
            self.assertEqual(out.read_text(), "old file\n")              # untouched
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(good_worksheet(), tmp, force=True, existing=True)
            self.assertEqual(code, 0, text)
            self.assertNotEqual(out.read_text(), "old file\n")

    def test_decision21_unresolved_row_is_accepted_with_note(self):
        ws = good_worksheet()
        ws.loc[ws["icpsr"] == "202", ["ai_verified", "ai_source_type", "ai_second_source_url"]] = ["", "", ""]
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(ws, tmp)
            self.assertEqual(code, 1)                                    # blank without the note: refused
        ws.loc[ws["icpsr"] == "202", "notes"] = "no second source obtained (synthetic)"
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(ws, tmp)
            self.assertEqual(code, 0, text)
            self.assertIn("Unresolved rows (decision 21): 1", text)

    def test_refuses_when_analysis_validation_fails(self):
        ws = good_worksheet()
        ws.loc[ws["icpsr"] == "202", "icpsr"] = "999"                    # not in the baseline
        with tempfile.TemporaryDirectory() as tmp:
            code, text, out = self.run_finalize(ws, tmp)
            self.assertEqual(code, 1)
            self.assertIn("FAILED", text)
            self.assertFalse(out.exists())


class TestProgress(unittest.TestCase):

    def test_progress_is_read_only_and_flags_decision17(self):
        ws = good_worksheet()
        ws.loc[ws["icpsr"] == "202", "ai_second_source_url"] = ""       # verified, no second source
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worksheet.csv"
            ws.to_csv(path, index=False)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            text = "\n".join(P.report(W.read_worksheet(path)))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["worksheet.csv"])
        self.assertIn("Verified but ai_second_source_url or ai_source_type empty: 1", text)
        self.assertIn("FLAG: not state/ap/news_reporting_ap", text)       # fixture row 105 (Ballotpedia)
        self.assertIn("ai_verified N: 1", text)


if __name__ == "__main__":
    unittest.main()
