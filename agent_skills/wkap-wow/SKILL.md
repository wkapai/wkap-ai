---
name: wkap-wow
description: "Use when helping a user run the WKAP Investor Log / Daily WoW workflow: preparing Worth Watching Workout packets, maintaining a private WoW Journal, classifying wow_type lifecycle items, tracking candidate/trackable/scoreable/thesis/status_update records, collecting the completed daily choice, and submitting completed packets to WKAP Ledger."
---

# WKAP WoW

## Source Of Truth

Before preparing or submitting a packet, read:

- https://wkap.ai/skills/wkap-wow-skill-latest.md
- https://wkap.ai/specs/wow-packet-latest.md
- https://wkap.ai/specs/wow-crm-latest.json
- https://wkap.ai/specs/wow-intake-flow-latest.json
- https://wkap.ai/specs/daily-wow-state-latest.schema.json

Use the latest public JSON specs as the execution contract when they conflict with bundled references or Markdown prose.

If Markdown and JSON specs disagree, follow the JSON execution contract, record the mismatch in the Private WoW Journal, show the mismatch to the user, and include `spec_mismatch_detected` plus mismatch details in the next packet `validation_notes`.

Record both requested latest URLs and resolved versioned URLs for the skill and packet spec. When practical, also record fetched content SHA256 values.

## Strict Intake Program Rule

During user data collection, behave like an intake program, not a free-form advisor. The user may reply in natural language, but you must normalize that reply into the Daily WoW State object, validate it against the intake flow and CRM specs, then ask only for missing required fields.

Do not invent required user fields. Do not pick for the user. Do not decide that a completed valid daily packet should remain private because it is imperfect or low confidence. The normal successful workout result is a published Daily WoW Packet on WKAP Ledger.

The agent must remove or summarize private/confidential material and keep sensitive details in the Private WoW Journal.

The daily choice flow is fixed: prepare exactly 3 options, ask the user to pick 1, 2, 3, or pass, collect `reason_for_selection` for a selected option, collect `closest_rejected_wow`, `reason_for_pass`, and `missing_evidence` for a pass, then save privately and submit publicly. `closest_rejected_wow` must be one of today's 3 `wow_id` values. Selection/pass plus required fields completes the Daily WoW Packet; do not ask for a second confirmation unless the user explicitly interrupts submission.

## Core Workflow

1. Apply setup defaults first; do not start with a long interview.
2. Maintain the user's private reading log throughout the day.
3. Save every prepared Daily WoW Packet privately, including no-reply, rejected, pass, draft, and submitted days.
4. Classify every WoW item with `wow_type`: `candidate_wow`, `trackable_wow`, `scoreable_signal`, `thesis_wow`, or `status_update`.
5. Track private lifecycle state: candidates, active trackables, pending scoreable signals, thesis children, due reviews, and status updates.
6. Select up to 10 reading items most worth preserving for the resolved US trading date.
7. Suggest exactly 3 WoW signals with `wow_type`, source refs, and lineage/status fields where applicable.
8. Ask the user to choose exactly one: select 1, select 2, select 3, or pass.
9. Ask for the required reason: `reason_for_selection` when selecting, or `reason_for_pass` when passing.
10. If the choice or reason is missing, ask only for the missing field.
11. Once choice plus reason exists, generate the final v0.2 Daily WoW Packet, save it privately, and submit it to WKAP Ledger.
12. After submission, reconcile both WKAP receipt email and WKAP public site / ledger, then update private lifecycle state.

## Low-Friction Setup Defaults

When installing this skill or setting up a recurring WKAP task, use defaults and infer behavior before asking questions.

- Private journal: create or use local Markdown files in `WKAP WoW Journal/` in the active workspace by default. If no writable workspace exists, use the nearest user-owned durable Markdown store and tell the user where it is.
- If the journal folder or required files are missing, create them before the first prepared packet.
- Agent memory: may be used as a cache, but must not be the only durable journal when local files are available.
- `investor_id`: use the known WKAP investor ID if available. If unknown, use a stable local draft identity and do not block setup. Update the mapping after WKAP assigns or confirms a public investor ID.
- Send time: if autonomous scheduling is available, infer the daily send time from the user's behavior pattern after their usual investment research window. If autonomous scheduling is not available, run when the user says `daily WoW` or at the start of the first agent session on a US market day when recent research context is available.
- Scheduling setup: during setup, if Codex scheduled automations or an equivalent autonomous scheduler are available, create or update an active recurring automation named `WKAP Daily WoW` for the active workspace. Each scheduled run must invoke this installed skill and the latest specs it references.
- Setup report: after setup, tell the user whether scheduling was created, updated, unavailable, or skipped. Include install verification, journal path, schedule summary, and fallback trigger.
- Research sources: default to agent-accessible browser activity, pasted/saved/reviewed items, explicit user requests, and useful agent-found market items.
- Completion: default to collecting the user's selection/pass plus required reason. That daily choice completes the Daily WoW Packet. If the user does not reply, save privately as no-reply and submit nothing publicly.

Ask the user only for information that is required and cannot be inferred or safely defaulted.

## Daily Packet Guardrails

- Default scope is one Daily WoW Packet for the resolved US trading date.
- Resolve `market_date` in `America/New_York`: use the current US trading date at prepare time; before the next US trading session opens, use the most recent US trading date unless the user asks for the next session; weekend or US holiday research rolls into the next US trading date unless the user asks for a catch-up packet.
- Do not produce a past-7-day summary, weekly review, or general private research memo unless the user explicitly asks for that.
- Recent history may be used as context, but the output must be today's structured Daily WoW Packet.
- A prose list of top private WoWs is not enough. Save and show the full v0.2 packet structure.
- Do not decide to keep a completed daily choice private on the user's behalf.
- No public submission happens without selection/pass plus reason or an explicit standing instruction.

## Strict Daily Workout

- Show exactly 3 WoW signal options, numbered 1-3.
- Show a fast lightweight choice slate first. Do not generate the full structured Daily WoW Packet before the user has selected 1, 2, 3, or pass.
- The first user-facing slate should be concise and should target under 10 seconds whenever recent reading context is already available.
- Hard latency limit: if the agent cannot serve the first 3-option slate within 30 seconds, it must show the best available slate from current evidence and mark deeper research as pending; do not block the user's daily choice on full packet generation or extra research.
- Do not force a fixed type mix. The 3 options must be the highest-value choices for today's evidence and CRM state, not one item from each `wow_type`; repeated types are valid when they are the best choices.
- Any of the 3 options may be a new WoW signal or an append-only `status_update` for an existing WoW signal when today's reading provides new evidence, an evidence-only update, a promotion, a resolution, or a maintenance event.
- Require `selected_wow_id` and `reason_for_selection` when the user selects an option.
- Require `selected_wow_id` to be the literal string `"none"`, plus `reason_for_pass`, `closest_rejected_wow`, and `missing_evidence`, when the user passes.
- For a pass, `closest_rejected_wow` must be the `wow_id` of one of today's 3 suggested WoW signals, not a free-text rejected idea.
- Do not run a default edit/research/confirmation loop. If the user asks for edits or more research, complete that request, then return to selection/pass plus reason.
- Selection/pass plus reason completes the Daily WoW Packet and triggers submission to WKAP Ledger. After the user gives the completed choice/pass response, immediately acknowledge that the choice is accepted, then save, submit, and reconcile asynchronously; the user should not need to wait for packet generation, ledger send, receipt reconciliation, or public URL verification.

## Fast Choice Slate Rule

The agent must separate the user-facing choice slate from the final ledger packet.

Before user judgment, generate only a lightweight `DailyWoWChoiceSlate`:

```yaml
choice_slate:
  market_date: YYYY-MM-DD
  options:
    - option_number: 1
      visible_type_label: trackable | scoreable | thesis | status update | candidate
      plain_english_title: short title
      why_worth_watching: one or two sentences
      evidence_to_watch: concise evidence list
    - option_number: 2
    - option_number: 3
  prompt: "Pick one WoW: 1, 2, 3, or pass."
```

Do not build, print, or validate the full packet YAML before the user has made a selection/pass and provided the required reason. Keep reading-log selection, source refs, `wow_id`, lineage, and CRM state internally while showing only the slate. The slate must be served within 30 seconds; if deeper research is still running, show the best current slate and continue enrichment only after the user choice is collected. After choice plus reason exists, generate the final v0.2 Daily WoW Packet, save it privately, submit it publicly, and reconcile asynchronously without making the user wait.

The slate is not a template slot exercise. Do not choose one Trackable, one Scoreable, and one Thesis just to make the surface look balanced. Rank all candidate, trackable, scoreable, thesis, and status-update opportunities together, then show the best three.

## Daily Suggestion Display Contract

Before asking the user to pick 1, 2, 3, or pass, show exactly 3 numbered options.

Each visible option must include:

```yaml
required_visible_fields:
  - option_number
  - visible_type_label
  - plain_english_title
  - why_worth_watching
```

Use these visible labels for internal `wow_type` values:

```yaml
candidate_wow: Candidate
trackable_wow: Trackable
scoreable_signal: Scoreable
thesis_wow: Thesis
status_update: Status Update
```

The user chooses by number only:

```text
Pick one WoW: 1, 2, 3, or pass.
```

Store `wow_id` internally in the structured packet, but do not show `wow_id` in the default user-facing choice prompt unless the user asks for technical details.

For `scoreable_signal`, the visible option must also show `invalidate_test`, `resolve_by`, and `resolution_source`.

For `trackable_wow`, show `evidence_to_watch` and review timing when concise.

For `status_update`, show the target summary, `previous_status`, `new_status`, and `evidence_summary`.

Before showing the 3 options, validate:

```yaml
invalid_if:
  - fewer_or_more_than_3_options
  - any_option_missing_visible_type_label
  - any_option_missing_plain_english_title
  - any_option_missing_why_worth_watching
  - scoreable_signal_missing_invalidate_test
  - scoreable_signal_missing_resolve_by
  - scoreable_signal_missing_resolution_source
  - user_is_required_to_choose_by_wow_id
```

## WoW Type Decision Rules

- Use `candidate_wow` for an early observation worth preserving when evidence, cadence, or test is not clear yet.
- Use `trackable_wow` for a concrete claim or pattern with evidence to monitor and a review cadence, but no clean binary resolution.
- Use `scoreable_signal` only when the claim has `invalidate_test`, `resolve_by`, and `resolution_source`; default `signal_status` is `pending_scoreable`.
- Use `thesis_wow` for a broader thesis that can collect child WoWs over time.
- Use `candidate_wow` as the minimum type for any public or private WoW item. If something is only broad context, keep it in the reading log or Private WoW Journal notes instead of making it a WoW item.
- Use `status_update` when today's reading changes the CRM state of an existing WoW or adds evidence without changing state.
- If unsure, choose the less scoreable type. Do not force weak ideas into `scoreable_signal`.

## Tracking Review

Before suggesting the 3 WoWs, inspect `active-trackables.md`, `pending-scoreables.md`, `thesis-map.md`, `receipts.md`, `public-verification.md`, and prior daily packets.

Use the tracking review to decide whether each daily option is a new `candidate_wow`, `trackable_wow`, `scoreable_signal`, `thesis_wow`, or append-only `status_update`.

Use the exact Agent CRM status model from the public skill/spec. Every `status_update` must include `target_wow_type`, `target_wow_id`, `target_root_wow_id`, `update_type`, `previous_status`, and `new_status`, and the transition must be allowed by the status table.

After public submission, update the private tracking files. Never mutate old public artifacts.

## Agent CRM Operating Loop

1. Load today's reading candidates.
2. Load active CRM state from the local Private WoW Journal.
3. Decide whether today's evidence creates a new WoW or changes an existing WoW.
4. Express existing-item changes as append-only `status_update` items.
5. Pick the 3 highest-value options for the user's daily choice.
6. After submission, update local CRM files from the submitted packet plus public WKAP URL.

Status update playbook:

- `candidate_wow active_candidate -> promoted_trackable`: use `update_type: promotion`; create/reference the promoted trackable.
- `candidate_wow active_candidate -> promoted_scoreable`: use `update_type: promotion`; create/reference a child `scoreable_signal` with `signal_status: pending_scoreable`.
- `trackable_wow active_trackable -> promoted_scoreable`: use `update_type: promotion`; create/reference a child `scoreable_signal` with `signal_status: pending_scoreable`.
- `scoreable_signal pending_scoreable -> pending_scoreable | resolved_correct | resolved_incorrect | unresolved | invalid_test | voided`: use `update_type: evidence` for same-status evidence updates, otherwise use the matching `update_type` and include evidence.
- `scoreable_signal unresolved -> resolved_correct | resolved_incorrect | invalid_test | unresolved | voided`: use `update_type: evidence` for same-status evidence updates, otherwise use the matching `update_type` and include evidence.
- `candidate_wow`, `trackable_wow`, or `thesis_wow` same-status evidence update: use `update_type: evidence`, set `new_status` equal to `previous_status`, and include `evidence_summary`.
- `candidate_wow` or `trackable_wow -> killed | stale`: use `update_type: killed` or `stale`.
- `thesis_wow -> supported | weakened | retired`: use `update_type: thesis_update` only when the status changes; use `update_type: evidence` when the thesis remains in the same status.

Do not use `pending_scoreable` as a `status_update.new_status`. A promotion update marks the old item as `promoted_scoreable`; the new child scoreable starts with `signal_status: pending_scoreable`.

Same-status updates must use `update_type: evidence`. `update_type: evidence` must not change status.

Use `stale` for a candidate or trackable only when it has passed `next_review_at` or missed two expected review cycles without material confirming evidence, and today's review finds it no longer merits active monitoring.

## Lifecycle Sync Contract

Keep the agent CRM and WKAP Public Ledger synchronized. Every public lifecycle item or status change must reconcile across:

- backend WKAP parse data plus `LedgerEvent` lifecycle logs
- local Private WoW Journal tracking files
- public WKAP WoW page and agent-readable facts

Use stable IDs as the sync keys: `packet_id`, `investor_id`, `wow_id`, `root_wow_id`, `parent_wow_id`, `target_wow_id`, `target_root_wow_id`, and `market_date`.

After public submission, update the local CRM files with the public URL, receipt/public verification status, and any lifecycle transition. A day is not publicly done until it appears on WKAP Ledger.

## Codex Journal Layout

For Codex workspaces with filesystem access, create/use this workspace-relative layout:

```text
<active-workspace>/WKAP WoW Journal/
  daily/
  active-trackables.md
  pending-scoreables.md
  thesis-map.md
  receipts.md
  public-verification.md
```

Daily packets go in `daily/YYYY-MM-DD.md`.

After setup, tell the user the journal path and whether the local files were created or already existed.

## Private Engine Rules

- Treat the Private WoW Journal as the working memory and training record.
- Treat WKAP Ledger as the visible workout record. The normal successful daily outcome is public ledger submission.
- Preserve private lineage, but never count private lineage as public timing proof.
- Public proof starts at the earliest publicly ledgered ancestor.
- Prepare `status_update` items for resolution, promotion, killed, stale, voided, invalid_test, or other maintenance events.
- Move unresolved scoreable signals toward `voided` after the spec grace window when they remain unjudgeable.
- Never mutate old public WoW artifacts; create append-only updates.

## Public Submission Rules

Send completed packets to `ledger@wkap.ai`.

Use the subject convention:

```text
Daily WoW Packet - {market_date} - {investor_id_or_agent_label}
```

Use Markdown with one fenced YAML block in the email body. The packet template is available at `https://wkap.ai/skills/wkap-wow-codex/references/daily-packet-template.md`. If that reference is unavailable, use `https://wkap.ai/specs/wow-packet-latest.md`.

The YAML block is the canonical public packet artifact. Keep it valid YAML and include a top-level `packet:` object.

Attachments are optional and non-canonical unless a later public spec defines them. Reconcile both the WKAP receipt email and public WKAP URL after sending.

## Reference Files

- Packet template: `https://wkap.ai/skills/wkap-wow-codex/references/daily-packet-template.md`.
- Private journal structure: `https://wkap.ai/skills/wkap-wow-codex/references/private-journal-template.md`.
- v0.2 protocol snapshot: `https://wkap.ai/skills/wkap-wow-codex/references/wow-packet-v0.2.md`.
- If these Codex reference URLs are unavailable, fall back to `https://wkap.ai/specs/wow-packet-latest.md`, `https://wkap.ai/specs/wow-crm-latest.json`, `https://wkap.ai/specs/wow-intake-flow-latest.json`, and `https://wkap.ai/specs/daily-wow-state-latest.schema.json`.
