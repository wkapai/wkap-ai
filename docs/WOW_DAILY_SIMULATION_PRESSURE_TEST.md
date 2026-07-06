# Daily WoW Conversation Pressure Test

## Purpose

This pressure test simulates the daily user conversation after Daily WoW setup:

1. Load realistic market-reading samples.
2. Present exactly 3 WoW options.
3. Normalize messy user replies into Daily WoW State v0.2.
4. Ask only for missing required fields.
5. Generate a structured v0.2 packet.
6. Save private journal records.
7. Optionally publish completed packets to the local WKAP ledger.
8. Update local CRM/training files from the result.

The implementation lives in:

- `core/wow_daily_simulation.py`
- `core/management/commands/simulate_daily_wow_conversations.py`
- `tests/test_wow_daily_simulation.py`

## Local Command

Dry run with private journal output:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --start-date 2026-07-06 --json
```

Publish completed simulated packets to the local ledger:

```powershell
.\.venv\Scripts\python.exe manage.py simulate_daily_wow_conversations --start-date 2026-07-06 --publish --json
```

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

Problem: A structured `status_update` with an explicit `author_id` different from the packet `author_id` was not rejected before publish.

Fix: `ledger.parsers._validate_structured_wow_items()` now rejects explicit status update author mismatches.

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
