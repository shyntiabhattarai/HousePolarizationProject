# Decisions by Shyntia — 2026-11-23

My decisions:
1. Baseline population: House members who held a seat on November 3, 2026. Members who died or resigned before that date are excluded from the baseline and are NOT counted as wave departures. Special-election winners who held the seat on Nov 3 are included.
2. Duplicate icpsr rows (e.g. a party switch): keep the row with the larger nominate_number_of_votes, and flag it as duplicate_resolved.
3. Missing nominate_dim1: exclude, and report the count and names.
4. Fewer than 100 scored votes: keep, flagged low_votes. Report the results with and without these members as a robustness check later.
5. Members who are not Democrats or Republicans: keep them in the data and the plot, but exclude them from party means.
6. Pre-registered definition of "moderate," fixed BEFORE any departure analysis: a Republican is moderate if their baseline nominate_dim1 is in the lowest third of the Republican baseline distribution (least conservative). A Democrat is moderate if their baseline nominate_dim1 is in the highest third of the Democratic baseline distribution (least liberal). The tercile cutoffs are computed once on the baseline and saved to data/processed/cutoffs.csv.
7. Departure reasons: lost_general, lost_primary, retired, ran_other_office, resigned_died. An incumbent who failed to advance from a top-two or jungle primary counts as lost_primary. An incumbent who lost a member-vs-member general election because of redistricting counts as lost_general, with "member_vs_member" noted.
8. Uncalled races stay in the data with status = uncalled. They are excluded from the main result and shown as a sensitivity check.

## Clarifications Shyntia chose on 2026-11-23 (from options Claude proposed; not part of the list above)

- A. Decision 2 also applies to rows that share a `bioguide_id` but have different icpsr codes (Kevin Kiley: icpsr 22336 and 92336, both bioguide_id K000401).
- B. Decision 6 timing: `cutoffs.csv` is written now as PROVISIONAL. It is recomputed once and frozen after Part 2's mid-Congress departures (decision 1) are verified, and before any departure analysis (Phase 3).
- C. Non-voting delegates and resident commissioners (AS, DC, GU, MP, PR, VI) stay in the data, flagged `delegate`, but are excluded from party means, tercile cutoffs and the departures search.
- D. Part 2 web sources are saved as local snapshots (`curl`) with URL, access time and SHA-256 recorded.
- E. Decision 1 stays open until Part 2 identifies members who left before Nov 3 from sources.

Implementation choices Claude made (open to change): tercile cutoffs use pandas `Series.quantile` with its default linear interpolation; a Republican at or below the R cutoff, or a Democrat at or above the D cutoff, counts as moderate.

# Decisions by Shyntia — 2026-11-23 (Phase 2 follow-up)

9. Correction: decision 1 excludes members who died or resigned before Nov 3, 2026 from the baseline. Your report said they were kept "as you chose" — that is incorrect. Apply decision 1 now.
10. Because the baseline changes, recompute the tercile cutoffs on the corrected baseline. This is still before any departure analysis, so the pre-registration holds. Record the old and new cutoffs side by side in notes/decisions.md.
11. "Called" means an AP call or an official/certified state result. A network projection alone (e.g. CNN) does not count. TN-4 stays uncalled unless a saved AP or state source shows otherwise.
12. Uncalled rows: set reason = "pending" and status = uncalled. Add a notes entry saying who leads per the source, if shown. They are excluded from the main result. Phase 3 will run two scenarios: all pending incumbents lose, and all pending incumbents win.
13. Kiley: party stays Republican in the baseline, because his NOMINATE score measures his 119th-Congress record. Note "ran as No party preference in 2026" in notes.
14. Same-party top-two general losses (Thompson CA-4, Gomez CA-34): reason = lost_general, with note "same_party_general". Phase 3 reports results with and without them.

Also in the same message: the hand-added Everton Blair (GA-13) row was removed from MANUAL_ROWS for now.

## Tercile cutoffs, old vs. new (decision 10)

Both rows come from `build.py` step O (pandas `Series.quantile`, linear interpolation), and both are computed on baseline members only, before any departure analysis.

| | Old: Phase 2, before decision 1 | New: decision 1 applied (decision 9) |
|---|---|---|
| Baseline in party means | 445 (221 D, 224 R) | 433 (214 D, 219 R) |
| Republican cutoff (1/3 quantile), moderate if ≤ | 0.45 (75 of 224 moderate) | 0.44866666666666666 (73 of 219 moderate) |
| Democrat cutoff (2/3 quantile), moderate if ≥ | −0.33333333333333337 (74 of 221 moderate) | −0.334 (72 of 214 moderate) |

The 12 members removed are the `resigned_died` rows of `data/interim/departures_draft.csv`, which is still unverified. If Shyntia's verification changes that list, the cutoffs change too.

# Decisions by Shyntia — 2026-11-23 (Phase 3 setup)

15. Young Kim (CA-40) keeps the same_party_general tag. Decision 14 is a rule, not a list of names, and it applies to her by its terms.
16. NY-1 (LaLota) and NY-2 (Garbarino) stay pending until I save an AP or state source during my verification pass. If a source confirms they won, they are returning members, not departures.
17. A lost_general row counts as called in the analysis only if verified_by_author = "Y" and second_source_url points to an AP or state election page. Ballotpedia reporting a call is not enough on its own. Rows that fail this test are reported separately and excluded from the main result.
18. Cutoffs are recomputed from the final baseline every time the analysis runs. If they differ from data/processed/cutoffs.csv, the analysis stops and prints both, so I can record the change before any results are shown.

## Implementation choices Shyntia picked on 2026-11-23 (Phase 3 planning; options Claude proposed)

- B (the baseline) means "in baseline, not a delegate, party D or R", the same as `in_party_means`. A literal reading of `in_baseline` would have put the 6 delegates into the party means.
- Members whose lost_general row is demoted by decision 17, or whose row is marked verified_by_author = N, are removed from B, as pending members are. They count as neither departures nor returning, and are listed separately.
- An "AP or state election page" is recognised from the second_source_url host. AP: the host ends with `apnews.com` or `ap.org`. State: the host ends with `.gov` or `.us`. Every URL and its classification is printed in the log.
- Commits are local only. Nothing is pushed.

# Decisions by Shyntia — 2026-11-23 (Phase 4 setup)

19. Meaning of verified_by_author = "N": the person did NOT leave the House (the departure claim is false). That member returns to B as a returning member, whatever the row's reason. If the person did leave but the AI chose the wrong reason or status, I fix the row's values and mark it "Y". The correction column documents what I changed. This replaces the Phase 3 interpretation that an "N" on a resigned_died row removes the member from B.

Note: decision 19 also replaces the Phase 3 planning choice that members whose row is marked N are removed from B. Rows demoted by decision 17 are still removed from B.

## Implementation choices Shyntia approved on 2026-11-23 (Phase 4 planning: "just do recommended")

- Plotly: the official partial bundle `https://cdn.plot.ly/plotly-cartesian-4.3.0.min.js` (scatter, bar and histogram), inlined into the page. Details are in `vendor/VENDOR.md`.
- Number-provenance test: an explicit allowlist covers numbers that are fixed text rather than data (the title's 2026, Nov 3, 119th, 120th, dimension 1, decision numbers, axis labels). Every other visible number carries `data-metric`.
- `data-metric` keys use namespaces:
  - `summary:` a summary.csv row;
  - `combo:` a gap_combinations.csv row;
  - `members:` an analysis_members.csv cell;
  - `dep:` a departures-file cell;
  - `meta:` a value read from a source file (SOURCES.md, git, vendor).

  The count of rows with an AP or state second source goes into summary.csv as a validation metric.
- The headline box (notes/headline.md) is Shyntia's own text. It is exempt from the provenance test and labelled "Author's summary".
- gap_combinations.csv also has `delta_mean_D` and `delta_mean_R` columns, so the page's sentence compares two looked-up numbers and does no arithmetic.
- Histogram bins are computed in Python (40 equal-width bins) and embedded. All 10,000 draws are embedded too.
- The departures table is built from the verified departures file, which makes it a required real-mode input. analysis_members.csv gains reason, status, verified_by_author, source_url and second_source_url columns.
- The mean lines on the dot plot follow the before/after panel's selection, using looked-up values only.
- The footer shows the git commit hash, followed by "(uncommitted changes)" when the working tree is dirty.

## Implementation choices Shyntia approved on 2026-11-23 (final code session: "recomended always")

- The submission ZIP leaves out the raw Voteview CSV (6,201,653 bytes) by default and cites its URL and SHA-256 (data/raw/SOURCES.md). `scripts/package.py --include-raw-csv` adds it.
- `scripts/run_all.sh` passes its arguments to step 1, so `bash scripts/run_all.sh --force` lets finalize_verification.py overwrite an existing departures_verified.csv on purpose.
- Every row marked Y or N needs a second_source_url, including an N on a resigned_died row (exactly as specified).

# Decisions by Shyntia — 2026-11-23 (final automated run)

20. Verification in this run was performed by the AI (Claude Code). Columns verified_by_author, second_source_url, and correction stay blank. New columns record the AI check: verified_by (always "ai"), ai_verified (Y/N), ai_second_source_url, ai_second_source_file, ai_correction. Decisions 17 and 19 apply to ai_verified and ai_second_source_url in the same way they applied to the author columns.

21. A check_order 1–7 row for which no AP or state source could be saved is marked ai_verified blank with notes 'no second source obtained'. For lost_general, lost_primary and pending rows, that member is removed from B and reported separately, as with a decision-17 demotion. A sampled retired/ran_other_office/resigned_died row left blank counts as unverified_sampled_out.

22. Because AP blocks automated access and many state results pages render via JavaScript, a saved news article that explicitly reports an AP race call (naming AP as the caller) counts as a second source, labeled ai_source_type = "news_reporting_ap". Priority order: state .gov page or PDF, then news_reporting_ap. Network projections that do not cite AP still do not count (decision 11 stands). Add a robustness check "state_sources_only" that uses only rows with a state .gov second source, and show it on the page's robustness table. Decision 17 is amended accordingly; record the amendment in decisions.md without editing decision 17's original text.

## Amendment record: decision 17 as amended by decision 22 (decision 17's original text above is unchanged)

Under decisions 20 and 22, a lost_general row counts as called in the analysis only if ai_verified = "Y" and the AI's second source is one of the following:
- an AP page (ai_source_type "ap");
- a state election page or PDF on a .gov or .us host (ai_source_type "state");
- a saved news article that explicitly names AP as the caller of the race (ai_source_type "news_reporting_ap").

Ballotpedia, network projections without an AP attribution, and other news do not count. Rows that fail the test are reported separately and removed from B. The robustness check "state_sources_only" counts only ai_source_type "state".

## Implementation choices (final automated run; Shyntia approved "recomended always" / this run's plan)

- **Schema.** After the draft's 16 columns come `verified_by, ai_verified, ai_source_type, ai_second_source_url, ai_second_source_file, ai_correction`. Under decision 20, validation fails if any of verified_by_author, second_source_url or correction is filled, or if verified_by is not "ai".
- **ai_source_type values:**
  - `state`: the URL host must end in .gov or .us;
  - `ap`: apnews.com or ap.org;
  - `news_reporting_ap`;
  - `federal_gov`: allowed only for resigned_died rows, e.g. clerk.house.gov; it never counts for election outcomes;
  - blank, for unresolved rows.

  Validation checks that the type agrees with the URL host.
- **Decision 21.** Accepted only when the row's notes contain "no second source obtained". In the analysis those members get the role `excluded_unresolved`.

# Decisions by Shyntia — 2026-11-23 (final automated run, after the AI cross-check)

23. Amends decision 11 for this run: an unofficial state .gov result counts as called if the saved file shows the count complete (100% reporting, or no outstanding-ballot indication), the margin between the top two candidates is at least 0.5 percentage points of their combined vote, and no saved source shows a recount request. Otherwise the race is pending. Record "unofficial" and the computed margin in notes for every row that relies on an unofficial state result. Add a robustness check "certified_or_ap_only" that counts only certified state results or AP-cited calls.

Also approved in the same message:
- Corrections 1–5 from the AI cross-check: Foxx (NC-5) to pending; Blair (GA-13, icpsr 22571) to lost_primary; Garbarino (NY-2) and LaLota (NY-1) ai_verified N, so both are returning; Wagner (MO-2) unresolved under decision 21.
- LaLota's source (AP's own race-result bulletin) is accepted as news_reporting_ap.
- Decision 23 applies to every lost_general row, Murphy (NC-3) and Foxx (NC-5) included. Each margin is computed from the saved file only. If a file does not show both candidates' totals or the reporting status, the row is marked pending with a note, never guessed.

## Implementation choices for decision 23

- New column `ai_call_basis` after `ai_source_type`:
  - `ap_call`: an AP page, or a news article naming AP as the caller;
  - `certified_state`: the saved state file says the results are certified/official;
  - `unofficial_state`: an unofficial state result that passes decision 23;
  - blank: anything else.
- **Margin** = |votes of the top two candidates' difference| ÷ (their combined votes) × 100, computed in `scripts/apply_ai_crosscheck.py` from totals that were extracted from the saved file and confirmed to appear in it. The result is recorded in `data/interim/decision23_margins.csv`.
- **Count complete** must be shown by the file itself. "Not shown" means pending, as Shyntia specified.
- **certified_or_ap_only:** lost_general counts only when `ai_call_basis` is `certified_state` or `ap_call`. Other lost_general rows are removed from B in that check, as in state_sources_only.
