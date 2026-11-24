"""
make_artifact.py -- Phase 4: build the self-contained web page from the analysis outputs.

  .venv/bin/python -I make_artifact.py --fixtures   SYNTHETIC preview -> preview/index_FIXTURES.html
  .venv/bin/python -I make_artifact.py              REAL page        -> docs/index.html (GitHub Pages)

Fixture mode runs analyze.py's pipeline on tests/fixtures/ in a temp folder; the page carries
a red "SYNTHETIC TEST DATA" banner, and preview/ is git-ignored. Real mode refuses to run
unless every analysis output exists and logs/analysis_phase3.txt says VALIDATION PASSED.

Rules: every number on the page is formatted HERE, in Python, from a CSV row or a source file,
and wrapped in <span data-metric="namespace:key">. The page's JavaScript only looks values up,
sorts, filters and draws; it does no arithmetic on scores. Everything is inlined (Plotly, CSS,
JS, data): no external scripts, styles, fonts or network requests.
"""

import argparse
import contextlib
import datetime
import hashlib
import html
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import analyze  # noqa: E402

TEMPLATE = ROOT / "templates" / "index.template.html"
PLOTLY_FILE = ROOT / "vendor" / "plotly-cartesian-4.3.0.min.js"
HEADLINE_FILE = ROOT / "notes" / "headline.md"
DECISIONS_FILE = ROOT / "notes" / "decisions.md"
VOTEVIEW_SOURCES = ROOT / "data" / "raw" / "SOURCES.md"
SNAPSHOT_SOURCES = ROOT / "data" / "sources" / "SOURCES.md"
FIXTURE_OUT = ROOT / "preview" / "index_FIXTURES.html"
REAL_OUT = ROOT / "docs" / "index.html"
JITTER_SEED = 20261103
HIST_BINS = 40
SITE_CONFIG = ROOT / "site_config.json"          # {"repo_url": ""} shows "[repo link pending]"

REAL_INPUTS = {
    "summary": ROOT / "data" / "processed" / "summary.csv",
    "combos": ROOT / "data" / "processed" / "gap_combinations.csv",
    "members": ROOT / "data" / "processed" / "analysis_members.csv",
    "draws": ROOT / "data" / "processed" / "permutation_draws_R.csv",
    "log": ROOT / "logs" / "analysis_phase3.txt",
    "departures": ROOT / "data" / "interim" / "departures_verified.csv",
    "baseline": ROOT / "data" / "processed" / "house119_baseline.csv",
}

GROUPS = analyze.DEPARTURE_GROUPS
GROUP_LABEL = {"lost_general": "Lost general election", "lost_primary": "Lost primary",
               "retired": "Retired", "ran_other_office": "Ran for other office",
               "returning": "Returning", "excluded_pending": "Pending race (excluded)",
               "excluded_demoted": "Unconfirmed loss (excluded, decision 17)",
               "excluded_unresolved": "No second source obtained (excluded, decision 21)",
               "excluded_low_votes": "Low-vote member (excluded in this check)",
               "excluded_same_party_general": "Same-party general-election loss (excluded in this check)"}
SCENARIO_LABEL = {"main": "Main analysis", "scenario_A": "Scenario A: every pending incumbent loses",
                  "scenario_B": "Scenario B: every pending incumbent wins",
                  "no_low_votes": "Without low-vote members",
                  "no_same_party_general": "Without same-party general-election losses",
                  "state_sources_only": "Only losses confirmed by a state .gov source (decision 22)",
                  "certified_or_ap_only": "Only certified state results or AP-cited calls (decision 23)",
                  "decision17_check": "Sanity check: decision 17 filter re-derived"}
# Colors: party = conventional blue/red; reasons = validated (dataviz validate_palette.js,
# light mode, all pairs) and always paired with a distinct hollow marker shape + legend label.
PARTY_COLOR = {"Democrat": "#2a78d6", "Republican": "#e34948"}
REASON_STYLE = {"lost_general": ("#c98500", "circle-open"), "lost_primary": ("#1baf7a", "triangle-up-open"),
                "retired": ("#3b3a37", "square-open"), "ran_other_office": ("#7a7974", "diamond-open"),
                "excluded": ("#9a9994", "x-thin-open")}


# ------------------------------------------------------------------ formatting
def fmt(value, how):
    """How every number is displayed. 'd3' = 3 decimals, 'd4' = 4, 'int', 'pct' = percent with
    1 decimal, 'raw' = text as-is. Negative numbers use a true minus sign."""
    if how == "raw":
        return str(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if how == "int":
        text = f"{int(round(float(value))):,}"          # thousands separator: 10,000
    elif how == "pct":
        text = f"{float(value) * 100:.1f}%"
    else:
        text = f"{float(value):.{int(how[1:])}f}"
    return text.replace("-", "−")


def num(value, how, key):
    """A displayed number, tagged with where it comes from (checked by tests/test_artifact.py)."""
    return (f'<span class="num" data-metric="{html.escape(key)}" data-fmt="{how}">'
            f"{html.escape(fmt(value, how))}</span>")


def esc(text):
    return html.escape("" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text))


def domain(url):
    return (urlparse(str(url)).hostname or "") if isinstance(url, str) and url else ""


# ------------------------------------------------------------------ inputs
class Summary:
    """Look-ups into summary.csv by (question, scenario, party, group, metric)."""

    def __init__(self, df):
        self.df = df

    def row(self, q, scenario, party, group, metric):
        s = self.df
        hit = s[(s["question"] == q) & (s["scenario"] == scenario) & (s["party"] == party)
                & (s["group"] == group) & (s["metric"] == metric)]
        return None if len(hit) != 1 else hit.iloc[0]

    def value(self, q, scenario, party, group, metric, column="value"):
        r = self.row(q, scenario, party, group, metric)
        return None if r is None else r[column]

    def span(self, q, scenario, party, group, metric, how, column="value"):
        key = f"summary:{q}|{scenario}|{party}|{group}|{metric}|{column}"
        return num(self.value(q, scenario, party, group, metric, column), how, key)


def combo_key(scenario, bits):
    return f"{scenario}|{''.join(str(int(b)) for b in bits)}"


def load_inputs(paths):
    data = {"summary": pd.read_csv(paths["summary"]),
            "combos": pd.read_csv(paths["combos"]),
            "members": pd.read_csv(paths["members"]),
            "draws": pd.read_csv(paths["draws"]),
            "departures": analyze.read_departures(paths["departures"]),
            "baseline": pd.read_csv(paths["baseline"])}
    data["members"]["flags"] = data["members"]["flags"].fillna("")
    return data


def collect_meta(n_draws):
    """Values for the methods footer, each read from a file (or git) -- never typed in."""
    raw = VOTEVIEW_SOURCES.read_text()
    snap = SNAPSHOT_SOURCES.read_text()
    rows = re.findall(r"^\| (2026-[^|]+\.[a-z]+) \| [^|]+ \| [^|]+ \| (\d{4}-\d\d-\d\d) [\d:]+ \|", snap, re.M)
    ballotpedia = [r for r in rows if "_ballotpedia-" in r[0]]
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.strip() != ""
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unknown", False
    return {
        "voteview_downloaded": re.search(r"Downloaded \(local time\):\*\* (.+?) \(", raw).group(1),
        "voteview_sha256": re.search(r"SHA-256:\*\* ([0-9a-f]{64})", raw).group(1),
        "snapshot_count": len(ballotpedia),
        "ai_source_files": len(rows) - len(ballotpedia),
        "snapshot_access_dates": ", ".join(sorted({d for _, d in rows})),
        "plotly_version": re.search(r"plotly-cartesian-([\d.]+)\.min\.js", PLOTLY_FILE.name).group(1),
        "git_commit": commit + (" (uncommitted changes)" if dirty else ""),
        "build_time": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "n_draws": n_draws,
    }


def meta_span(meta, key, how="raw"):
    return num(meta[key], how, f"meta:{key}")


def decision_text(number):
    """Decision N, word for word, from notes/decisions.md."""
    m = re.search(rf"^{number}\. (.+)$", DECISIONS_FILE.read_text(), re.M)
    return m.group(1) if m else ""


# ------------------------------------------------------------------ page pieces
def repo_link_html():
    """Footer repo link from site_config.json; an empty repo_url shows a visible placeholder."""
    url = json.loads(SITE_CONFIG.read_text()).get("repo_url", "").strip() if SITE_CONFIG.exists() else ""
    if not url:
        return '<span id="repo-link" data-repo="pending">[repo link pending]</span>'
    return f'<a id="repo-link" data-repo="set" href="{esc(url)}">{esc(url)}</a>'


def headline_html():
    text = HEADLINE_FILE.read_text().strip() if HEADLINE_FILE.exists() else "TODO"
    if text.upper().startswith("TODO"):
        return ('<div id="headline" class="headline pending" data-headline="pending">'
                "<strong>[HEADLINE PENDING]</strong> The author writes the headline after reviewing "
                "the verified results (notes/headline.md).</div>")
    paras = "".join(f"<p>{esc(p)}</p>" for p in text.split("\n\n"))
    return (f'<div id="headline" class="headline" data-headline="author">'
            f'<div class="label">Author’s summary</div>{paras}</div>')


def combos_payload(combos):
    """Every toggle state, with display strings already formatted (JS only looks them up)."""
    out = {}
    for _, r in combos.iterrows():
        bits = [r[g] for g in GROUPS]
        key = combo_key(r["scenario"], bits)
        cells = {}
        for col, how in [("mean_D", "d3"), ("mean_R", "d3"), ("gap", "d3"), ("delta_gap", "d3"),
                         ("n_D", "int"), ("n_R", "int")]:
            cells[col] = {"text": fmt(r[col], how), "metric": f"combo:{key}|{col}", "fmt": how}
        cells["sentence"] = sentence(r, key)
        out[key] = {"cells": cells, "mean_D": float(r["mean_D"]), "mean_R": float(r["mean_R"])}
    return out


def sentence(r, key):
    """The one-line reading of a toggle state. Direction words come from the SIGNS of the
    looked-up deltas; the number shown is the size of the gap change."""
    if not any(r[g] for g in GROUPS):
        return "No groups removed: this is the starting gap among all analysed members (G0)."
    d_gap, d_r, d_d = r["delta_gap"], r["delta_mean_R"], r["delta_mean_D"]
    if abs(d_gap) < 5e-7:
        return "Removing these members leaves the gap unchanged at the displayed precision."
    verb = "widens" if d_gap > 0 else "narrows"
    if abs(d_r) >= abs(d_d):
        why = f"the Republican mean moves {'right' if d_r > 0 else 'left'}"
    else:
        why = f"the Democratic mean moves {'left' if d_d < 0 else 'right'}"
    size = num(abs(d_gap), "d3", f"combo:{key}|delta_gap|abs")
    return f"Removing these members {verb} the gap by {size}, mostly because {why}."


def dotplot_spec(members, combos, summary):
    """Plotly traces + layout for the dot plot. Jitter is fixed (seeded) and computed here."""
    m = members.sort_values("icpsr").reset_index(drop=True)
    rng = np.random.default_rng(JITTER_SEED)
    m["y"] = np.where(m["party"] == "Republican", 1.0, 0.0) + rng.uniform(-0.28, 0.28, len(m))

    def hover(r, col):
        moderate = "yes" if str(r["moderate"]).lower() in ("true", "1", "yes") else "no"
        group = GROUP_LABEL.get(r[col], r[col])
        src = domain(r.get("ai_second_source_url")) or domain(r.get("source_url"))
        return (f"<b>{esc(r['bioname'])}</b><br>{esc(r['state_abbrev'])}-{int(r['district_code'])}"
                f"<br>dim1 {fmt(r['nominate_dim1'], 'd3')} \u00b7 moderate: {moderate}"
                f"<br>group: {esc(group)}<br>reason in file: {esc(r.get('reason')) or '\u2014'}"
                f"<br>verified: {esc(r.get('ai_verified')) or '—'} "
                f"({esc(r.get('ai_source_type')) or 'no second source'})"
                f"<br>source: {esc(src) or '\u2014'}")

    def traces_for(col):
        """One set of traces using the scenario's own group column in analysis_members.csv.
        Trace order and names are the same in every scenario; 'ids' are icpsr codes."""
        traces = []
        for party in ["Democrat", "Republican"]:
            part = m[(m["party"] == party) & (m[col] == "returning")]
            traces.append({"type": "scatter", "mode": "markers", "name": f"{party}s, returning",
                           "x": part["nominate_dim1"].tolist(), "y": part["y"].tolist(),
                           "ids": part["icpsr"].astype(str).tolist(),
                           "text": [hover(r, col) for _, r in part.iterrows()], "hoverinfo": "text",
                           "customdata": [""] * len(part), "meta": "returning",
                           "marker": {"color": PARTY_COLOR[party], "size": 8, "symbol": "circle",
                                      "line": {"color": "#fcfcfb", "width": 1}}})
        for group in GROUPS + ["excluded"]:
            sel = m[col].str.startswith("excluded") if group == "excluded" else m[col] == group
            part = m[sel]
            color, symbol = REASON_STYLE[group]
            name = ("Pending, unconfirmed, or excluded in this scenario" if group == "excluded"
                    else f"Departing: {GROUP_LABEL[group].lower()}")
            traces.append({"type": "scatter", "mode": "markers", "name": name,
                           "x": part["nominate_dim1"].tolist(), "y": part["y"].tolist(),
                           "ids": part["icpsr"].astype(str).tolist(),
                           "text": [hover(r, col) for _, r in part.iterrows()], "hoverinfo": "text",
                           "customdata": [str(r["source_url"]) if isinstance(r["source_url"], str) else ""
                                          for _, r in part.iterrows()], "meta": group,
                           "marker": {"color": color, "size": 10, "symbol": symbol,
                                      "line": {"color": color, "width": 2}}})
        return traces

    by_scenario = {s: traces_for(f"group_{s}") for s in analyze.COMBO_SCENARIOS}
    r_cut = summary.value("cutoffs", "main", "Republican", "B", "cutoff")
    d_cut = summary.value("cutoffs", "main", "Democrat", "B", "cutoff")
    g0 = combos[combo_key("main", [0, 0, 0, 0])]
    after = combos[combo_key("main", [1, 1, 1, 1])]
    # Moderate zones: D from the D cutoff up to the most conservative Democrat; R from the most
    # liberal Republican up to the R cutoff (decision 6).
    d_max = float(m.loc[m["party"] == "Democrat", "nominate_dim1"].max())
    r_min = float(m.loc[m["party"] == "Republican", "nominate_dim1"].min())
    shapes = [
        {"type": "rect", "xref": "x", "yref": "y", "x0": d_cut, "x1": d_max + 0.02, "y0": -0.42, "y1": 0.42,
         "fillcolor": "rgba(42,120,214,0.10)", "line": {"width": 0}, "layer": "below"},
        {"type": "rect", "xref": "x", "yref": "y", "x0": r_min - 0.02, "x1": r_cut, "y0": 0.58, "y1": 1.42,
         "fillcolor": "rgba(227,73,72,0.10)", "line": {"width": 0}, "layer": "below"},
    ]
    # indexes 2-5: mean lines (D before, D after, R before, R after); JS updates them by look-up.
    for party, y0, y1 in [("D", -0.42, 0.42), ("R", 0.58, 1.42)]:
        color = PARTY_COLOR["Democrat" if party == "D" else "Republican"]
        shapes.append({"type": "line", "x0": g0[f"mean_{party}"], "x1": g0[f"mean_{party}"], "y0": y0, "y1": y1,
                       "line": {"color": color, "width": 2, "dash": "dash"}})
        shapes.append({"type": "line", "x0": after[f"mean_{party}"], "x1": after[f"mean_{party}"], "y0": y0, "y1": y1,
                       "line": {"color": color, "width": 2}})
    layout = {
        "height": 430, "margin": {"l": 100, "r": 20, "t": 30, "b": 90}, "hovermode": "closest",
        "paper_bgcolor": "#fcfcfb", "plot_bgcolor": "#fcfcfb", "font": {"family": "system-ui, sans-serif", "size": 13},
        "xaxis": {"title": {"text": "DW-NOMINATE dimension 1 (−1 liberal to +1 conservative)"},
                  "range": [-1.05, 1.05], "zeroline": True, "zerolinecolor": "#c3c2b7", "gridcolor": "#ecebe7"},
        "yaxis": {"tickvals": [0, 1], "ticktext": ["Democrats", "Republicans"], "range": [-0.6, 1.6],
                  "fixedrange": True, "showgrid": False},
        "legend": {"orientation": "h", "y": -0.28, "x": 0},
        "shapes": shapes,
        "annotations": [
            {"x": d_cut, "xanchor": "left", "y": 0.47, "xref": "x", "yref": "y",
             "text": "moderate (pre-registered: least liberal third)", "showarrow": False,
             "font": {"size": 11, "color": "#52514e"}},
            {"x": r_cut, "xanchor": "right", "y": 1.47, "xref": "x", "yref": "y",
             "text": "moderate (pre-registered: least conservative third)", "showarrow": False,
             "font": {"size": 11, "color": "#52514e"}}],
    }
    return {"traces": by_scenario, "layout": layout}


def histogram_spec(draws, summary):
    """Bars for the 10,000 permutation means, binned HERE (40 equal-width bins)."""
    values = draws["mean_dim1"].to_numpy(dtype=float)
    observed = summary.value("Q1", "main", "Republican", "lost_general", "mean_dim1")
    if len(values) == 0:
        return {"data": [], "layout": {}, "empty": True}
    counts, edges = np.histogram(values, bins=HIST_BINS)
    centers = (edges[:-1] + edges[1:]) / 2
    trace = {"type": "bar", "x": centers.tolist(), "y": counts.tolist(), "width": float(edges[1] - edges[0]) * 0.92,
             "marker": {"color": "#9a9994"}, "name": "random draws", "textposition": "none",
             "hovertext": [f"means {fmt(a, 'd3')} to {fmt(b, 'd3')}: {int(c)} draws"
                      for a, b, c in zip(edges[:-1], edges[1:], counts)],
             "hoverinfo": "text"}
    layout = {"height": 340, "margin": {"l": 70, "r": 20, "t": 30, "b": 60}, "bargap": 0,
              "paper_bgcolor": "#fcfcfb", "plot_bgcolor": "#fcfcfb", "font": {"family": "system-ui, sans-serif", "size": 13},
              "xaxis": {"title": {"text": "Mean DW-NOMINATE dimension 1 of a random group of k Republicans"}},
              "yaxis": {"title": {"text": "Number of random draws"}, "gridcolor": "#ecebe7"},
              "showlegend": False,
              "shapes": [{"type": "line", "x0": observed, "x1": observed, "yref": "paper", "y0": 0, "y1": 1,
                          "line": {"color": "#c98500", "width": 3}}],
              "annotations": [{"x": observed, "y": 1, "yref": "paper", "text": "actual losers",
                               "showarrow": False, "xanchor": "left", "font": {"color": "#8a5b00"}}]}
    return {"data": [trace], "layout": layout, "empty": False,
            "edges": edges.tolist(), "counts": counts.tolist()}


def q1_block(S, party, group, scenario="main"):
    """Text for one Q1 result (used in the main section and the exploratory details)."""
    k = S.value("Q1", scenario, party, group, "k")
    n_group = S.value("Q1", scenario, party, group, "mean_dim1", "n")
    parts = [f"{GROUP_LABEL[group]}: mean {S.span('Q1', scenario, party, group, 'mean_dim1', 'd3')} "
             f"(n = {S.span('Q1', scenario, party, group, 'mean_dim1', 'int', 'n')}); returning mean "
             f"{S.span('Q1', scenario, party, 'returning', 'mean_dim1', 'd3')}; share moderate "
             f"{S.span('Q1', scenario, party, group, 'share_moderate', 'pct')} vs. baseline "
             f"{S.span('Q1', scenario, party, 'baseline', 'share_moderate', 'pct')}."]
    if k is not None and not pd.isna(k):
        parts.append(f"Permutation p (mean) = {S.span('Q1', scenario, party, group, 'perm_p_mean', 'd4')}; "
                     f"moderate-count p = {S.span('Q1', scenario, party, group, 'perm_p_moderate_count', 'd4')} "
                     f"(exact: {S.span('Q1', scenario, party, group, 'exact_p_moderate_count', 'd4')}).")
    elif S.row("Q1", scenario, party, group, "test") is not None:
        parts.append("Too few members to test.")
    elif n_group == 0:
        parts.append("No members in this group.")
    return " ".join(parts)


def robustness_rows(S):
    rows = []
    for scenario in ["main", "no_low_votes", "no_same_party_general", "scenario_A", "scenario_B",
                     "state_sources_only", "certified_or_ap_only", "decision17_check"]:
        rows.append(
            f"<tr><th scope=\"row\">{esc(SCENARIO_LABEL[scenario])}</th>"
            f"<td>{S.span('Q1', scenario, 'Republican', 'lost_general', 'mean_dim1', 'int', 'n')}</td>"
            f"<td>{S.span('Q1', scenario, 'Republican', 'lost_general', 'mean_dim1', 'd3')}</td>"
            f"<td>{S.span('Q1', scenario, 'Republican', 'lost_general', 'perm_p_mean', 'd4')}</td>"
            f"<td>{S.span('Q2', scenario, 'both', '(v) returning only (all departures removed)', 'gap', 'd3')}</td>"
            f"<td>{S.span('Q2', scenario, 'both', '(v) returning only (all departures removed)', 'gap_change_from_G0', 'd3')}</td></tr>")
    return "\n".join(rows)


def departures_rows(dep, members, baseline):
    """One table row per row of the departures file, numbers tagged with their source."""
    mem = members.set_index("icpsr")
    base = baseline.set_index("icpsr")
    out = []
    for _, r in dep.iterrows():
        icpsr = int(r["icpsr"])
        if icpsr in mem.index:
            dim1 = num(mem.loc[icpsr, "nominate_dim1"], "d3", f"members:{icpsr}|nominate_dim1")
            sort_dim1 = float(mem.loc[icpsr, "nominate_dim1"])
            moderate = "yes" if str(mem.loc[icpsr, "moderate"]).lower() in ("true", "1") else "no"
        else:
            dim1 = num(base.loc[icpsr, "nominate_dim1"], "d3", f"baseline:{icpsr}|nominate_dim1")
            sort_dim1 = float(base.loc[icpsr, "nominate_dim1"])
            moderate = "not in B"
        district = num(float(r["district_code"]), "int", f"dep:{icpsr}|district_code")
        src = f'<a href="{esc(r["source_url"])}" target="_blank" rel="noopener">{esc(domain(r["source_url"]))}</a>' \
            if r["source_url"] else "—"
        src2 = (f'<a href="{esc(r["ai_second_source_url"])}" target="_blank" rel="noopener">'
                f'{esc(domain(r["ai_second_source_url"]))}</a> ({esc(r["ai_source_type"])})'
                if r["ai_second_source_url"] else "—")
        out.append(
            f'<tr data-party="{esc(r["party"])}" data-reason="{esc(r["reason"])}">'
            f'<td data-sort="{esc(r["bioname"])}">{esc(r["bioname"])}</td>'
            f'<td data-sort="{esc(r["state_abbrev"])}-{int(float(r["district_code"])):03d}">{esc(r["state_abbrev"])}-{district}</td>'
            f'<td data-sort="{esc(r["party"])}">{esc(r["party"])}</td>'
            f'<td data-sort="{sort_dim1:.6f}" data-type="number">{dim1}</td>'
            f'<td data-sort="{moderate}">{moderate}</td>'
            f'<td data-sort="{esc(r["reason"])}">{esc(r["reason"])}</td>'
            f'<td data-sort="{esc(r["status"])}">{esc(r["status"])}</td>'
            f'<td data-sort="{esc(r["ai_verified"]) or "-"}">{esc(r["ai_verified"]) or "—"}</td>'
            f"<td>{src}</td><td>{src2}</td></tr>")
    return "\n".join(out)


def clean(obj):
    """NaN/inf -> None (JSON null) so the embedded JSON is valid for JSON.parse."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def render(paths, fixture, out_path):
    """Fill the template from the analysis outputs at `paths` and write `out_path`."""
    d = load_inputs(paths)
    S = Summary(d["summary"])
    combos = combos_payload(d["combos"])
    meta = collect_meta(len(d["draws"]))
    plotly = PLOTLY_FILE.read_text(encoding="utf-8")
    assert "</script" not in plotly
    init = combos[combo_key("main", [1, 1, 1, 1])]["cells"]

    def panel_cell(col):
        c = init[col]
        return (f'<span class="num" id="cell-{col}" data-metric="{c["metric"]}" data-fmt="{c["fmt"]}">'
                f'{html.escape(c["text"])}</span>')

    payload = {
        "members": d["members"].astype(object).where(d["members"].notna(), None).to_dict("records"),
        "summary": d["summary"].astype(object).where(d["summary"].notna(), None).to_dict("records"),
        "combos": combos,
        "draws": d["draws"]["mean_dim1"].tolist(),
        "departures": d["departures"].to_dict("records"),
        "dotplot": dotplot_spec(d["members"], {k: {"mean_D": v["mean_D"], "mean_R": v["mean_R"]}
                                               for k, v in combos.items()}, S),
        "histogram": histogram_spec(d["draws"], S),
        "meta": meta,
    }
    data_json = json.dumps(clean(payload), allow_nan=False, default=str).replace("</", "<\\/")
    k = S.value("Q1", "main", "Republican", "lost_general", "k")
    fills = {
        "FIXTURE_BANNER": ('<div id="fixture-banner" class="fixture-banner" role="alert">'
                           "SYNTHETIC TEST DATA — NOT REAL RESULTS</div>") if fixture else "",
        "PAGE_TITLE": "PREVIEW (synthetic) — Hollowing the Middle?" if fixture else "Hollowing the Middle?",
        "HEADLINE": headline_html(),
        "ACCESS_DATES": meta_span(meta, "snapshot_access_dates"),
        "SCENARIO_OPTIONS": "".join(f'<option value="{s}">{esc(SCENARIO_LABEL[s])}</option>'
                                    for s in analyze.COMBO_SCENARIOS),
        "CELL_MEAN_D": panel_cell("mean_D"), "CELL_MEAN_R": panel_cell("mean_R"), "CELL_GAP": panel_cell("gap"),
        "CELL_DELTA": panel_cell("delta_gap"), "CELL_N_D": panel_cell("n_D"), "CELL_N_R": panel_cell("n_R"),
        "SENTENCE": init["sentence"],
        "Q1_K": S.span("Q1", "main", "Republican", "lost_general", "k", "int"),
        "Q1_MEAN": S.span("Q1", "main", "Republican", "lost_general", "mean_dim1", "d3"),
        "Q1_RETURNING": S.span("Q1", "main", "Republican", "returning", "mean_dim1", "d3"),
        "Q1_BASE": S.span("Q1", "main", "Republican", "baseline", "mean_dim1", "d3"),
        "Q1_SHARE": S.span("Q1", "main", "Republican", "lost_general", "share_moderate", "pct"),
        "Q1_SHARE_BASE": S.span("Q1", "main", "Republican", "baseline", "share_moderate", "pct"),
        "Q1_P": S.span("Q1", "main", "Republican", "lost_general", "perm_p_mean", "d4"),
        "Q1_P_COUNT": S.span("Q1", "main", "Republican", "lost_general", "perm_p_moderate_count", "d4"),
        "Q1_P_EXACT": S.span("Q1", "main", "Republican", "lost_general", "exact_p_moderate_count", "d4"),
        "N_DRAWS": meta_span(meta, "n_draws", "int"),
        "Q1_STATUS": "" if k is not None and not pd.isna(k) else
                     '<p class="note">No Republican lost_general members in this run: no test.</p>',
        "EXPLORATORY": "".join(f"<li><b>{party}s</b> — {q1_block(S, party, g)}</li>"
                               for party in ["Republican", "Democrat"] for g in GROUPS
                               if not (party == "Republican" and g == "lost_general")),
        "ROBUSTNESS_ROWS": robustness_rows(S),
        "DEPARTURE_ROWS": departures_rows(d["departures"], d["members"], d["baseline"]),
        "REASON_OPTIONS": "".join(f'<option value="{g}">{esc(g)}</option>'
                                  for g in sorted(d["departures"]["reason"].unique())),
        "VOTEVIEW_DATE": meta_span(meta, "voteview_downloaded"),
        "VOTEVIEW_SHA": meta_span(meta, "voteview_sha256"),
        "SNAPSHOT_COUNT": meta_span(meta, "snapshot_count", "int"),
        "AI_SOURCE_FILES": meta_span(meta, "ai_source_files", "int"),
        "N_STATE": S.span("validation", "main", "both", "departures", "n_rows_state_second_source", "int"),
        "N_NEWS_AP": S.span("validation", "main", "both", "departures", "n_rows_news_reporting_ap_second_source", "int"),
        "N_UNRESOLVED": S.span("validation", "main", "both", "departures", "n_unresolved", "int"),
        "N_DEP_ROWS": S.span("validation", "main", "both", "departures", "n_rows", "int"),
        "R_CUTOFF": S.span("cutoffs", "main", "Republican", "B", "cutoff", "d3"),
        "D_CUTOFF": S.span("cutoffs", "main", "Democrat", "B", "cutoff", "d3"),
        "DECISION_1": f'<q class="quote" data-quote-of="notes/decisions.md">{esc(decision_text(1))}</q>',
        "DECISION_6": f'<q class="quote" data-quote-of="notes/decisions.md">{esc(decision_text(6))}</q>',
        "DECISION_17": f'<q class="quote" data-quote-of="notes/decisions.md">{esc(decision_text(17))}</q>',
        "DECISION_20": f'<q class="quote" data-quote-of="notes/decisions.md">{esc(decision_text(20))}</q>',
        "DECISION_22": f'<q class="quote" data-quote-of="notes/decisions.md">{esc(decision_text(22))}</q>',
        "BUILD_TIME": meta_span(meta, "build_time"),
        "GIT_COMMIT": meta_span(meta, "git_commit"),
        "PLOTLY_VERSION": meta_span(meta, "plotly_version"),
        "REPO_LINK": repo_link_html(),
        "DATA_JSON": data_json,
        "PLOTLY_JS": plotly,
    }
    page = TEMPLATE.read_text(encoding="utf-8")
    for key, value in fills.items():
        page = page.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", page)
    if leftover:
        raise ValueError(f"unfilled placeholders: {sorted(set(leftover))}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


# ------------------------------------------------------------------ self-contained check
FORBIDDEN = ["<script src", '<link rel="stylesheet"', "<link ", "@import", "fetch(", "XMLHttpRequest",
             "url(http", ".woff", "fonts.googleapis"]
# The ONLY forbidden strings allowed inside the vendored Plotly block, and how many times each
# may appear there: d3's request helper (never called by this page; see vendor/VENDOR.md).
# Every other forbidden string must appear 0 times in the vendor block, and every forbidden
# string -- including XMLHttpRequest -- must appear 0 times outside it.
VENDOR_EXCEPTIONS = {"XMLHttpRequest": 1}


def self_contained_problems(page):
    """Every reason `page` is not self-contained. The ONLY exemption is VENDOR_EXCEPTIONS, and it
    applies only inside the single <script id="plotly-bundle"> block, which must also be
    byte-identical to the SHA-checked vendor file."""
    problems = []
    blocks = re.findall(r'<script id="plotly-bundle">.*?</script>', page, re.S)
    if len(blocks) != 1:
        return [f"expected exactly one plotly-bundle block, found {len(blocks)}"]
    block = re.search(r'<script id="plotly-bundle">(.*?)</script>', page, re.S)
    vendored = PLOTLY_FILE.read_bytes()
    if block.group(1).encode("utf-8") != vendored:
        problems.append("plotly-bundle block is not byte-identical to the vendored file")
    recorded = re.search(r"SHA-256:\*\* ([0-9a-f]{64})", (ROOT / "vendor" / "VENDOR.md").read_text()).group(1)
    if hashlib.sha256(vendored).hexdigest() != recorded:
        problems.append("vendored file SHA-256 does not match vendor/VENDOR.md")
    for needle in FORBIDDEN:                                   # inside the vendor block
        count, allowed = block.group(1).count(needle), VENDOR_EXCEPTIONS.get(needle, 0)
        if count != allowed:
            problems.append(f"inside vendor block: {needle!r} appears {count} times (allowed {allowed})")
    rest = page.replace(block.group(0), "")
    for needle in FORBIDDEN:                                   # everywhere else: none at all
        if needle in rest:
            problems.append(f"outside vendor block: {needle!r} found")
    if re.findall(r"<script[^>]*\bsrc=", page):
        problems.append("a <script src=...> tag exists")
    return problems


# ------------------------------------------------------------------ modes
def run_fixture_analysis(workdir):
    """Run analyze.py's pipeline on the SYNTHETIC fixtures into workdir; return input paths."""
    workdir = Path(workdir)
    fix = ROOT / "tests" / "fixtures"
    base = analyze.read_baseline(fix / "members.csv")
    dep = analyze.assign_roles(analyze.read_departures(fix / "departures.csv"))
    B, _, _, _ = analyze.build_B(base, dep)
    cuts = analyze.compute_cutoffs(B)
    pd.DataFrame({"party": list(cuts), "cutoff": list(cuts.values())}).to_csv(workdir / "cutoffs.csv", index=False)
    code = analyze.main(fix / "departures.csv", fix / "members.csv", workdir / "cutoffs.csv",
                        workdir, workdir / "analysis_phase3.txt", run_tests=False)
    if code != 0:
        raise RuntimeError("analysis of the fixtures failed; see the log above")
    return {"summary": workdir / "summary.csv", "combos": workdir / "gap_combinations.csv",
            "members": workdir / "analysis_members.csv", "draws": workdir / "permutation_draws_R.csv",
            "log": workdir / "analysis_phase3.txt", "departures": fix / "departures.csv",
            "baseline": fix / "members.csv"}


def real_mode_problems(paths):
    """Why real mode must refuse (empty list = OK to build)."""
    problems = [f"missing: {p}" for name, p in paths.items() if not Path(p).exists()]
    log = Path(paths["log"])
    if log.exists():
        text = log.read_text()
        if analyze.VALIDATION_PASSED not in text.splitlines():
            problems.append(f"{log} does not contain the line '{analyze.VALIDATION_PASSED}'")
        if "STOPPED:" in text:
            problems.append(f"{log} says the analysis STOPPED")
    return problems


def main(argv=None, real_paths=None, real_out=REAL_OUT):
    parser = argparse.ArgumentParser(description="Build the project web page.")
    parser.add_argument("--fixtures", action="store_true", help="SYNTHETIC preview into preview/")
    args = parser.parse_args(argv)
    if args.fixtures:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                paths = run_fixture_analysis(tmp)
            out = render(paths, fixture=True, out_path=FIXTURE_OUT)
        print(f"Wrote {out} ({out.stat().st_size:,} bytes) -- SYNTHETIC TEST DATA, not for publishing")
        return 0
    paths = real_paths or REAL_INPUTS
    problems = real_mode_problems(paths)
    if problems:
        print("REFUSING to build docs/index.html: the verified analysis outputs are not ready.")
        for p in problems:
            print(f"  - {p}")
        print("Run build.py and analyze.py after saving data/interim/departures_verified.csv.")
        return 1
    out = render(paths, fixture=False, out_path=Path(real_out))
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
