"""
Tests for scripts/independent_check.py on the SYNTHETIC fixtures (temp folder; no real data).
Hand values (see tests/test_analysis.py): R lost_general mean = (0.1+0.2+0.7)/3 = 0.3333333333;
G0 = 2.8/6 + 0.35 = 0.8166666667; returning-only gap = 0.6 + 0.4 = 1.0.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import independent_check as IC  # noqa: E402
import make_artifact  # noqa: E402


class TestIndependentCheck(unittest.TestCase):

    def test_matches_on_fixtures_and_catches_a_wrong_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                paths = make_artifact.run_fixture_analysis(tmp)
                code = IC.main(paths["members"], paths["summary"], Path(tmp) / "check.txt")
            self.assertEqual(code, 0)
            text = (Path(tmp) / "check.txt").read_text()
            self.assertIn("RESULT: all three match to 1e-9", text)
            self.assertIn("0.333333333333", text)
            self.assertIn("0.816666666667", text)
            self.assertIn("1.000000000000", text)
            s = pd.read_csv(paths["summary"])                       # corrupt one number -> must fail
            mask = (s["question"] == "Q2") & (s["scenario"] == "main") & (s["group"] == "G0 (all analysed)") & (s["metric"] == "gap")
            s.loc[mask, "value"] += 1e-6
            s.to_csv(paths["summary"], index=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(IC.main(paths["members"], paths["summary"], Path(tmp) / "check2.txt"), 1)
            self.assertIn("MISMATCH", (Path(tmp) / "check2.txt").read_text())

    def test_does_not_import_analyze(self):
        import ast
        tree = ast.parse((ROOT / "scripts" / "independent_check.py").read_text())
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({"analyze", "make_artifact", "worksheet_common"} & imported, imported)


if __name__ == "__main__":
    unittest.main()
