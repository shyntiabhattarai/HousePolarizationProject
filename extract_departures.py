"""
extract_departures.py -- Phase 2, Part 2: build the DRAFT departures file from
the saved Ballotpedia snapshots in data/sources/ (never from the live web).

Run with:  .venv/bin/python extract_departures.py      (then run build.py)

Writes:
  data/interim/departures_draft.csv     one row per departing (or uncalled) member
  data/interim/member_status_draft.csv  every baseline member + their 2026 status

Rules followed here:
  - Every row names the snapshot file it came from (source_file).
  - icpsr comes from data/processed/house119_baseline.csv. The match key is
    state + district + party; the name is only used to CONFIRM it. In states
    whose maps changed for 2026 the district number is not the same seat, so a
    member is matched within state + party and confirmed by name, and the row
    is marked confidence = medium with a note. Failed or ambiguous matches are
    left blank and flagged -- never forced.
  - verified_by_author, second_source_url and correction are left EMPTY.
  - Nothing here computes any result (no means, gaps or tests).
"""

import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

SOURCES = Path("data/sources")
BASELINE_FILE = Path("data/processed/house119_baseline.csv")
DRAFT_FILE = Path("data/interim/departures_draft.csv")
STATUS_FILE = Path("data/interim/member_status_draft.csv")
ACCESSED = "2026-11-23"

NOT_RUNNING_FILE = "2026-11-23_ballotpedia-congress-not-running.html"
NOT_RUNNING_URL = ("https://ballotpedia.org/List_of_U.S._Congress_incumbents_"
                   "who_are_not_running_for_re-election_in_2026")
RESULTS_FILE = "2026-11-23_ballotpedia-house-results-2026.html"
STATE_URL = "https://ballotpedia.org/United_States_House_of_Representatives_elections_in_{},_2026"

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY",
}
AT_LARGE = ["Alaska", "Delaware", "North Dakota", "South Dakota", "Vermont", "Wyoming"]

# Not-running page: table caption -> reason (decision 7).
CAPTIONS = {
    "Retiring from public office, 2026": "retired",
    "Running for the U.S. Senate, 2026": "ran_other_office",
    "Running for governor, 2026": "ran_other_office",
    "Running for attorney general, 2026": "ran_other_office",
    "Running for state legislative districts, 2026": "ran_other_office",
    "Left office early, 2025-2026": "resigned_died",
    "Lost re-election, 2026": "lost",          # primary vs general read from the row
}
PARTY_CODE = {"Democrat": 100, "Democratic": 100, "Republican": 200}

# Rows added by hand from a snapshot. Empty: the Everton Blair (GA-13) row was removed on
# 2026-11-23 (he is handled in the verification worksheet instead).
MANUAL_ROWS = []

DRAFT_COLUMNS = ["icpsr", "bioname", "state_abbrev", "district_code", "party", "reason",
                 "status", "source_file", "source_url", "source_type", "accessed",
                 "confidence", "notes", "verified_by_author", "second_source_url", "correction"]


# ------------------------------------------------------------------ helpers
class _Text(HTMLParser):
    """Turn a saved HTML page into lines of visible text (scripts/styles skipped)."""
    BREAKS = {"tr", "p", "br", "li", "h1", "h2", "h3", "h4", "h5", "div", "table"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BREAKS:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_lines(filename):
    parser = _Text()
    parser.feed((SOURCES / filename).read_text(encoding="utf-8"))
    lines = "".join(parser.parts).split("\n")
    return [re.sub(r"\s+", " ", x).strip() for x in lines if x.strip()]


def plain(text):
    """Lowercase, strip accents and punctuation -- used ONLY to confirm a match."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", " ", text.lower()).split()


def surname_confirms(bioname, source_name):
    """True if every word of the Voteview surname (text before the comma) appears,
    in order, at the end of the source name (ignoring Jr./Sr./II/III)."""
    surname = plain(bioname.split(",")[0])
    words = [w for w in plain(source_name) if w not in ("jr", "sr", "ii", "iii", "iv")]
    return len(surname) > 0 and words[-len(surname):] == surname


def first_name_confirms(bioname, source_name):
    """Tie-breaker when two members share a surname (e.g. Raúl and Adelita Grijalva):
    the first Voteview given name must appear in the source name."""
    given = plain(bioname.split(",")[1]) if "," in bioname else []
    return len(given) > 0 and given[0] in plain(source_name)


def narrow(pool, name):
    """Members in pool confirmed by surname; if several, also by first name."""
    hits = pool[pool["bioname"].map(lambda b: surname_confirms(b, name))]
    if len(hits) > 1:
        hits = hits[hits["bioname"].map(lambda b: first_name_confirms(b, name))]
    return hits


def party_of(line):
    """Party label in a candidate line, e.g. 'Mike McGuire  (Democratic Party) ✔' -> 'Democratic'."""
    tail = line.split("(Incumbent)")[-1]
    m = re.search(r"\(([^()]*?)(?: Party)?[,)]", tail)
    return m.group(1) if m else ""


def same_party(a, b):
    """Compare the first word of two party labels ('Republican Party, Conservative' ~ 'Republican')."""
    return bool(a) and bool(b) and a.split()[0].rstrip(",") == b.split()[0].rstrip(",")


def parse_seat(text):
    """"North Carolina's 11th Congressional District" -> ("NC", 11)."""
    m = re.match(r"(.+?)['’]s? (\d+)(?:st|nd|rd|th)", text)
    if m and m.group(1) in STATES:
        return STATES[m.group(1)], int(m.group(2))
    m = re.match(r"(.+?)['’]s? At-[Ll]arge", text)
    if m and m.group(1) in STATES:
        return STATES[m.group(1)], 1
    return None, None


# ------------------------------------------------------------------ sources
def read_not_running():
    """Rows from the four House tables on the not-running page."""
    rows, caption = [], None
    for line in page_lines(NOT_RUNNING_FILE):
        if line in CAPTIONS:
            caption = line
            continue
        cells = [c.strip() for c in line.strip("| ").split(" | ")]
        if caption is None or len(cells) < 4 or "Congressional District" not in cells[2]:
            continue                                       # Senate rows have no district
        state, district = parse_seat(cells[2])
        reason = CAPTIONS[caption]
        detail = re.sub(r"\[\d+\]", "", cells[3])
        if reason == "lost":
            reason = "lost_primary" if detail.lower().startswith("primary") else "lost_general"
        rows.append({"name": cells[0], "party": cells[1], "state_abbrev": state,
                     "district": district, "reason": reason,
                     "detail": f"{caption}: {detail}" + (f" ({cells[4]})" if len(cells) > 4 else "")})
    return pd.DataFrame(rows)


def read_state_page(state_name):
    """Every '(Incumbent)' line on a multi-district state page, with its section."""
    filename = f"2026-11-23_ballotpedia-house-{state_name.lower().replace(' ', '-')}.html"
    out, district, section, dnmb, started = [], None, None, False, False
    has_winner, canceled = {}, set()
    for line in page_lines(filename):
        if line == "Candidates":
            started = True
            continue
        if not started:
            continue
        m = re.fullmatch(r"District (\d+)", line)
        if m:
            district, section, dnmb = int(m.group(1)), None, False
            continue
        if district is None:
            continue
        # Some districts (e.g. Alabama) show a results table instead of a candidate list.
        # Its first sentence says who won: "Incumbent X (R) defeated ..." or
        # "Y (D) defeated incumbent X (R) ...".
        if line.startswith("General election for U.S. House"):
            section, dnmb = "general_table", False
            continue
        if section == "general_table":
            won = re.match(r"Incumbent (.+?) \(([DR])\) defeated", line)
            lost = re.match(r"(.+?) \(([DR])\) defeated incumbent (.+?) \(([DR])\)", line)
            if won or lost:
                has_winner[district] = {"D": "Democratic", "R": "Republican"}[
                    won.group(2) if won else lost.group(2)]
                name, letter = (won.group(1), won.group(2)) if won else (lost.group(3), lost.group(4))
                out.append({"state_abbrev": STATES[state_name], "district_2026": district,
                            "name": name, "party_label": {"D": "Democratic", "R": "Republican"}[letter],
                            "section": "general", "did_not_make_ballot": False,
                            "check_mark": bool(won), "source_file": filename,
                            "source_url": STATE_URL.format(state_name.replace(" ", "_"))})
            section = None
            continue
        if line.startswith("General election candidates"):
            section, dnmb = "general", False
        elif line.endswith("candidates") and ("rimary" in line or "convention" in line):
            section, dnmb = line.strip().lower(), False
        elif line.startswith("Did not make the ballot"):
            dnmb = True
        elif line.startswith("The general election was canceled"):
            canceled.add(district)
        if section == "general" and not dnmb and line.endswith("✔"):
            has_winner[district] = party_of(line)
        if "(Incumbent)" in line:
            name = line.split("(Incumbent)")[0].strip()
            out.append({"state_abbrev": STATES[state_name], "district_2026": district,
                        "name": name, "party_label": party_of(line),
                        "section": section, "did_not_make_ballot": dnmb,
                        "check_mark": line.endswith("✔"), "source_file": filename,
                        "source_url": STATE_URL.format(state_name.replace(" ", "_"))})
    df = pd.DataFrame(out)
    if len(df):
        df["general_has_winner"] = df["district_2026"].map(lambda d: d in has_winner)
        df["winner_party"] = df["district_2026"].map(lambda d: has_winner.get(d, ""))
        df["general_canceled"] = df["district_2026"].isin(canceled)
    return df


def read_at_large(state_name):
    """At-large pages use a results table; return the general-election winner's name."""
    filename = f"2026-11-23_ballotpedia-house-{state_name.lower().replace(' ', '-')}.html"
    html = (SOURCES / filename).read_text(encoding="utf-8")
    start = html.find("General election for U.S. House")
    end = html.find('class="votebox"', start)          # the next results box (a primary)
    box = html[start:end if end > 0 else len(html)]
    # 1st choice: the results sentence ("Incumbent X (D) defeated ..." or, for ranked-choice
    # Alaska, "... was won by: incumbent X (R) in round 3"); 2nd: the row marked "winner".
    sentence = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", box))
    winner = (re.search(r"Incumbent (.+?) \(\w+\) defeated", sentence)
              or re.search(r"won by: incumbent (.+?) \(", sentence)
              or re.search(r'results_row winner.*?title="([^"]+)"', box, re.S))
    return (winner.group(1).strip() if winner else None), filename


def read_results_timeline():
    """Every race call on the results page's timeline (250 of 431 calls are on the saved
    page). 'defeated' is the incumbent named as defeated, if any; 'call' is who made the
    call ('Official Ballotpedia call.', 'Projected by CNN.', ...)."""
    found, day = [], ""
    for line in page_lines(RESULTS_FILE):
        if re.fullmatch(r"[A-Z][a-z]+ \d{1,2}, 2026", line):
            day = line
            continue
        m = re.match(r"(\d{1,2}:\d\d [AP]M): (.+?) \((\w)\) won the (.+?) U\.S\. House election "
                     r"\(District (\d+)\)(.*)", line)
        if m:
            lost = re.search(r"Incumbent (.+?) \((\w)\) was defeated\.", m.group(6))
            call = re.search(r"(Official Ballotpedia call\.|Projected by [^.]+\.)", m.group(6))
            found.append({"state_abbrev": STATES.get(m.group(4)), "district_2026": int(m.group(5)),
                          "winner": f"{m.group(2)} ({m.group(3)})",
                          "defeated": lost.group(1) if lost else "",
                          "call": call.group(1) if call else "",
                          "when": day, "text": line})
    return pd.DataFrame(found)


# ------------------------------------------------------------------ matching
def match(base, state, district, party_code, name):
    """Return (icpsr, how, note). how: 'seat' | 'state_party_name' | '' (no match)."""
    pool = base[(base["state_abbrev"] == state)]
    if party_code is not None:
        pool = pool[pool["party_code"] == party_code]
    seat = pool[pool["district_code"] == district]
    confirmed = narrow(seat, name)
    if len(confirmed) == 1:
        return int(confirmed["icpsr"].iloc[0]), "seat", ""
    by_name = narrow(pool, name)
    if len(by_name) == 1:
        row = by_name.iloc[0]
        return int(row["icpsr"]), "state_party_name", (
            f"source district {district} != 119th district {row['district_code']:g}; "
            f"matched within {state} + party, confirmed by name")
    if len(by_name) > 1:
        return None, "", f"AMBIGUOUS: {len(by_name)} baseline members in {state} match '{name}'"
    return None, "", f"NO MATCH in baseline for '{name}' ({state}-{district})"


def main():
    base = pd.read_csv(BASELINE_FILE)
    # Match against every scored 119th member except dropped duplicates and delegates. NOT
    # filtered on in_baseline: build.py removes the members who left early (decision 1) using
    # this file's resigned_died rows, so they must still be matchable here.
    base = base[~base["flags"].fillna("").str.contains("duplicate_dropped|delegate")]

    # 1. Not-running page: retired, ran_other_office, resigned_died, lost_primary
    listed = read_not_running()
    rows = []
    for _, r in listed.iterrows():
        code = PARTY_CODE.get(r["party"])
        icpsr, how, note = match(base, r["state_abbrev"], r["district"], code, r["name"])
        rows.append({"icpsr": icpsr, "source_name": r["name"], "state_abbrev": r["state_abbrev"],
                     "district_code": r["district"], "party": r["party"], "reason": r["reason"],
                     "status": "called", "source_file": NOT_RUNNING_FILE,
                     "source_url": NOT_RUNNING_URL, "how": how,
                     "notes": "; ".join(x for x in [r["detail"], note] if x)})

    # 2. State pages: every incumbent's 2026 general-election outcome
    pages = [read_state_page(s) for s in STATES if s not in AT_LARGE]
    inc = pd.concat([p for p in pages if len(p)], ignore_index=True)
    general = inc[(inc["section"] == "general") & ~inc["did_not_make_ballot"]].copy()
    timeline = read_results_timeline()

    outcomes = []          # one entry per incumbent found on a general ballot
    for _, g in general.iterrows():
        code = 100 if g["party_label"] == "Democratic" else 200 if g["party_label"] == "Republican" else None
        icpsr, how, note = match(base, g["state_abbrev"], g["district_2026"], code, g["name"])
        if icpsr is None and code is not None:      # party label changed (e.g. now independent)
            icpsr, how, note2 = match(base, g["state_abbrev"], g["district_2026"], None, g["name"])
            note = note2 if icpsr else note
        if g["check_mark"]:
            result = "won_general"
        elif g["general_has_winner"]:
            result = "lost_general"
        else:
            result = "uncalled"
        tl = timeline[(timeline["state_abbrev"] == g["state_abbrev"]) &
                      (timeline["district_2026"] == g["district_2026"])].head(1)
        outcomes.append({"icpsr": icpsr, "source_name": g["name"], "state_abbrev": g["state_abbrev"],
                         "district_2026": g["district_2026"], "party_label": g["party_label"],
                         "result": result, "how": how, "match_note": note,
                         "winner_party": g["winner_party"],
                         "timeline_call": tl["call"].iloc[0] if len(tl) and tl["defeated"].iloc[0] else "",
                         "timeline_text": f"{tl['when'].iloc[0]}: {tl['text'].iloc[0]}" if len(tl) else "",
                         "source_file": g["source_file"], "source_url": g["source_url"]})

    # Louisiana: general election canceled = the incumbent won the Nov 3 primary outright.
    la = inc[(inc["state_abbrev"] == "LA") & inc["general_canceled"] &
             inc["section"].str.startswith("primary", na=False) & inc["check_mark"]]
    for _, g in la.iterrows():
        code = 100 if g["party_label"] == "Democratic" else 200 if g["party_label"] == "Republican" else None
        icpsr, how, note = match(base, "LA", g["district_2026"], code, g["name"])
        outcomes.append({"icpsr": icpsr, "source_name": g["name"], "state_abbrev": "LA",
                         "district_2026": g["district_2026"], "party_label": g["party_label"],
                         "result": "won_outright_primary", "how": how, "match_note": note,
                         "timeline_call": "", "source_file": g["source_file"],
                         "source_url": g["source_url"]})

    for state_name in AT_LARGE:
        winner, filename = read_at_large(state_name)
        member = base[base["state_abbrev"] == STATES[state_name]].iloc[0]
        won = winner is not None and surname_confirms(member["bioname"], winner)
        outcomes.append({"icpsr": int(member["icpsr"]), "source_name": winner or "",
                         "state_abbrev": STATES[state_name], "district_2026": 1,
                         "party_label": member["party"], "result": "won_general" if won else "not_winner",
                         "how": "seat", "match_note": f"at-large; winner row on page: {winner}",
                         "timeline_call": "", "source_file": filename,
                         "source_url": STATE_URL.format(state_name.replace(" ", "_"))})
    outcomes = pd.DataFrame(outcomes)

    # 3. Departure rows from general-election outcomes (lost or uncalled)
    for _, o in outcomes[outcomes["result"].isin(["lost_general", "uncalled"])].iterrows():
        notes = [f"2026 ballot: {o['state_abbrev']}-{o['district_2026']} ({o['party_label']})"]
        if o["result"] == "lost_general":
            notes.append("state page: another candidate in this general has the winner check mark")
            if same_party(o["winner_party"], o["party_label"]):
                notes.append(f"same_party_general (winner's party: {o['winner_party']})")
            notes.append(f"results-page timeline: {o['timeline_call']}" if o["timeline_call"]
                         else "results-page timeline has no entry for this call")
        else:
            notes.append("UNCALLED (decision 12): no general-election candidate has a winner check "
                         "mark on the state page")
            if o["timeline_text"]:
                notes.append("who leads per source: results-page timeline says '" + o["timeline_text"]
                             + "' -- NOT counted as called (decision 11: needs a saved AP or official "
                             "state source; this is Ballotpedia reporting a projection)")
            else:
                notes.append("who leads per source: not shown (state page lists candidates without "
                             "vote counts; no results-page timeline entry)")
        if o["match_note"]:
            notes.append(o["match_note"])
        rows.append({"icpsr": o["icpsr"], "source_name": o["source_name"],
                     "state_abbrev": o["state_abbrev"], "district_code": o["district_2026"],
                     "party": o["party_label"],
                     "reason": "lost_general" if o["result"] == "lost_general" else "pending",
                     "status": "called" if o["result"] == "lost_general" else "uncalled",
                     "source_file": o["source_file"], "source_url": o["source_url"],
                     "how": o["how"], "notes": "; ".join(notes)})

    # Rows found by reading a snapshot by hand because the page layout doesn't tag the
    # member as "(Incumbent)". Each one quotes what the saved page shows; all are low
    # confidence and need Shyntia's check.
    for m in MANUAL_ROWS:
        icpsr, how, note = match(base, m["state_abbrev"], m["district"], PARTY_CODE[m["party"]], m["name"])
        rows.append({"icpsr": icpsr, "source_name": m["name"], "state_abbrev": m["state_abbrev"],
                     "district_code": m["district"], "party": m["party"], "reason": m["reason"],
                     "status": "called", "source_file": m["source_file"], "source_url": m["source_url"],
                     "how": "manual", "notes": m["notes"] + (f"; {note}" if note else "")})

    draft = pd.DataFrame(rows)

    # member-vs-member: a lost_general whose winner is also a 119th incumbent (state page shows
    # the winner as '(Incumbent) ✔' in the same 2026 district).
    winners = outcomes[outcomes["result"] == "won_general"][["state_abbrev", "district_2026", "source_name"]]
    for i, r in draft[draft["reason"] == "lost_general"].iterrows():
        w = winners[(winners["state_abbrev"] == r["state_abbrev"]) &
                    (winners["district_2026"] == r["district_code"])]
        if len(w):
            draft.loc[i, "notes"] += f"; member_vs_member: lost to incumbent {w['source_name'].iloc[0]}"

    # Fill bioname from the baseline (by icpsr), confidence, and the fixed columns
    # bioname, district_code and party are taken from the BASELINE row (119th Congress),
    # so every column means the same thing in every row. The source's own party label
    # is noted when it differs (e.g. a member now listed as independent).
    by_icpsr = base.set_index("icpsr")
    draft["bioname"] = draft["icpsr"].map(by_icpsr["bioname"])
    base_party = draft["icpsr"].map(by_icpsr["party"])
    differs = base_party.notna() & ~draft["party"].str[:5].eq(base_party.str[:5])
    draft.loc[differs, "notes"] += "; ran as " + draft.loc[differs, "party"] + " in 2026"
    draft.loc[differs, "notes"] += ("; party kept as " + base_party[differs] +
                                    " (decision 13: NOMINATE score measures the 119th record)")
    draft["party"] = base_party.fillna(draft["party"])
    draft["district_code"] = draft["icpsr"].map(by_icpsr["district_code"]).fillna(draft["district_code"])
    draft["source_type"] = "ballotpedia"
    draft["accessed"] = ACCESSED

    def confidence(r):
        if pd.isna(r["icpsr"]) or r["status"] == "uncalled" or r["how"] == "manual":
            return "low"
        if r["how"] != "seat" or (r["reason"] == "lost_general" and "timeline: " not in r["notes"]):
            return "medium"
        return "high"
    draft["confidence"] = draft.apply(confidence, axis=1)
    draft.loc[draft["icpsr"].isna(), "notes"] += "; icpsr LEFT BLANK -- needs Shyntia"
    for col in ["verified_by_author", "second_source_url", "correction"]:
        draft[col] = ""
    draft["icpsr"] = draft["icpsr"].astype("Int64")
    draft = draft.sort_values(["reason", "state_abbrev", "district_code"])
    draft[DRAFT_COLUMNS].to_csv(DRAFT_FILE, index=False)
    print(f"Wrote {len(draft)} rows to {DRAFT_FILE}")

    # 4. Status of every baseline member (for completeness checks in build.py)
    status = base[["icpsr", "bioname", "state_abbrev", "district_code", "party"]].copy()
    dep = draft.dropna(subset=["icpsr"]).groupby("icpsr")
    status["departure_reasons"] = status["icpsr"].map(
        dep["reason"].agg(";".join))
    out = outcomes.dropna(subset=["icpsr"]).groupby("icpsr")
    status["general_results"] = status["icpsr"].map(out["result"].agg(";".join))
    status["status_source_file"] = status["icpsr"].map(out["source_file"].agg(";".join))
    status.to_csv(STATUS_FILE, index=False)
    print(f"Wrote {len(status)} rows to {STATUS_FILE}")

    unmatched = outcomes[outcomes["icpsr"].isna()]
    print(f"State-page incumbents with no baseline match: {len(unmatched)}")
    for _, o in unmatched.iterrows():
        print(f"  {o['source_name']} ({o['state_abbrev']}-{o['district_2026']}, {o['party_label']}): {o['match_note']}")


if __name__ == "__main__":
    main()
