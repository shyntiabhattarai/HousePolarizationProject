"""
Tests for make_artifact.py. Everything is built from the SYNTHETIC fixtures into temp folders;
real mode is only ever exercised on copies of fixture outputs. (Decision-19 tests: see
tests/test_analysis.py, test_11_decision19_N_means_returning.)

Run with:  .venv/bin/python -I -m unittest discover -s tests -t . -v
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import make_artifact as M  # noqa: E402
import contextlib, io  # noqa: E402,E401

SECTION_IDS = ["header", "caveats", "what-is", "dotplot", "before-after", "moderate-test",
               "robustness", "departures", "methods"]
# Numbers that are fixed wording, not data (Shyntia approved this allowlist, 2026-11-23).
ALLOWED = [r"November 3, 2026", r"\b2026\b", r"\bNov\.? 3\b", r"\b119th\b", r"\b120th\b",
           r"\bdimension 1\b", r"\bdecision \d+\b", r"\bG0\b", r"SHA-256",
           r"\{\{[A-Z0-9_]+\}\}"]   # last one: template placeholders (not visible on the page)
FORBIDDEN, VENDOR_EXCEPTIONS = M.FORBIDDEN, M.VENDOR_EXCEPTIONS   # defined in make_artifact.py


class Visible(HTMLParser):
    """Collect visible text (outside script/style), noting which text sits inside an element
    carrying data-metric, the author's headline, a decisions.md quote, or the scale-bar zero."""
    VOID = {"meta", "br", "input", "img", "hr", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.free, self.metrics, self.quotes, self.ids = [], [], [], [], set()
        self._metric = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag in self.VOID:
            return
        kind = ("skip" if tag in ("script", "style", "title") else
                "metric" if "data-metric" in a else
                "exempt" if "data-headline" in a or "data-quote-of" in a or "scale-zero" in a.get("class", "") else None)
        self.stack.append((tag, kind, a))
        if kind == "metric":
            self._metric = {"key": a["data-metric"], "fmt": a["data-fmt"], "text": ""}
            self.metrics.append(self._metric)
        if "data-quote-of" in a:
            self.quotes.append("")

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        while self.stack:
            t, kind, _ = self.stack.pop()
            if kind == "metric":
                self._metric = None
            if t == tag:
                break

    def handle_data(self, data):
        kinds = {k for _, k, _ in self.stack}
        if "skip" in kinds:
            return
        if "metric" in kinds:
            self._metric["text"] += data
        elif "exempt" in kinds:
            if any("data-quote-of" in a for _, _, a in self.stack):
                self.quotes[-1] += data
        else:
            self.free.append(data)


self_contained_problems = M.self_contained_problems   # the same check package.py uses


def stray_digits(text):
    for pattern in ALLOWED:
        text = re.sub(pattern, "", text)
    return re.findall(r"\d+", text)


def build_fixture(tmp):
    with contextlib.redirect_stdout(io.StringIO()):
        paths = M.run_fixture_analysis(tmp)
    out = M.render(paths, fixture=True, out_path=Path(tmp) / "index_FIXTURES.html")
    return paths, out.read_text(encoding="utf-8")


class TestArtifact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths, cls.page = build_fixture(cls.tmp.name)
        cls.parsed = Visible()
        cls.parsed.feed(cls.page)
        cls.data = json.loads(re.search(r'<script type="application/json" id="page-data">(.*?)</script>',
                                        cls.page, re.S).group(1))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def resolve(self, key):
        """Look a data-metric key up in the CSV / source file it names."""
        ns, rest = key.split(":", 1)
        parts = rest.split("|")
        if ns == "summary":
            q, scen, party, group, metric, col = parts
            s = pd.read_csv(self.paths["summary"])
            row = s[(s["question"] == q) & (s["scenario"] == scen) & (s["party"] == party)
                    & (s["group"] == group) & (s["metric"] == metric)]
            self.assertEqual(len(row), 1, key)
            return row[col].iloc[0]
        if ns == "combo":
            scen, bits, col = parts[:3]
            c = pd.read_csv(self.paths["combos"])
            mask = (c["scenario"] == scen)
            for g, b in zip(M.GROUPS, bits):
                mask &= c[g] == int(b)
            self.assertEqual(mask.sum(), 1, key)
            value = c.loc[mask, col].iloc[0]
            return abs(value) if parts[3:] == ["abs"] else value
        if ns in ("members", "baseline"):
            df = pd.read_csv(self.paths[ns])
            return df.loc[df["icpsr"] == int(parts[0]), parts[1]].iloc[0]
        if ns == "dep":
            df = pd.read_csv(self.paths["departures"])
            return float(df.loc[df["icpsr"] == int(parts[0]), parts[1]].iloc[0])
        if ns == "meta":
            return self.independent_meta(parts[0])
        self.fail(f"unknown namespace in {key}")

    def independent_meta(self, name):
        """Meta values re-derived here from the files, not from make_artifact's own parsing."""
        raw = (ROOT / "data" / "raw" / "SOURCES.md").read_text()
        snap = (ROOT / "data" / "sources" / "SOURCES.md").read_text()
        meta = self.data["meta"]
        if name == "voteview_sha256":
            return re.search(r"\b[0-9a-f]{64}\b", raw).group(0)
        if name == "voteview_downloaded":
            self.assertIn(meta[name], raw)
            return meta[name]
        if name == "snapshot_count":
            return len(list((ROOT / "data" / "sources").glob("2026-*_ballotpedia-*.html")))
        if name == "ai_source_files":
            files = list((ROOT / "data" / "sources").glob("2026-*"))
            return len([f for f in files if "_ballotpedia-" not in f.name])
        if name == "snapshot_access_dates":
            for d in meta[name].split(", "):
                self.assertIn(f"| {d} ", snap)
            return meta[name]
        if name == "plotly_version":
            return re.search(r"plotly\.js v([\d.]+)", (ROOT / "vendor" / "VENDOR.md").read_text()).group(1)
        if name == "n_draws":
            return len(pd.read_csv(self.paths["draws"]))
        if name == "git_commit":
            head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True).stdout.strip()
            self.assertTrue(meta[name].startswith(head))
            return meta[name]
        if name == "build_time":
            self.assertRegex(meta[name], r"^\d{4}-\d\d-\d\d \d\d:\d\d")
            return meta[name]
        self.fail(f"unknown meta key {name}")

    # 1. Number provenance.
    def test_1_number_provenance(self):
        self.assertGreater(len(self.parsed.metrics), 50)
        for m in self.parsed.metrics:
            expected = M.fmt(self.resolve(m["key"]), m["fmt"])
            self.assertEqual(m["text"].strip(), expected, m["key"])
        stray = [(t.strip(), stray_digits(t)) for t in self.parsed.free if stray_digits(t)]
        self.assertEqual(stray, [], "visible numbers without data-metric")
        decisions = (ROOT / "notes" / "decisions.md").read_text()
        for q in self.parsed.quotes:
            self.assertIn(q, decisions)                       # quotes are word for word

    def test_1b_template_has_no_numeric_literals(self):
        template = Visible()
        template.feed(M.TEMPLATE.read_text(encoding="utf-8"))
        stray = [(t.strip(), stray_digits(t)) for t in template.free if stray_digits(t)]
        self.assertEqual(stray, [])
        self.assertEqual(template.metrics, [])

    # 2. Self-contained.
    def test_2_self_contained(self):
        self.assertEqual(self_contained_problems(self.page), [])

    # 2b. The checker catches network code OUTSIDE the vendor block -- XMLHttpRequest included,
    #     even though one XMLHttpRequest is allowed INSIDE it -- and an extra one inside it.
    def test_2b_self_contained_checker_catches_violations(self):
        for injected in ["<script>var r = new XMLHttpRequest();</script>", "<script>fetch('x');</script>",
                         '<link rel="stylesheet" href="https://example.org/x.css">']:
            bad = self.page.replace("</body>", injected + "</body>")
            self.assertTrue(any("outside vendor block" in p for p in self_contained_problems(bad)), injected)
        marker = '<script id="plotly-bundle">'
        bad = self.page.replace(marker, marker + "/*XMLHttpRequest*/")
        problems = self_contained_problems(bad)
        self.assertTrue(any("appears 2 times (allowed 1)" in p for p in problems), problems)
        self.assertTrue(any("not byte-identical" in p for p in problems), problems)

    # 3. Banner in fixture mode; absent in a real-mode build run on copied fixture outputs.
    def test_3_banner(self):
        self.assertIn('id="fixture-banner"', self.page)
        self.assertIn("SYNTHETIC TEST DATA \u2014 NOT REAL RESULTS", self.page)
        with tempfile.TemporaryDirectory() as tmp:
            real = self.copy_as_real(Path(tmp))
            code = self.quiet_main(real, Path(tmp) / "docs" / "index.html")
            self.assertEqual(code, 0)
            built = (Path(tmp) / "docs" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn('id="fixture-banner"', built)
            self.assertNotIn("SYNTHETIC TEST DATA", built)

    # 4. Real mode refuses when an input is missing or the log doesn't show validation passed.
    def test_4_real_mode_refuses(self):
        for missing in M.REAL_INPUTS:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(missing=missing):
                real = self.copy_as_real(Path(tmp))
                real[missing].unlink()
                out = Path(tmp) / "docs" / "index.html"
                self.assertEqual(self.quiet_main(real, out), 1)
                self.assertFalse(out.exists())
        with tempfile.TemporaryDirectory() as tmp:
            real = self.copy_as_real(Path(tmp))
            real["log"].write_text("VALIDATION: something\nSTOPPED: departures file failed validation\n")
            out = Path(tmp) / "docs" / "index.html"
            self.assertEqual(self.quiet_main(real, out), 1)
            self.assertFalse(out.exists())
        # Real inputs: refused exactly when one is missing or the log lacks VALIDATION PASSED.
        missing = [p for p in M.REAL_INPUTS.values() if not Path(p).exists()]
        log_ok = M.REAL_INPUTS["log"].exists() and M.analyze.VALIDATION_PASSED in M.REAL_INPUTS["log"].read_text().splitlines()
        self.assertEqual(M.real_mode_problems(M.REAL_INPUTS) == [], not missing and log_ok)

    # 5. Embedded JSON parses; row counts match the CSVs.
    def test_5_embedded_json(self):
        p = self.paths
        self.assertEqual(len(self.data["members"]), len(pd.read_csv(p["members"])))
        self.assertEqual(len(self.data["summary"]), len(pd.read_csv(p["summary"])))
        self.assertEqual(len(self.data["combos"]), len(pd.read_csv(p["combos"])))
        self.assertEqual(len(self.data["combos"]), 80)
        self.assertEqual(len(self.data["draws"]), len(pd.read_csv(p["draws"])))
        self.assertEqual(len(self.data["departures"]), len(pd.read_csv(p["departures"])))

    # 6. Every Part 3 section is present.
    def test_6_sections_present(self):
        for sid in SECTION_IDS:
            self.assertIn(sid, self.parsed.ids, sid)

    # 7. Headline placeholder when notes/headline.md is TODO; author text otherwise.
    def test_7_headline(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = M.HEADLINE_FILE
            try:
                M.HEADLINE_FILE = Path(tmp) / "headline.md"
                M.HEADLINE_FILE.write_text("TODO (Shyntia writes this after seeing real results)\n")
                self.assertIn('data-headline="pending"', M.headline_html())
                self.assertIn("[HEADLINE PENDING]", M.headline_html())
                M.HEADLINE_FILE.write_text("A synthetic headline for the test.")
                self.assertIn('data-headline="author"', M.headline_html())
                self.assertNotIn("PENDING", M.headline_html())
            finally:
                M.HEADLINE_FILE = original

    # 8. Dots follow the scenario: each scenario's traces put every member exactly where that
    #    scenario's group column in analysis_members.csv says. Fixture member 103 is pending:
    #    main -> the "excluded" trace (grey x); scenario A -> the lost_general trace.
    def test_8_dotplot_follows_scenario(self):
        members = pd.read_csv(self.paths["members"]).set_index("icpsr")
        traces = self.data["dotplot"]["traces"]
        self.assertEqual(sorted(traces), sorted(M.analyze.COMBO_SCENARIOS))
        for scenario, tr in traces.items():
            col = members[f"group_{scenario}"]
            seen = []
            for trace in tr:
                for icpsr in trace["ids"]:
                    group = col[int(icpsr)]
                    expected = ("excluded" if group.startswith("excluded") else
                                "returning" if group == "returning" else group)
                    self.assertEqual(trace["meta"], expected, (scenario, icpsr))
                    seen.append(int(icpsr))
            self.assertEqual(sorted(seen), sorted(members.index))   # every member once
        where = {s: {t["meta"] for t in tr if "103" in t["ids"]} for s, tr in traces.items()}
        self.assertEqual(where["main"], {"excluded"})
        self.assertEqual(where["scenario_A"], {"lost_general"})
        self.assertEqual(where["scenario_B"], {"returning"})

    # 9. Repo link: empty repo_url in site_config.json -> visible "[repo link pending]"; a URL -> a link.
    def test_9_repo_link(self):
        self.assertIn("repo_url", json.loads((ROOT / "site_config.json").read_text()))
        with tempfile.TemporaryDirectory() as tmp:
            original = M.SITE_CONFIG
            try:
                M.SITE_CONFIG = Path(tmp) / "site_config.json"
                M.SITE_CONFIG.write_text('{"repo_url": ""}')
                self.assertIn('data-repo="pending">[repo link pending]</span>', M.repo_link_html())
                M.SITE_CONFIG.write_text('{"repo_url": "https://github.com/example/repo"}')
                self.assertIn('href="https://github.com/example/repo"', M.repo_link_html())
                self.assertNotIn("pending", M.repo_link_html())
                M.SITE_CONFIG.write_text('{"repo_url": "   "}')
                self.assertIn("[repo link pending]", M.repo_link_html())
            finally:
                M.SITE_CONFIG = original

    # helpers
    def copy_as_real(self, tmp):
        real = {}
        for name, src in self.paths.items():
            dst = tmp / f"{name}_{Path(src).name}"
            shutil.copy(src, dst)
            real[name] = dst
        return real

    @staticmethod
    def quiet_main(real, out):
        with contextlib.redirect_stdout(io.StringIO()):
            return M.main([], real_paths=real, real_out=out)


if __name__ == "__main__":
    unittest.main()
