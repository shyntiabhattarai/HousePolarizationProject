# AI log

One entry per AI session. Entries are appended only; old entries are never rewritten.

---

## 2026-11-23: Session 1 (Phase 1: scaffold, baseline data, diagnostics)

**Tool / model:** Claude Code (CLI), model Claude Opus 5.5 (`claude-opus-5-5`)

**Request (summary):** Phase 1 only. Scaffold the project, set up a venv with pandas,
download Voteview `HSall_members.csv` into `data/raw/` with provenance in `SOURCES.md`,
and write and run `build.py` with diagnostic steps a–j for the 119th House (party
codes, duplicate icpsr, missing scores, low vote counts, mid-Congress departures, a
provisional D/R baseline, a processed CSV, and row accounting). Explicitly out of
scope: lists of departing members, charts or HTML, and web research.

**Setup choices the user approved before work began:**
- Use the existing `HousePolarization/` folder as the project root, not a new `hollow-middle-2026/` subfolder.
- Keep the existing git repo, which PyCharm had already initialized, so `git init` was not run. No push to GitHub for now.
- Reuse the existing `.venv` (Python 3.14.3). Upgrade pip inside it, then install pandas.

**What was done:**
- Created `data/raw/`, `data/processed/`, `logs/`, `notes/`, `transcripts/`, `.gitignore`, `requirements.txt` (pandas==3.1.1) and `README.md`.
- Upgraded pip 23.2.1 → 26.3 and installed pandas 3.1.1 inside `.venv`. pip also pulled in pandas' required dependencies: numpy 2.5.5, python-dateutil 4.0.0 and tzdata 2026.6.
- Downloaded `HSall_members.csv` (6201653 bytes, SHA-256 7af4703c…095ee) and recorded its provenance in `data/raw/SOURCES.md`.
- Wrote `build.py` (steps a–j), ran it once, and logged the output to `logs/build_phase1.txt`. The run wrote `data/processed/house119_baseline.csv` (452 rows).
- Provisional baseline: D mean −0.3887 (n=224), R mean 0.5226 (n=227), gap 0.9112.

**Decisions deferred to the user:**
1. Kevin Kiley appears under two icpsr codes: 22336 (party 200) and 92336 (party 328). The duplicate-icpsr check in step D cannot catch this, because the second row has a different icpsr.
2. Party code 328 is not mapped to a name in `build.py`. The member is kept, flagged `non_dr_party`, and left out of the D/R means.
3. 11 seats have two members each (22 rows, flagged `shared_seat`). In the provisional means, both the departed member and their successor are counted.
4. 4 members died during the 119th (flagged `left_midterm`). The data cannot identify resignations.
5. 13 members have fewer than 100 scaled votes (flagged `low_votes`).
6. Six non-voting delegates and resident commissioners are included (AS, DC, GU, MP, PR, VI).
7. The user asked for an HTML file for GitHub Pages. This was deferred, because the Phase 1 spec rules out HTML. Hosting on Pages will require pushing to GitHub later.

---

## 2026-11-23: Session 2 (Phase 2: decisions recorded, source snapshots, departures draft)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`)

**Continuity:** This session picked up from an earlier Claude Code session in PyCharm's terminal by
way of a HANDOFF.md that Shyntia pasted in. That session wrote `notes/decisions.md` and the
uncommitted build.py steps K–O. The pages it read in Chrome were not saved, so its leads were
re-checked here only against snapshots saved in this session.

**Request (summary):** Verify the state described in the handoff. Save raw source snapshots. Build
`data/interim/departures_draft.csv`. Run completeness checks. Write this log entry. Commit only
after approval, then stop. Do not compute results.

**Choices Shyntia approved before work began:**
1. The completeness checks run as build.py step P (P1–P6), so `logs/build_phase2.txt` is never overwritten by a separate script.
2. Decision 1 is not applied yet. The members who left early stay in the baseline until Shyntia verifies them (clarification B).
3. A member counts as "returning" only if a saved state page shows them winning their Nov. 3 race. In the end every member in the means has a sourced status, so nobody was presumed to be returning.
4. Keep token use low, so no multi-agent workflows were run.

**What was done:**
- Checked: Phase 1 commit `d7cca24` exists; `.idea/` is in `.gitignore` and untracked; raw file hash matches. Re-ran build.py and all three outputs were byte-identical (SHA-256 before and after).
- Removed the empty stray folder `data/interim/sources/` and created `data/sources/`.
- Saved 53 Ballotpedia pages with curl: the not-running list, the House results page, the House elections page, and the 50 state House pages. Each is recorded in `data/sources/SOURCES.md` (URL, date shown on the page, access time, bytes, SHA-256, use). No site blocked curl. Six state pages returned HTTP 202 with no content on the first try and were downloaded again.
- Wrote `extract_departures.py` (standard library + pandas; it reads only `data/sources/`). It writes `data/interim/departures_draft.csv` (125 rows) and `data/interim/member_status_draft.csv` (all 445 members in the party means, with their 2026 status).
- build.py gained step P (checks P1–P6), which writes to `logs/build_phase2.txt`. Steps A–O and the baseline numbers are unchanged.

**Sources saved:** see `data/sources/SOURCES.md`. All of them are Ballotpedia, so every row has only one source until Shyntia verifies it.

**Could not resolve:**
- No saved source gives a total for general-election defeats. The results page's timeline shows only 250 of 431 calls. The elections-2026 page's sentence "Eleven incumbents ... lost re-election in the general elections" appears to be leftover 2024 text and was not used.
- Uncalled races: the results page says 4 uncalled (1 D-held, 3 R-held). The draft has 4 R-held incumbents with no winner (MN-1, NY-1, NY-2, TN-4). The state pages also show LA-5 (R-held) and LA-6 (D-held) as open seats with no winner. For TN-4, the timeline reports a Nov. 19 "Projected by CNN" call, but the state page shows no winner.
- Everton Blair (GA-13, icpsr 22571): the GA page lists him in the Democratic primary with no winner mark, but he isn't on the lost-primary list. He was added by hand as a low-confidence row.
- Missouri redistricting: the two pages disagree on whether Missouri used a new map.
- The not-running page is dated Oct. 2, 2026. The state pages would catch a member who withdrew after that date, but nothing on them shows when a member left.

**Decisions deferred to Shyntia:** see the Phase 2 final response. In summary: the reason for the 4 uncalled rows, TN-4's status, Everton Blair, Kevin Kiley's party (listed as "No party preference" or "(I)" in 2026; the baseline keeps his Republican row), whether same-party top-two losses (CA-4 Thompson, CA-34 Gomez) count as lost_general, and whether a CNN projection counts as "called".

---

## 2026-11-23: Session 2, continued (Phase 2b: apply decision 1, decisions 9–14)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`). Same session as the entry above.

**Request (summary):** Record decisions 9–14 word for word. Apply decision 1. Recompute the cutoffs. Mark uncalled rows as pending with who leads. Add a note to Kiley's row. Tag same-party top-two losses. Remove the Blair row. Re-run both scripts. Shyntia said not to commit, so neither the Phase 2 commit nor the Phase 2b commit was made.

**Correction noted:** in Phase 2, Claude wrote that the members who left early were kept "as you chose". That was wrong. Decision 1 excludes them, as decision 9 now says.

**What was done:**
- `notes/decisions.md`: added decisions 9–14 word for word under "Decisions by Shyntia — 2026-11-23 (Phase 2 follow-up)", the Blair and second-source instructions, and the old-vs-new cutoff table.
- `build.py`:
  - Step M now applies decision 1: the 12 `resigned_died` rows in the draft become `baseline_status = left_before_nov3`, are flagged `left_before_nov3`, and are removed from `in_baseline` and `in_party_means`. Every other row is `held_seat_nov3`.
  - Row accounting gained the matching line.
  - Step O's status label now reads "decision 10".
  - P2 gained a decision-11 note. P6 now confirms each exclusion.
- `extract_departures.py`:
  - Uncalled rows now have `reason = pending` (decision 12), with a note on who leads per the saved results-page timeline.
  - `same_party_general` is tagged automatically (decision 14).
  - Kiley's row gets "ran as No party preference in 2026; party kept as Republican" (decision 13).
  - `MANUAL_ROWS` is now empty, with Blair removed.
  - The timeline reader now records every call, not only "was defeated" lines.
  - Matching no longer filters on `in_baseline`, so the members who left early can still be matched.

**Results of the re-run (baseline only; no departure analysis):**
- Party means: 433 members (214 D, 219 R). D mean −0.3861, R mean 0.5251, gap 0.9111.
- Cutoffs: R 0.4487 (73 moderate), D −0.3340 (72 moderate).
- Draft: 124 rows (lost_general 37, lost_primary 11, pending 4, ran_other_office 28, resigned_died 12, retired 32). Every source total in P2 matches.

**Raised for Shyntia, not decided:**
- Young Kim (CA-40) is also tagged `same_party_general`, because she lost to fellow Republican Ken Calvert in a top-two general that was also member-vs-member.
- NY-1 and NY-2 show "Projected by NYT and AP" on the Ballotpedia timeline. That is Ballotpedia reporting an AP call, not a saved AP page, so they stay pending.
- Under decision 11, none of the 37 lost_general rows has an AP or state source yet. All of them currently rest on Ballotpedia's winner check mark.
- Blair (GA-13) now has an undetermined status in check P3 and stays in the baseline.

---

## 2026-11-23: Session 2, continued (Phase 3: analysis pipeline + tests, no real-data results)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`). Same session as above.

**Request (summary):** Commit Phase 2b. Record decisions 15–18. Build `analyze.py`, which reads only `departures_verified.csv`, with input validation, Q1, Q2, robustness checks and outputs. Build synthetic fixtures and stdlib unittest tests. Show that the guard works. Do not run the analysis on real data.

**Plan approved by Shyntia, with these answers to four questions:**
- Commit locally, never push.
- B uses the `in_party_means` logic: not a delegate, party D or R.
- Members with a row demoted by decision 17 or marked N are removed from B, like pending members.
- AP and state sources are recognised by URL host. AP: `apnews.com`, `ap.org`. State: `.gov`, `.us`.

**Phase 2b commit: NOT made.** The `git commit` command was blocked by Claude Code's permission classifier. Claude did not try to work around the block, and the commit is left for Shyntia.

**What was built:**
- `notes/decisions.md`: decisions 15–18 word for word under "Decisions by Shyntia — 2026-11-23 (Phase 3 setup)", plus the four implementation choices.
- `analyze.py` (pandas, numpy 2.5.5 already installed, standard library; nothing installed):
  - **Guard:** with no verified file, it runs the test suite, prints "VERIFICATION PENDING: no results computed", exits 0 and writes nothing.
  - **Validation:** checks the schema; verified_by_author must be Y, N or blank; a blank on lost_general, lost_primary or pending is a hard fail; a blank on the other reasons is counted and flagged `unverified_sampled_out`; checks icpsr exists and isn't duplicated. N rows are excluded and listed. `correction` is never read.
  - **Decisions applied:** decision 17 (AP/state rule, every lost_general row's URL classification logged); decision 1 re-applied from the verified resigned_died rows, with any change from the draft reported; decision 18 (cutoffs recomputed and compared to cutoffs.csv, stopping on any difference over 1e-12).
  - **Analysis:** pending handling for main, Scenario A and Scenario B; Q1 (means, moderate shares, 10,000-draw permutation test with seed 20261103, hypergeometric cross-check); Q2 (G0, cases (i)–(v), printed arithmetic); 5 robustness checks; the four outputs.
- `build.py` step M now uses `departures_verified.csv` when it exists (rows not marked N), and otherwise the draft. Current outputs are unchanged (SHA-256 checked).
- `tests/__init__.py`, `tests/fixtures/members.csv` (18 synthetic members), `tests/fixtures/departures.csv` (10 synthetic rows), and `tests/test_analysis.py` (10 tests: the 8 required plus an end-to-end run on fixtures and a schema check).

**Test results:** 10 of 10 pass. Test 4: exact p 0.1250 vs. permutation p 0.1244 (8 values, k = 3); exact 0.1500 vs. permutation 0.1467 (6 values, k = 3).

**No results were computed on real data.**
- `departures_verified.csv` does not exist, and `analyze.py` contains no reference to `departures_draft.csv` (checked with grep).
- The guard run added no files to `data/processed/` or `logs/`.
- The only full pipeline run used the synthetic fixtures and wrote to the session scratchpad.

**Interpretations, flagged in the Phase 3 response:**
- Cutoffs come from B before pending and demoted members are removed.
- The permutation population is every analysed Republican.
- Members with no departure row count as returning, which includes Blair.
- Exploratory groups also get p-values.
- The low_votes and same_party_general checks remove those members from both sides.
- The guard returns exit 1 if the test suite fails.
- For Democrats with k ≥ 5, the result is labelled "DEMOCRAT MIRROR" rather than EXPLORATORY.

---

## 2026-11-23: Session 2, continued (Phase 4: artifact generator, synthetic preview only)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`). Same session.

**Request (summary):** Record decision 19 and implement it with tests. Precompute every toggle state into `gap_combinations.csv`. Build `make_artifact.py`, the template, the vendored Plotly and the artifact tests. Generate the synthetic preview only. Update the README. Propose commits for Shyntia to run. Do not run real mode, and do not push.

**Plan:** proposed with a page layout and the exact Plotly URL. Shyntia replied "just do recommended", which approved:
- the Plotly cartesian bundle;
- the number allowlist;
- namespaced `data-metric` keys;
- an exempt author headline;
- `delta_mean_D` and `delta_mean_R` columns;
- histogram bins computed in Python;
- the departures table built from the verified file;
- mean lines that follow the panel;
- a git hash shown with "(uncommitted changes)" when the tree is dirty.

All of these are recorded in notes/decisions.md.

**What was built or changed:**
- `notes/decisions.md`: decision 19 word for word, and the Phase 4 implementation choices.
- `analyze.py`:
  - decision 19 (an N row makes the member returning, and an N on resigned_died puts the member back in B);
  - one scenario naming used everywhere;
  - `gap_combinations.csv` (80 rows);
  - validation counts and cutoffs written into summary.csv;
  - a `VALIDATION PASSED` line in the log;
  - departure columns added to `analysis_members.csv`;
  - `Report.add` now refuses a duplicate summary key with a different value, and keeps a repeated identical row only once. This fixed duplicate "returning" and "baseline" rows that the new provenance test found.
- `tests/test_analysis.py`: hand calculations updated for decision 19 (fixture G0 is now 0.8167), test 11 added for decision 19, test (a)–(d) added for gap_combinations, and a uniqueness check added for summary keys.
- `vendor/plotly-cartesian-4.3.0.min.js`, downloaded from https://cdn.plot.ly/ (SHA-256 38d5da8c…a175), and `vendor/VENDOR.md`.
- `make_artifact.py`, `templates/index.template.html`, `tests/test_artifact.py`, and `notes/headline.md` (contents: TODO).
- `.gitignore`: added `preview/`. `README.md`: rebuild steps, an outputs table, and a note that the preview is synthetic.

**Colours:** checked with the dataviz skill's `validate_palette.js`.
- Party: D #2a78d6, R #e34948.
- Reasons: amber #c98500 and aqua #1baf7a, plus charcoal and grey inks.
- Each reason also has its own hollow marker shape. Orange and violet were rejected for being too close to red and blue.

**Checks:**
- All 23 tests pass.
- The preview was rendered in a headless browser served from localhost: no console errors. At phone width the page overflowed and the dot-plot labels overlapped; both were fixed and re-checked. The histogram's on-bar labels were moved to hover text.
- The screenshots and the local server were removed afterwards.

**Real data:**
- Real mode was NOT run, and `docs/` does not exist.
- `departures_verified.csv` does not exist, so `analyze.py` still prints VERIFICATION PENDING.
- Every page built in this phase used synthetic fixtures.
- **No commit was made, and nothing was pushed.** Shyntia will run the commands.

---

## 2026-11-23: Session 2, continued (Phase 4 follow-up: Shyntia's answers to the Phase 4 questions)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`). Same session.

**Shyntia's answers:**
1. Redraw the dots for each scenario.
2. Hiding the zone labels on phones is fine.
3. Real source metadata in the fixture footer is fine.
4. Keep the repo-link placeholder.
5. Use thousands separators for integers.

He also asked for confirmation of exactly what test 2 exempts inside the vendored Plotly block.

**What was changed:**
- `analyze.py`: `analysis_members.csv` gained `group_no_low_votes` and `group_no_same_party_general`. Members that check removes get `excluded_low_votes` or `excluded_same_party_general`; everyone else keeps their main group. Every page scenario now has its own group column.
- `make_artifact.py`:
  - The dot-plot traces are built once per scenario from that scenario's group column, with the same trace order and names in each, `ids` set to the icpsr codes, and `meta` set to the group.
  - Integers are formatted with thousands separators ("10,000"). The provenance test uses the same `fmt()`, so the check matches.
  - Two new group labels for the excluded members.
- `templates/index.template.html`: when the scenario changes, `Plotly.react` redraws the dots, then the mean lines move. The chart note now says the dots and lines follow the panel's scenario.
- `tests/test_analysis.py`: test (e) checks that each scenario's group column marks exactly that scenario's analysed members, with the same groups.
- `tests/test_artifact.py`:
  - Test 8 checks that every member sits in the trace its scenario column says, and that pending fixture member 103 is "excluded" in main, lost_general in Scenario A, and returning in Scenario B.
  - Test 2 is tightened: inside the vendor block, `XMLHttpRequest` must appear exactly once and every other forbidden string zero times. Outside the block, no forbidden string may appear. Exactly one vendor block may exist, and it must be byte-identical to the SHA-checked file.
- `vendor/VENDOR.md`: describes the tightened check.

**Checks:**
- All 25 tests pass.
- The preview was rebuilt (1,862,125 bytes).
- In a headless browser, switching to Scenario A redraws member 103 as an amber lost_general circle, and the lines match the panel. The only console message was the browser's automatic favicon.ico 404 from the local test server, which doesn't come from the page's code. The server and screenshots were removed.
- Real mode was not run. `docs/` does not exist. Nothing was committed or pushed.

---

## 2026-11-23: Session 2, continued (Final code session)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`). Same session.

**Request (summary):**
- Phase 4 fixes, plus `site_config.json` and `docs/.nojekyll`.
- The verification worksheet and the sample draw.
- `progress.py`, `finalize_verification.py`, `package.py` and `run_all.sh` (created, not run).
- README order, tests, the fixture preview, and this log.

The plan was proposed and approved ("recomended always"). The three choices are recorded in notes/decisions.md:
- the raw CSV is excluded by default (`--include-raw-csv` adds it);
- `run_all.sh` passes `--force` through to step 1;
- every Y/N row needs a second source.

**What was built or changed:**
- **Part 1.** The per-scenario dots and thousands separators were already done in the previous follow-up and were re-tested.
  - The self-contained check moved into `make_artifact.self_contained_problems()`, used by both the tests and `package.py`. Its only exemption is `XMLHttpRequest` once, inside the single byte-identical Plotly block.
  - New test 2b injects `XMLHttpRequest`, `fetch(` and a stylesheet link outside the block, and an extra `XMLHttpRequest` inside it, and confirms all are caught.
  - `site_config.json` is `{"repo_url": ""}`; the footer shows "[repo link pending]". Test 9 covers this.
  - `docs/.nojekyll` created. `docs/index.html` was NOT generated.
- **Part 2.**
  - `scripts/draw_sample.py`: Python 3.14.3, `random.seed(20261123)`, `random.sample(sorted icpsr, 15)` from 72 rows. Output: `data/interim/verification_sample.csv`.
  - `scripts/make_worksheet.py` wrote `data/interim/verification_worksheet.csv`: 125 rows, with check_order 1–8 = 1 / 4 / 1 / 2 / 35 / 10 / 15 / 57. The Blair row's display name comes from the baseline's GA-13 member who held the seat. Foxx, Kiley and Al Green are identified by icpsr. Shyntia's three columns are blank, and nothing was looked up. It refuses to overwrite an existing worksheet without `--force`.
  - The draft's SHA-256 is unchanged.
- **Part 3:** `scripts/progress.py` (read-only), using `scripts/worksheet_common.py`.
- **Part 4:** `scripts/finalize_verification.py`. It refuses on blank required rows, Y/N rows without a second source, a Blair row with no icpsr, an existing output without `--force`, or a failed `analyze.validate_departures`, and writes nothing in any of those cases. The output has the draft's columns in the draft's order. Covered by `tests/test_finalize.py`.
- **Part 5:** `scripts/package.py` and `tests/test_package.py`. Run once on the real project: it correctly refused, because `docs/index.html` is missing. `submission/` was added to `.gitignore`.
- **Part 6:** `scripts/run_all.sh`. Syntax-checked with `bash -n`, NOT run.
- **Part 7:**
  - All 40 tests pass.
  - The fixture preview was rebuilt and checked headlessly: Scenario A draws pending member 103 as lost_general. The only console message was the browser's favicon 404 from the local test server. Screenshots and the server were removed.
  - `progress.py` shows 68 blank required rows and 0 done.

**Not done, on purpose:** no real-mode build, no analysis of real data, no commit, no push.

---

## 2026-11-23: Session 2, continued (Final automated run: AI verification, analysis, artifact, package)

**Tool / model:** Claude Code in VS Code, model: Claude Opus 5.5 (`claude-opus-5-5`), with Claude Code subagent workflows. Same session.

**Summary:** this session covered the cross-check of the departures (decision 20; all 68 rows in check_order 1–7 against saved state or AP-reporting sources), the headline draft in notes/headline.md, and the independent arithmetic check in scripts/independent_check.py. Shyntia made decisions 20–23, approved corrections 1–5, and accepted LaLota's source. The author columns (verified_by_author, second_source_url, correction) are blank.

**What was done:**
- **Decisions.** 20–23 appended word for word, with an amendment record for decision 17 and the implementation choices. The schema gained `verified_by, ai_verified, ai_source_type, ai_call_basis, ai_second_source_url, ai_second_source_file, ai_correction`. analyze.py, build.py, the worksheet scripts, finalize, progress, make_artifact, the fixtures and the tests were updated. New robustness checks: `state_sources_only` (decision 22) and `certified_or_ap_only` (decision 23).
- **AI cross-check.** A workflow of 10 subagents, one per state group, saved 56 source files with curl into data/sources/ and returned a finding for each row. Their raw output is in data/interim/ai_crosscheck_findings.json.
- **Evidence checks.** Claude checked every file's SHA-256 and size; 38 rows were confirmed by text matching. 4 further subagents adversarially re-verified the other 30 rows against the saved files, and all were supported.
- **Results.** 53 confirmed, 12 corrected (Blair, plus 11 rows moved to pending by decision 23, Foxx and Murphy among them), 2 marked N (LaLota, Garbarino; they return), 1 unresolved (Wagner).
- **Decision 23.** 7 more subagents extracted top-two totals and reporting/certification status from the saved state files (data/interim/decision23_extraction.json). scripts/apply_ai_crosscheck.py re-checked every number and name against the file, computed the margins, and applied the rule. Output: data/interim/decision23_margins.csv.
  - 24 lost_general rows stay called: 11 AP-cited, 13 unofficial state results with a complete count, a margin of at least 0.5 pp and no recount request.
  - 11 became pending: NC-5 (recount request), NC-3 (0.109 pp), IA-1 (19 of 20 reporting), IN-5 (reporting not shown), OH-7/10/15 (outstanding ballots), and PA-1/7/8/10 (98.53% of districts reporting).
  - Wagner stays unresolved.
- **Validation fix from saved sources only.** The first run_all.sh stopped at validation: Mills, Ogles and Rose had state results on non-.gov hosts (results.elections.myflorida.com, sos-prod.tnsosgovfiles.com). No code was changed to get past it. Their second source was switched to saved .gov pages that support each row (HOST_FIXES in apply_ai_crosscheck.py), with the non-.gov files kept as supporting evidence.
- **SOURCES.md.** All 56 new files are recorded (5 marked supporting), with hashes recomputed from disk.
- **run_all.sh** (finalize → build → analyze → make_artifact, real mode) finished. B = 433 (214 D, 219 R). Cutoffs unchanged at R 0.4487 / D −0.3340. VALIDATION PASSED. The decision-17 check MATCHES. All hypergeometric cross-checks agree.
- **Independent check.** The Republican lost_general mean, G0 and the returning-only gap all match summary.csv to 1e-9.
- **Results** (main):
  - Q1: k = 23 Republican lost_general; their mean is 0.420 against 0.550 for returning Republicans; 60.9% are moderate against a 31.7% baseline; permutation p = 0.0002; exact moderate-count p = 0.0022.
  - Q2: G0 = 0.918; the returning-only gap is 0.929 (+0.011).
- **Page and package.** Real-mode docs/index.html built (2.9 MB, self-contained, headline present, footer says the AI did the cross-check). Checked in a headless browser, with screenshots deleted afterwards. All 47 tests pass. submission/HousePolarization_submission.zip built: 166 files, raw Voteview CSV not included.
- **Test changes, and why.**
  - The provenance test now separates Ballotpedia snapshots from AI source files.
  - Two tests that assumed "no real outputs yet" or "headline still TODO" now use temporary files.
  - One label was reworded to the allowlisted "decision 17" form.

  No test was weakened to pass a real-data check.

**Not done:** no git command was run, and nothing was pushed.

**Token note:** the four subagent workflows used about 2.2M subagent tokens in total.

---

## 2026-11-23: Session 2, continued (deployment prep)

**Tool / model:** Claude Code in VS Code, Claude Opus 5.5 (`claude-opus-5-5`).

- Shyntia gave the deployment repo, https://github.com/shyntiabhattarai/HousePolarizationProject. It was written into `site_config.json`.
- The real page was rebuilt (the footer now links to the repo) and the ZIP repackaged.
- `tests/test_artifact.py` test 9 now checks the empty-link placeholder with a temporary config, so it no longer depends on the real file. All 47 tests pass.
- Read-only checks: the local repo has no remote yet. The GitHub repo's `main` holds only GitHub's "Initial commit" (a 243-byte README.md), so the push needs a merge of unrelated histories.
- No commit, merge or push was run by the AI. Shyntia runs those.
