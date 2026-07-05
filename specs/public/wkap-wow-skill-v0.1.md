# WKAP WoW Skill v0.1

## Metadata

skill_name: WKAP WoW Skill  
skill_version: v0.1  
skill_url: https://wkap.ai/skills/wkap-wow-skill-v0.1.md  
latest_skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md  
current_wow_packet_spec: https://wkap.ai/specs/wow-packet-latest.md

This Markdown file is the canonical public source of truth for WKAP WoW Skill v0.1.

## Agent Facts

```yaml
agent_facts:
  skill: wkap_wow_skill
  skill_version: v0.1
  current_wow_packet_spec: https://wkap.ai/specs/wow-packet-latest.md
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

The agent must treat the latest spec URL as the current public source of truth for packet shape and protocol rules.

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

## Daily WoW Workout Routine

The daily routine is a workout, not a drafting loop.

The agent must suggest exactly 3 WoW signals. The user must choose one of:

```text
1. select WoW 1
2. select WoW 2
3. select WoW 3
4. pass today
```

Required user fields:

```yaml
selected:
  required:
    - selected_wow_id
    - reason_for_selection
  pass_only_fields:
    closest_rejected_idea: null
    why_pass: null
    missing_evidence: null

passed:
  required:
    - selected_wow_id: none
    - reason_for_pass
    - closest_rejected_idea
    - missing_evidence
```

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

## Status Update Preparation

Status changes must be append-only.

The agent maintenance loop prepares `status_update` items for resolution, promotion, killed, stale, voided, invalid_test, or other updates.

The agent should prepare unresolved-to-voided `status_update` items after the default 30-day unresolved grace window when a scoreable signal remains unjudgeable.

Status updates reference `target_wow_id` and `target_root_wow_id`. They are not new market calls and not lineage nodes.

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
