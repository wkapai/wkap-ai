# Daily WoW Conversation Pressure Test

## Purpose

This pressure test simulates the daily user conversation after Daily WoW setup:

1. Delete stale local simulation data when requested.
2. Load real public market-reading samples.
3. Present exactly 3 WoW options.
4. Normalize messy user replies into Daily WoW State v0.2.
5. Ask only for missing required fields.
6. Generate a structured v0.2 packet.
7. Save private journal records.
8. Optionally publish completed packets to the local WKAP ledger.
9. Optionally verify generated public pages, machine-readable lifecycle fields, source refs, and status-transition coverage.
10. Update local CRM/training files from the result.

The implementation lives in:

- `core/wow_daily_simulation.py`
- `core/management/commands/simulate_daily_wow_conversations.py`
- `tests/test_wow_daily_simulation.py`

The hardening roadmap for making lifecycle/status-update QA fully automated, including oracle-based public-page reconstruction and fix-rerun loops, lives in `docs/WOW_SIMULATION_HARDENING_PLAN.md`.

## Local Command

Delete prior local simulator data only:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --reset-only --json
```

Dry run with private journal output:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --start-date 2026-07-06 --json
```

Delete old simulator data, then publish completed simulated packets to the local ledger:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --reset --start-date 2026-07-06 --publish --json
```

Delete old simulator data, publish completed packets, then verify public pages and lifecycle reconstruction:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --reset --start-date 2026-07-06 --publish --verify-public --json
```

The reset is scoped to simulator-owned data: investor `w0998`, sender `wkap-daily-wow-sim@example.com`, generated `daily-wow-simulation` journal blocks, generated daily case files, local public investor pages, WoW manifests, timestamps, and raw email artifacts for the matching packet ids.

## Real Source Basket

The default daily reading log uses public, traceable source samples:

- CoreWeave and Meta expanded AI infrastructure agreement: `https://www.coreweave.com/news/coreweave-and-meta-announce-21-billion-expanded-ai-infrastructure-agreement`
- TSMC Q4 2025 earnings transcript: `https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-01/51d09df96cd89ac19d65af39032b038dc2896a24/TSMC%204Q25%20Transcript.pdf`
- Circle Q1 2026 results: `https://www.circle.com/pressroom/circle-reports-first-quarter-2026-results`
- BMO, CME Group, and Google Cloud tokenized cash platform: `https://www.cmegroup.com/media-room/press-releases/2026/3/24/bmo-introduces-tokenized-cash-and-deposit-platform-with-cme-group-and-google-cloud.html`
- Tesla Q1 2026 update: `https://ir.tesla.com/_flysystem/s3/sec/000162828026026551/tsla-20260422-gen.pdf`
- Amazon data center energy pledge: `https://www.aboutamazon.com/news/policy-news-views/amazon-data-centers-power-costs-white-house-pledge`
- Constellation Crane Clean Energy Center: `https://www.constellationenergy.com/about/locations/crane-clean-energy-center.html`

The three daily options are built from that basket:

- Trackable: AI infrastructure bottlenecks across capacity contracts, TSMC packaging, and data center power.
- Scoreable: Circle reserve-income growth versus USDC circulation growth by the next quarterly result.
- Thesis: CME tokenized cash as evidence that regulated market infrastructure can absorb 24/7 settlement.

## Coverage

The simulation currently generates 33 daily cases:

- 5 completed conversation cases.
- 1 no-reply private-only case.
- 27 lifecycle status-transition cases.

The lifecycle cases cover every allowed transition in `ledger/wow_lifecycle_rules.py`:

- `candidate_wow`: active, promoted, killed, stale, revived.
- `trackable_wow`: active, promoted, killed, stale, revived.
- `scoreable_signal`: pending, resolved correct, resolved incorrect, unresolved, invalid test, voided.
- `thesis_wow`: active, supported, weakened, retired.

## Problems Found And Fixes

### P1: Old Local Test Data Polluted Reruns

Problem: Repeated local publish runs left `w0998` packets, raw emails, ledger events, generated journal files, public pages, manifests, and raw email artifacts in place. A new run could look successful while still depending on stale local state.

Fix: Added `reset_daily_wow_simulation()` plus `--reset` and `--reset-only` command options. The reset safely deletes only simulator-owned data and guards filesystem deletion to allowed roots.

### P1: Fake Fixtures Hid Whether The Flow Made Sense

Problem: The earlier market-reading samples were plausible but synthetic. That made it hard to judge whether daily choices, pass reasons, and lifecycle updates felt like real investor work.

Fix: Replaced the sample set with public source data from CoreWeave, TSMC, Circle, CME, Tesla, Amazon, and Constellation. The option builder now resolves `source_refs` against the current reading log, and tests assert those links stay grounded.

### P1: No Daily WoW Conversation Simulator

Problem: Existing coverage validated final packet parsing and lifecycle rendering, but not the daily user/agent intake loop.

Fix: Added a simulator that normalizes selection/pass replies into Daily WoW State, validates the state, writes private journal records, and can publish completed packets locally.

### P1: Missing Pre-Submission Daily State Validation

Problem: The backend parser catches malformed final packets, but there was no reusable validator for the agent-facing display and choice flow.

Fix: Added `validate_daily_state()` checks for exactly 3 options, visible type labels, plain-English titles, scoreable visible fields, status update visible fields, selected/pass requirements, and allowed CRM transitions.

### P1: Natural-Language Choice Normalization Bug

Problem: The reply "the scoreable one" initially normalized to option 1 because "one" was detected before the unique type label.

Fix: Type-label matching now runs before ordinal fallback, and generic "one/two/three" matching was removed in favor of explicit numbers or first/second/third.

### P1: Status Update Author Mismatch Could Parse

Problem: A structured `status_update` with an explicit `investor_id` different from the packet `investor_id` was not rejected before publish.

Fix: `ledger.parsers._validate_structured_wow_items()` now rejects explicit status update author mismatches.

### P1: Completed Choice Still Modeled A Blocking Submit

Problem: After a valid user selection/pass plus required reason, the simulator returned a `ready_to_submit` state and "complete and ready to submit" prompt. That did not reflect the user requirement that the agent immediately acknowledge the completed judgment and finish packet generation, ledger send, receipt reconciliation, and public URL verification in the background.

Fix: `normalize_user_reply()` now moves completed responses into `submission_in_progress`, returns the explicit background acknowledgement, and marks normalized replies with `submission: background`. Tests assert the state and acknowledgement prompt.

### P1: Lifecycle Filler Options Had Unresolved Source Refs

Problem: Lifecycle status-update cases published a one-item reading log, but the non-selected filler options were generated from a separate default reading log and could reference `Reading Item 3` or `Reading Item 4`. The packet parsed and rendered, but an outside-agent verification pass found unresolved `source_refs`.

Fix: `lifecycle_transition_options()` now receives the case's actual reading log and builds all filler options against that same source set. The lifecycle simulation test now asserts that every option's `source_refs` resolve against the packet reading log before parsing.

### P2: Installed User-Level Template Drift

Problem: The user-level bundled skill reference template under `.codex/skills/wkap-wow/references/daily-packet-template.md` still shows v0.1, while repo/public specs are v0.2.

Fix: The installed local skill template was updated to v0.2, and the missing installed `references/wow-packet-v0.2.md` snapshot was added so future agent runs do not inherit v0.1 packet defaults.

## Generated Local Artifacts

The simulator writes private artifacts under:

```text
WKAP WoW Journal/
  daily/
  simulation/daily-wow-pressure-test-report.md
  user-judgment-profile.md
  active-trackables.md
  pending-scoreables.md
  thesis-map.md
  receipts.md
  public-verification.md
```

Generated blocks in CRM summary files are delimited with:

```text
<!-- daily-wow-simulation:start -->
...
<!-- daily-wow-simulation:end -->
```

This makes reruns idempotent without wiping hand-written journal content.

## Verification

Initial stale-data reset result:

```text
Deleted 32 packets, 32 raw emails, 1,344 simulator ledger events, 5 generated journal blocks, and 100 generated paths.
```

Latest real-source publish run:

```text
Cases: 33
Completed packets: 32
Published packets: 32
Lifecycle transitions covered: 27
Case errors: 0
```

Targeted simulator tests:

```powershell
.\.venv\Scripts\python.exe manage.py test tests.test_wow_daily_simulation
```

Existing lifecycle/spec regression slice:

```powershell
.\.venv\Scripts\python.exe manage.py test tests.test_wkap_v0.WKAPV0Tests.test_one_investor_lifecycle_crm_covers_all_allowed_status_transitions tests.test_wkap_v0.WKAPV0Tests.test_outside_agent_reconstructs_one_investor_wow_lifecycle_from_public_pages tests.test_wkap_v0.WKAPV0Tests.test_wow_protocol_crm_json_matches_backend_lifecycle_rules tests.test_wkap_v0.WKAPV0Tests.test_wow_intake_and_state_schema_require_visible_daily_options
```

Local ledger validation after publish:

```powershell
.\.venv\Scripts\python.exe manage.py wkap --json validate-all
```
