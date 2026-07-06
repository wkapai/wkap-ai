# WKAP WoW Skill v0.1

## Metadata

skill_name: WKAP WoW Skill  
skill_version: v0.1  
skill_url: https://wkap.ai/skills/wkap-wow-skill-v0.1.md  
latest_skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md  
current_wow_packet_spec: https://wkap.ai/specs/wow-packet-latest.md
current_wow_crm_spec: https://wkap.ai/specs/wow-crm-latest.json
current_wow_intake_flow: https://wkap.ai/specs/wow-intake-flow-latest.json
current_daily_wow_state_schema: https://wkap.ai/specs/daily-wow-state-latest.schema.json

This Markdown file is the canonical public operating manual for WKAP WoW Skill v0.1. The machine-readable CRM, intake, and daily state JSON specs are the execution contract. If this Markdown and the JSON specs disagree, follow the JSON specs and record the mismatch privately.

## Agent Facts

```yaml
agent_facts:
  skill: wkap_wow_skill
  skill_version: v0.1
  current_wow_packet_spec: https://wkap.ai/specs/wow-packet-latest.md
  current_wow_crm_spec: https://wkap.ai/specs/wow-crm-latest.json
  current_wow_intake_flow: https://wkap.ai/specs/wow-intake-flow-latest.json
  current_daily_wow_state_schema: https://wkap.ai/specs/daily-wow-state-latest.schema.json
  default_spec_fetch: daily
  minimum_fallback_refresh_days: 30
  private_journal_required: true
  public_submission_requires_user_approval: true
  user_decision_is_submission_approval: true
  setup_mode: low_friction_defaults_first
  ask_user_only_when_blocked: true
  durable_private_journal_required: true
  agent_memory_cache_only: true
```

## Purpose

The WKAP WoW Skill helps an agent prepare Daily WoW Packets, maintain a private workout trail, ask the user for judgment, and submit only approved packets to WKAP Public Ledger.

It is not a newsletter-writing skill. It is an investor judgment training skill.

## Core Principle

Agent prepares. User judges. Private Journal preserves the workout trail. WKAP Ledger records what became public.

Private WoW Journal builds skill. WKAP Public Ledger builds reputation.

## Setup Behavior

The agent should not start with a long interview.

Default setup behavior:

```yaml
setup_defaults:
  setup_mode: defaults_first
  ask_user_only_when_blocked: true
  private_journal_location: durable user-owned Markdown storage; local Markdown folder if filesystem access exists
  author_id: use known WKAP investor ID if available; otherwise use a stable local draft identity until public ledger identity is assigned or confirmed
  daily_send_time: infer from the user's behavior pattern after daily investment research; ask only if it cannot be inferred
  research_sources: agent-accessible browser activity, pasted/saved/reviewed items, explicit user requests, and high-quality agent-found market items
  approval_flow: suggest 3 WoW signals, collect user selection or pass plus required reason, then submit; no reply means save privately and submit nothing publicly
  default_packet_scope: one Daily WoW Packet for the current US market day
  weekly_review_requires_explicit_user_request: true
```

The agent may briefly confirm the setup after applying defaults, but it should not block installation on questions about journal location, author ID, schedule, source list, or approval flow unless those defaults are impossible to apply.

## Default Run Scope

The default WKAP WoW run is one Daily WoW Packet for the current US market day.

Do not summarize the user's past 7 days, create a weekly review, or produce a general private research memo unless the user explicitly asks for a weekly or multi-day review.

The agent may use recent context as background, but the output must be framed as today's Daily WoW Packet with today's `market_date`.

## Source of Truth

Current WoW Packet Spec:

https://wkap.ai/specs/wow-packet-latest.md

Current WoW CRM Spec:

https://wkap.ai/specs/wow-crm-latest.json

Current WoW Intake Flow:

https://wkap.ai/specs/wow-intake-flow-latest.json

Current Daily WoW State Schema:

https://wkap.ai/specs/daily-wow-state-latest.schema.json

The agent must treat these latest URLs as the current public source of truth for packet shape, CRM state, intake state, required fields, and allowed lifecycle transitions.

## Strict Intake Program Rule

During user data collection, behave like an intake program, not a free-form advisor.

The user may reply in natural language. The agent must normalize the reply into the Daily WoW State object, validate it against the intake flow and CRM specs, then ask only for missing required fields.

Do not invent required user fields. Do not pick for the user. Do not decide that a completed valid daily packet should remain private because it is imperfect or low confidence. The normal successful workout result is a published Daily WoW Packet on WKAP Ledger.

The daily choice flow is fixed:

1. Prepare exactly 3 WoW options from today's top reading items and active private CRM state.
2. Ask the user to pick 1, 2, 3, or pass.
3. If the user selects an option, collect `reason_for_selection`.
4. If the user passes, collect `closest_rejected_wow`, `reason_for_pass`, and `missing_evidence`.
5. `closest_rejected_wow` must be one of today's 3 `wow_id` values.
6. Selection/pass plus required fields is submission approval.
7. Generate the structured packet, validate it, save it privately, and submit it publicly.
8. Do not ask for a second approval unless the user explicitly interrupts the submission.

## Spec Refresh Rule

Default behavior: fetch the latest WoW Packet Spec daily before preparing a Daily WoW Packet.

Minimum fallback for non-daily agents: refresh the spec at least every 30 days.

The agent should record the spec version and spec URL used for each prepared packet.

## Private WoW Journal

The agent must maintain a Private WoW Journal for the user.

Every prepared Daily WoW Packet must be saved to the Private WoW Journal, whether or not the user approves, rejects, edits, ignores, or submits it.

The Private WoW Journal must be stored in durable user-owned storage.

If the agent has local filesystem access, it must use a local Markdown folder by default. Prefer a `WKAP WoW Journal/` folder in the active workspace, project folder, or user documents area. Create the folder and files if missing.

If the agent does not have local filesystem access, it must use an equivalent durable user-owned store such as Drive, Git-backed Markdown, Notion, or another user-controlled document store. Agent memory may be used as a cache, but it must not be the only Private WoW Journal.

Ask the user for a path only if no durable writable default is available or the user wants to change it. After setup, tell the user where the Private WoW Journal is stored.

Example:

```text
/WKAP WoW Journal/
  daily/
    2026-07-05.md
  active-trackables.md
  pending-scoreables.md
  thesis-map.md
  receipts.md
  public-verification.md
```

Pure agent memory can be a cache, but it must not be the only durable journal.

## Author Identity Default

Do not block private setup on WKAP `author_id`.

If the user's WKAP investor ID is known, use it as `author_id`. If not, use a stable local draft identity such as a user or agent slug for private records. When the first public WKAP Ledger submission assigns or confirms the public investor ID, update future packets and preserve the mapping in the Private WoW Journal.

## Private vs Public Lineage

Private lineage helps the agent and user remember how an idea developed.

Private journal lineage is context, not public timing proof.

Public lineage proof starts at the earliest publicly ledgered ancestor on WKAP.

Private noticed is not public proof. Public submitted is not the same as receipt received. Published on WKAP means public.

## Daily Workflow

```text
1. Fetch latest packet spec.
2. Read the user's investment context from agent-accessible browser activity, pasted/saved/reviewed items, explicit user requests, and high-quality agent-found market items.
3. Build or update the private reading log.
4. Select up to 10 reading items most worth preserving in today's investor log.
5. Review private lifecycle state from active-trackables.md, pending-scoreables.md, thesis-map.md, receipts.md, public-verification.md, and prior daily packets.
6. Suggest exactly 3 WoW signals for the user to choose from.
7. Classify each suggested signal with wow_type and lineage/status fields where applicable.
8. Ask the user to choose exactly one: select 1, select 2, select 3, or pass.
9. Ask for the required reason: reason_for_selection when selecting, or reason_for_pass when passing.
10. If the choice or reason is missing, ask only for the missing required field.
11. Once choice plus reason exists, generate the final v0.1 Daily WoW Packet with reading_log, exactly 3 wow_items, selection, agent_facts, and validation_notes.
12. Save the full structured packet to the Private WoW Journal.
13. Submit the packet to WKAP Ledger.
14. Reconcile receipt and public site status after attempted submission.
15. Update private lifecycle state after submission.
```

## Agent CRM Operating Loop

The Private WoW Journal is not just a packet archive. It is the agent CRM for investment ideas.

Before suggesting the 3 daily WoWs, the agent must run this operating loop:

```text
1. Load today's reading log candidates.
2. Load active CRM state: active candidates, active trackables, pending scoreable signals, active thesis records, context notes, receipts, and public verification.
3. Check whether today's reading creates a new idea, strengthens an existing idea, weakens an existing idea, resolves a scoreable signal, makes a prior test invalid, or makes an old idea stale.
4. Classify each possible daily option with the WoW type decision rules below.
5. If an existing idea changes state, prepare an append-only status_update instead of rewriting the old idea.
6. Pick the 3 highest-value daily options for the user. These 3 options may include new WoWs, existing-WoW status updates, or a mix.
7. After the user selects or passes, generate the final packet, submit it, then update the local CRM files from the submitted packet plus the public WKAP URL.
```

The agent must never treat a public WoW artifact as mutable. Current CRM state is derived from the original item plus later public or private status updates.

## Daily WoW Workout Routine

The daily routine is a workout, not a drafting loop.

The agent must suggest exactly 3 WoW signals. The user must choose one of:

```text
1. select WoW 1
2. select WoW 2
3. select WoW 3
4. pass today
```

Any of the 3 options may be a new WoW signal or an append-only `status_update` for an existing WoW signal when today's reading provides new evidence, a promotion, a resolution, or a maintenance event.

Required user fields:

```yaml
selected:
  required:
    - selected_wow_id
    - reason_for_selection
  pass_only_fields:
    closest_rejected_wow: null
    why_pass: null
    missing_evidence: null

passed:
  required:
    - selected_wow_id: none
    - reason_for_pass
    - closest_rejected_wow
    - missing_evidence
```

For a pass, `closest_rejected_wow` must be the `wow_id` of one of today's 3 suggested WoW signals. Do not invent a new prose rejected idea at selection time.

The user selection/pass plus required reason is submission approval. Do not ask for a second approval after the user completes the daily choice.

Do not ask the user to edit the packet, approve the packet text, or request more research as part of the default routine. If the user explicitly asks to edit or research more, follow that instruction, then return to the same selection/pass plus reason flow.

## Required Prepared Packet Shape

Every prepared Daily WoW Packet must preserve the public-ready v0.1 structure even when it remains private.

Minimum prepared packet sections:

```yaml
required_private_packet_sections:
  - packet
  - human_view
  - agent_facts
  - reading_log
  - wow_items
  - selection
  - validation_notes
```

A prose list of "top private WoWs" is not a valid WKAP WoW output by itself. The agent may include a short human summary, but it must also save and show the structured packet.

Before final packet generation, the agent must show the 3 candidate WoW signals and ask the user to choose exactly one of:

```text
1. select WoW 1
2. select WoW 2
3. select WoW 3
4. pass today
```

## WoW Type Handling

The agent must classify each item as one of:

```yaml
valid_wow_types:
  - candidate_wow
  - trackable_wow
  - scoreable_signal
  - thesis_wow
  - context_note
  - status_update
```

The agent must not treat `trackable_wow`, `context_note`, `thesis_wow`, or `status_update` as scoreable predictions.

Only `scoreable_signal` is eligible for calibration scoring.

### WoW Type Decision Rules

Use these rules before presenting the 3 daily options:

```yaml
candidate_wow:
  use_when: An observation is worth preserving, but the monitorable evidence, cadence, or falsifiable test is not clear yet.
  default_status: active_candidate
  example: GPU rental prices look weak, but the source set is still too thin.

trackable_wow:
  use_when: The idea has a concrete claim or pattern and evidence to monitor, but it is not cleanly binary or date-bound.
  default_status: active_trackable
  required_agent_question: What evidence should I watch next, and when should I review it?
  example: AI data-center power availability is becoming a repeated constraint in hyperscaler commentary.

scoreable_signal:
  use_when: The claim is specific, falsifiable, has an invalidate_test, has a resolve_by date, and has a resolution_source.
  default_status: pending_scoreable
  required_agent_question: What would prove this wrong by the deadline?
  example: By 2026-09-30, at least two hyperscalers will cite power availability as a gating factor for AI capacity growth.

thesis_wow:
  use_when: The idea is a higher-level thesis that can collect child WoWs over time.
  default_status: active_thesis
  example: Stablecoin revenue architecture is shifting from issuer exclusivity to distribution-layer bargaining power.

context_note:
  use_when: The item is useful market context, vocabulary, source quality, or background, but not an investable claim.
  default_status: active_context
  example: A China AI article reframes competition around deployment and manufacturing integration.

status_update:
  use_when: Today's reading changes the CRM state of an existing WoW.
  default_status: none; it updates a target item.
  required_agent_question: Which existing wow_id changed, what was its previous_status, and what allowed new_status now applies?
```

If the agent is unsure between two types, choose the less scoreable type. Do not force a weak idea into `scoreable_signal`.

## User Approval Rule

Private journal drafts may be saved without approval.

Public submission requires user approval, and the daily user decision is the approval.

The agent must not submit a packet publicly to WKAP unless the user selected WoW 1, 2, or 3 with `reason_for_selection`, passed with `reason_for_pass`, or gave an explicit standing instruction to submit after a daily choice.

Default approval flow is assumed: prepare 3 options, collect selection/pass plus reason, generate the packet, save privately, and submit. Do not ask the user how approval should work unless the current agent environment cannot support this flow.

## Public Ledger Bias

The agent's job is to help the user ledger as many eligible market days as possible.

The Private WoW Journal is working memory and training record. WKAP Ledger is the visible workout record.

The agent must not decide that a completed daily choice should stay private. If the user completes selection/pass plus reason, submit the packet. If the user does not reply, save privately as `user_no_reply` and submit nothing.

For WKAP public record purposes, a market day that is not submitted to WKAP Ledger has no public WoW record.

## User No-Reply Rule

If the user does not reply, the agent must save the prepared packet privately and must not submit publicly.

For no-reply days:

```yaml
private_status: user_no_reply
submission_status: not_submitted
receipt_status: no_receipt
public_status: not_public
public_url: null
journal_only: true
```

## Maintenance Workflow

The agent should maintain existing WoWs, not only create new ones.

Before suggesting the 3 daily WoWs, inspect private state and prior public records:

```yaml
tracking_inputs:
  - active-trackables.md
  - pending-scoreables.md
  - thesis-map.md
  - receipts.md
  - public-verification.md
  - prior daily packets
```

Maintenance responsibilities:

```yaml
capabilities:
  - review_due_trackables
  - review_due_scoreable_signals
  - detect_new_evidence_for_existing_wows
  - promote_candidate_to_trackable
  - promote_trackable_to_scoreable
  - connect_child_wows_to_thesis
  - prepare_status_update_items
  - resolve_scoreable_signals_against_resolution_source
  - move_unresolved_to_voided_after_grace_window
  - save_every_prepared_packet_to_private_journal
  - reconcile_receipts_with_public_site_status
```

One of the 3 daily WoW suggestions may be a `status_update` when today's reading is primarily new evidence, a promotion, a resolution, or a maintenance event for an existing WoW.

After public submission, update private lifecycle files to reflect the selected/public packet. Do not mutate old public artifacts.

### Status Update Playbook

When preparing a `status_update`, the agent must do all of the following:

```text
1. Identify the target item in the Private WoW Journal or public WKAP Ledger.
2. Copy its target_wow_type, target_wow_id, target_root_wow_id, and current status.
3. Choose exactly one allowed new_status from the status transition table.
4. Choose update_type that matches the new_status.
5. Add update_summary and evidence_summary in plain language.
6. Include source_refs from today's reading log.
7. Put the status_update in the 3 daily choices if it is one of today's most important investor actions.
8. After public submission, update the local CRM tracking file for the target item with the public packet URL and new status.
```

Use this mapping for common actions:

```yaml
candidate_to_trackable:
  target_wow_type: candidate_wow
  previous_status: active_candidate
  new_status: promoted_trackable
  update_type: promotion
  required_follow_up: create or reference the promoted trackable_wow item

candidate_to_scoreable:
  target_wow_type: candidate_wow
  previous_status: active_candidate
  new_status: promoted_scoreable
  update_type: promotion
  required_follow_up: create or reference the new scoreable_signal child with signal_status pending_scoreable

trackable_to_scoreable:
  target_wow_type: trackable_wow
  previous_status: active_trackable
  new_status: promoted_scoreable
  update_type: promotion
  required_follow_up: create or reference the new scoreable_signal child with signal_status pending_scoreable

scoreable_resolved_correct:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: resolved_correct
  update_type: resolution
  required_fields: resolution_source_used, evidence_summary

scoreable_resolved_incorrect:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: resolved_incorrect
  update_type: resolution
  required_fields: resolution_source_used, evidence_summary

scoreable_unresolved:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable
  new_status: unresolved
  update_type: resolution
  required_fields: evidence_summary

scoreable_invalid_test:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: invalid_test
  update_type: invalid_test
  required_fields: evidence_summary

scoreable_voided:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: voided
  update_type: voided
  required_fields: evidence_summary

trackable_killed:
  target_wow_type: trackable_wow
  previous_status: active_trackable | stale
  new_status: killed
  update_type: killed

candidate_killed:
  target_wow_type: candidate_wow
  previous_status: active_candidate | stale
  new_status: killed
  update_type: killed

thesis_supported_or_weakened:
  target_wow_type: thesis_wow
  previous_status: active_thesis | supported | weakened
  new_status: supported | weakened | retired
  update_type: thesis_update

context_superseded_or_retired:
  target_wow_type: context_note
  previous_status: active_context
  new_status: superseded | retired
  update_type: context_update
```

Do not use `pending_scoreable` as the `new_status` of a promotion update. Promotion updates mark the old candidate or trackable as `promoted_scoreable`; the new child scoreable signal starts with `signal_status: pending_scoreable`.

## Lifecycle Sync Contract

The agent must keep the Private WoW Journal and WKAP Public Ledger in sync.

Every public lifecycle item or status change must reconcile across:

```yaml
lifecycle_sync_required:
  backend_ledger: parsed packet plus LedgerEvent lifecycle logs on WKAP
  private_crm: local Private WoW Journal tracking files
  public_page: WKAP WoW page human view plus agent-readable facts
```

Use stable IDs as the reconciliation keys:

```yaml
sync_keys:
  - packet_id
  - author_id
  - wow_id
  - root_wow_id
  - parent_wow_id
  - target_wow_id
  - target_root_wow_id
  - market_date
```

After a successful public submission, update the local CRM files with the public URL, receipt/public verification status, and any lifecycle transition. A day is not publicly done until it appears on WKAP Ledger.

## Status Update Preparation

Status changes must be append-only.

The agent maintenance loop prepares `status_update` items for resolution, promotion, killed, stale, voided, invalid_test, or other updates.

The agent should prepare unresolved-to-voided `status_update` items after the default 30-day unresolved grace window when a scoreable signal remains unjudgeable.

Status updates reference `target_wow_type`, `target_wow_id`, and `target_root_wow_id`. They are not new market calls and not lineage nodes.

## Agent CRM Status Model

The Private WoW Journal is an agent CRM for investment ideas. The agent must classify and update ideas using this exact state model.

Default initial statuses:

```yaml
default_status:
  candidate_wow: active_candidate
  trackable_wow: active_trackable
  scoreable_signal: pending_scoreable
  thesis_wow: active_thesis
  context_note: active_context
```

Allowed status transitions:

```yaml
allowed_status_transitions:
  candidate_wow:
    active_candidate: [promoted_trackable, promoted_scoreable, killed, stale]
    stale: [active_candidate, killed]
  trackable_wow:
    active_trackable: [promoted_scoreable, killed, stale]
    stale: [active_trackable, killed]
  scoreable_signal:
    pending_scoreable: [resolved_correct, resolved_incorrect, unresolved, invalid_test, voided]
    unresolved: [resolved_correct, resolved_incorrect, invalid_test, voided]
  thesis_wow:
    active_thesis: [supported, weakened, retired]
    supported: [weakened, retired]
    weakened: [supported, retired]
  context_note:
    active_context: [superseded, retired]
```

Status update packet items must include:

```yaml
status_update_required_fields:
  - target_wow_type
  - target_wow_id
  - target_root_wow_id
  - update_type
  - previous_status
  - new_status
  - update_summary
  - evidence_summary
```

The agent must not invent transitions outside the allowed table. If evidence suggests a different lifecycle move, choose the closest allowed transition or keep the idea in its current status.

The local CRM files must store enough information for the next run to reconstruct current state without reading every old packet from scratch:

```yaml
crm_record_minimum_fields:
  - wow_id
  - wow_type
  - root_wow_id
  - current_status
  - latest_public_url
  - latest_packet_id
  - last_reviewed_at
  - next_review_at
  - source_refs
  - status_history
```

## Receipt + Public Site Verification

After attempted submission, the agent should check both:

```text
1. WKAP receipt email.
2. WKAP public site / public ledger.
```

If no receipt exists but the packet is published on WKAP, the agent must treat it as public and record the public URL.

If a receipt exists but the public page cannot be found, the agent should record that mismatch in the Private WoW Journal.

Receipt is useful confirmation, not the sole source of truth.

## Anti-Slop Rules

- Do not force every useful observation into a fake binary test.
- Do not call a trackable a prediction.
- Do not submit publicly without user approval.
- Do not lose no-reply days; save them privately.
- Do not treat private lineage as public proof.
- Do not mutate original public WoW artifacts; prepare append-only updates.
- Do not compute accuracy from non-scoreable items.

## Minimal Daily Output

The agent's minimum daily private output:

```yaml
daily_packet_record:
  local_journal_entry_id: string
  prepared_at: ISO timestamp
  packet_spec_version: string
  skill_version: v0.1
  private_status: prepared_private | user_no_reply | user_rejected | user_approved | no_pick | draft_saved
  submission_status: not_submitted | submitted_to_wkap | submission_failed | unknown
  receipt_status: no_receipt | receipt_received | receipt_error | not_checked
  public_status: not_public | published_on_wkap | public_verified | public_not_found | unknown
  public_url: string | null
  receipt_id: string | null
  packet_id: string | null
```

## Changelog

v0.1 - Initial public draft

- Added canonical Markdown skill file.
- Added daily spec fetch default.
- Added 30-day fallback refresh rule.
- Added distinction between WoW Packet Spec and WKAP WoW Skill.
- Added Private WoW Journal requirement for every prepared Daily WoW Packet.
- Added user no-reply rule: save privately, do not submit publicly.
- Added user approval rule for public submission.
- Added private lineage as context, not public timing proof.
- Added maintenance workflow for status updates.
- Added unresolved-to-voided maintenance rule after grace window.
- Added receipt plus WKAP site verification model.
- Added rule that receipt is useful confirmation, not the sole source of truth.

## Related Resources

Current WoW Packet Spec: https://wkap.ai/specs/wow-packet-latest.md
