"""
apply_ai_crosscheck.py -- write the AI's cross-check (decision 20) into the verification worksheet.

Run with:  .venv/bin/python -I scripts/apply_ai_crosscheck.py

Inputs (all produced on 2026-11-23 by Claude Code subagents from files saved in data/sources/):
  data/interim/ai_crosscheck_findings.json   one finding per check_order 1-7 row (+ adversarial verdicts)
  data/interim/decision23_extraction.json    top-two totals / reporting / certification per state-sourced
                                              lost_general row
Outputs:
  data/interim/verification_worksheet.csv     ai_* columns filled; author columns stay blank
  data/interim/decision23_margins.csv          the decision-23 test for every lost_general row
  logs/ai_verification.txt                     one line per checked row + totals

Corrections 1-5 were approved on 2026-11-23; decision 23 is applied here in code:
an unofficial state result counts as called only if the saved file shows the count complete, the
top-two margin is >= 0.5 percentage points of their combined vote, and no saved source shows a
recount request. Vote totals and names are re-checked against the saved file before use.
"""

import html
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKSHEET = ROOT / "data" / "interim" / "verification_worksheet.csv"
FINDINGS = ROOT / "data" / "interim" / "ai_crosscheck_findings.json"
EXTRACTION = ROOT / "data" / "interim" / "decision23_extraction.json"
MARGINS = ROOT / "data" / "interim" / "decision23_margins.csv"
LOG = ROOT / "logs" / "ai_verification.txt"
THRESHOLD_PP = 0.5          # decision 23
UNRESOLVED_NOTE = "no second source obtained"   # decision 21
BLAIR_ICPSR = "22571"       # in the Voteview baseline

# Rows whose cited state results file sits on an official state server that is NOT a .gov/.us
# host, which analyze.py's validation rejects as a 'state' source. Under "fix the worksheet
# from saved sources only", the second source becomes a SAVED .gov page that supports the row;
# the non-.gov file stays listed as supporting evidence. Each support was checked in the saved file.
HOST_FIXES = {
    "22350": ("https://floridaelectionwatch.gov/FederalOffices/USRepresentative",
              "data/sources/2026-11-23_fl-electionwatch-us-representative-general.html",
              "FL .gov general page: District 7 Republican nominee is Ryan Elijah; 'Mills' appears 0 times. "
              "Primary results file is on results.elections.myflorida.com (official FL DOS results server, non-.gov "
              "host): data/sources/2026-11-23_fl-dos-2026-rep-primary-federal-summary.html"),
    "22357": ("https://www.elections.tn.gov/categories/congressional/offices",
              "data/sources/2026-11-23_tn-nov2026-congressional-results.html",
              "TN .gov dashboard: District 5 Republican nominee is Charlie Hatcher; 'Ogles' appears 0 times. "
              "Primary results PDF is on sos-prod.tnsosgovfiles.com (TN SOS file store, non-.gov host), linked from "
              "the saved .gov index data/sources/2026-11-23_tn-sos-election-results-index.html: "
              "data/sources/2026-11-23_tn-aug2026-gop-primary-by-county.pdf"),
    "21959": ("https://www.elections.tn.gov/categories/congressional/offices",
              "data/sources/2026-11-23_tn-nov2026-congressional-results.html",
              "TN .gov dashboard: District 6 Republican nominee is Johnny Garrett; 'John Rose' appears 0 times. "
              "His governor-primary candidacy is in the primary PDF on sos-prod.tnsosgovfiles.com (TN SOS file "
              "store, non-.gov host), linked from the saved .gov index: "
              "data/sources/2026-11-23_tn-aug2026-gop-primary-by-county.pdf"),
}


def file_text(spec):
    """Concatenated text of the saved (non-PDF) files named in spec ('a ; b')."""
    out = ""
    for p in [x.strip() for x in re.split(r"[;,]", spec) if x.strip()]:
        if not p.endswith(".pdf"):
            out += html.unescape((ROOT / p).read_bytes().decode("utf-8", "replace"))
    return out


def surname(name):
    words = re.sub(r"\(.*?\)", " ", name).replace('"', " ").split()
    words = [w for w in words if w.lower().strip(".,") not in ("jr", "sr", "ii", "iii", "iv")]
    return words[-1].strip(".,") if words else ""


def decision23(x):
    """Decision 23 for one extracted row -> dict with the margin and the status."""
    text = file_text(x["file"])
    a, b = int(x["cand1_votes"]), int(x["cand2_votes"])
    nums_ok = a > 0 and b > 0 and all(str(n) in text or f"{n:,}" in text for n in (a, b))
    names_ok = all(surname(n) and surname(n).lower() in text.lower() for n in (x["cand1_name"], x["cand2_name"]))
    margin = abs(a - b) / (a + b) * 100 if a + b else None
    recount = bool(re.search(r"recount", x["recount_or_outstanding_mentions"], re.I)
                   and re.search(r"request", x["recount_or_outstanding_mentions"], re.I))
    certified = x["certification"] == "certified"
    if not (nums_ok and names_ok):
        status, why = "pending", "both candidates' totals could not be confirmed in the saved file"
    elif certified:
        status, why = "called", "certified state result"
    elif recount:
        status, why = "pending", "a saved source shows a recount request"
    elif x["count_complete"] != "yes":
        status, why = "pending", ("saved file does not show the reporting status" if x["count_complete"] == "not_shown"
                                  else "saved file shows the count is not complete")
    elif margin < THRESHOLD_PP:
        status, why = "pending", f"margin {margin:.3f} pp is below {THRESHOLD_PP} pp"
    else:
        status, why = "called", "unofficial, count complete, margin >= 0.5 pp, no recount request"
    return {"icpsr": x["icpsr"], "file": x["file"], "contest": x["contest_label"],
            "top1": x["cand1_name"], "top1_votes": a, "top2": x["cand2_name"], "top2_votes": b,
            "margin_pp": round(margin, 4) if margin is not None else None, "count_complete": x["count_complete"],
            "certification": x["certification"], "recount_request": recount, "totals_in_file": nums_ok,
            "names_in_file": names_ok, "d23_status": status, "d23_reason": why,
            "reporting_quote": x["reporting_quote"][:300]}


def main():
    ws = pd.read_csv(WORKSHEET, dtype=str, keep_default_na=False)
    if (ws["ai_verified"] != "").any():
        raise SystemExit("REFUSING: the worksheet already has AI values; rebuild it with make_worksheet.py --force first.")
    findings = json.loads(FINDINGS.read_text())
    by_icpsr = {r["icpsr"]: r for r in findings["crosscheck_rows"]}
    d23 = {x["icpsr"]: decision23(x) for x in json.loads(EXTRACTION.read_text())["rows"]}
    log, counts = [], {"confirmed": 0, "corrected": 0, "N": 0, "unresolved": 0}

    for i, row in ws.iterrows():
        order = int(row["check_order"])
        if order > 7:
            continue
        key = BLAIR_ICPSR if order == 1 else row["icpsr"]
        f = by_icpsr[key]
        draft = f"{row['reason'] or '(no reason)'}/{row['status'] or '-'}"
        url = f["source_url"].split(" ; ")[0].strip()
        ws.loc[i, ["ai_source_type", "ai_second_source_url", "ai_second_source_file"]] = [
            "" if f["source_type"] == "none" else f["source_type"], url, f["source_file"]]
        notes = row["notes"]
        if key in HOST_FIXES:
            gov_url, gov_file, why = HOST_FIXES[key]
            ws.loc[i, ["ai_second_source_url", "ai_second_source_file"]] = [gov_url, f"{gov_file} ; {f['source_file']}"]
            notes += f"; second source set to a saved .gov page (state file on a non-.gov host): {why}"
        if " ; " in f["source_url"]:
            notes += f"; AI also used: {f['source_url'].split(' ; ', 1)[1]}"
        action = ""
        if f["outcome"] == "unresolved":
            ws.loc[i, "ai_verified"] = ""
            ws.loc[i, ["ai_source_type", "ai_second_source_url", "ai_second_source_file"]] = ["", "", ""]
            notes += f"; {UNRESOLVED_NOTE} (decision 21): {f['notes'][:300]}"
            action = "UNRESOLVED -> removed from B (decision 21)"
            counts["unresolved"] += 1
        elif f["outcome"] == "did_not_leave":
            ws.loc[i, "ai_verified"] = "N"
            ws.loc[i, "ai_correction"] = f"did not leave the House (decision 19): {f['what_source_says'][:240]}"
            action = "N -> member returning (decision 19)"
            counts["N"] += 1
        elif f["outcome"] == "corrected" and order == 1:            # Blair
            ws.loc[i, ["icpsr", "party", "reason", "status"]] = [BLAIR_ICPSR, "Democrat", "lost_primary", "called"]
            ws.loc[i, "ai_verified"] = "Y"
            ws.loc[i, "ai_correction"] = ("added as lost_primary (icpsr 22571): lost the May 19, 2026 GA-13 Democratic "
                                          "primary per Georgia official results; held the seat on Nov 3 after a special election")
            notes = f"AI cross-check (decision 20): {f['what_source_says'][:300]}"
            action = "CORRECTED -> lost_primary/called (icpsr 22571)"
            counts["corrected"] += 1
        elif f["outcome"] == "corrected":                           # Foxx: handled by decision 23 below
            ws.loc[i, "ai_verified"] = "Y"
            action = "CORRECTED (see decision 23 below)"
        else:
            ws.loc[i, "ai_verified"] = "Y"
            action = "CONFIRMED"
        # decision 23 call basis for every lost_general row
        if row["reason"] == "lost_general" and ws.loc[i, "ai_verified"] == "Y":
            if ws.loc[i, "ai_source_type"] in ("ap", "news_reporting_ap"):
                ws.loc[i, "ai_call_basis"] = "ap_call"
            elif ws.loc[i, "ai_source_type"] == "state":
                t = d23[row["icpsr"]]
                tag = (f"decision 23: unofficial state result; margin {t['margin_pp']:.3f} pp "
                       f"({t['top1']} {t['top1_votes']:,} vs {t['top2']} {t['top2_votes']:,}); {t['d23_reason']}")
                notes += f"; {tag}"
                if t["d23_status"] == "called":
                    ws.loc[i, "ai_call_basis"] = "certified_state" if t["certification"] == "certified" else "unofficial_state"
                else:
                    ws.loc[i, ["reason", "status"]] = ["pending", "uncalled"]
                    ws.loc[i, "ai_correction"] = f"lost_general/called -> pending/uncalled ({tag})"
                    action = "CORRECTED -> pending/uncalled (decision 23)"
                    counts["corrected"] += 1
        if action == "CONFIRMED":
            counts["confirmed"] += 1
        ws.loc[i, "notes"] = notes
        log.append(f"{ws.loc[i, 'bioname']} ({ws.loc[i, 'state_abbrev']}-{ws.loc[i, 'district_code']}, icpsr "
                   f"{ws.loc[i, 'icpsr'] or 'blank'}) | draft: {draft} | source ({f['source_type']}): "
                   f"{f['what_source_says'][:220] or f['notes'][:220]} | file: {f['source_file'] or 'none'} | action: {action}")

    ws.to_csv(WORKSHEET, index=False)
    lg = ws[ws["icpsr"].isin(list(d23)) | (ws["reason"] == "lost_general")]
    rows = []
    for _, r in ws.iterrows():
        f = by_icpsr.get(r["icpsr"])
        if not f or (r["icpsr"] not in d23 and r["reason"] != "lost_general"):
            continue
        t = d23.get(r["icpsr"], {})
        rows.append({"icpsr": r["icpsr"], "bioname": r["bioname"], "seat_119th": f"{r['state_abbrev']}-{r['district_code']}",
                     "ai_source_type": r["ai_source_type"] or "none", "ai_call_basis": r["ai_call_basis"],
                     "margin_pp": t.get("margin_pp", ""), "top1": t.get("top1", ""), "top1_votes": t.get("top1_votes", ""),
                     "top2": t.get("top2", ""), "top2_votes": t.get("top2_votes", ""),
                     "count_complete": t.get("count_complete", ""), "certification": t.get("certification", ""),
                     "recount_request": t.get("recount_request", ""), "final_reason": r["reason"], "final_status": r["status"],
                     "rule": t.get("d23_reason", "AP-cited call" if r["ai_call_basis"] == "ap_call" else
                                   ("unresolved (decision 21)" if r["ai_verified"] == "" else ""))})
    pd.DataFrame(rows).to_csv(MARGINS, index=False)
    header = ["Verification log (decision 20), 2026-11-23.",
              "One line per check_order 1-7 row: member | what the draft said | what the saved source says | file | action.",
              "Decision 23 applied in scripts/apply_ai_crosscheck.py.", ""]
    totals = ["", f"TOTALS: confirmed {counts['confirmed']}, corrected {counts['corrected']}, N (did not leave) {counts['N']}, "
                  f"unresolved {counts['unresolved']} (of {len(log)} rows checked)"]
    LOG.write_text("\n".join(header + log + totals) + "\n")
    print("\n".join(totals).strip())
    print(f"Wrote {WORKSHEET.relative_to(ROOT)}, {MARGINS.relative_to(ROOT)} ({len(rows)} rows), {LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
