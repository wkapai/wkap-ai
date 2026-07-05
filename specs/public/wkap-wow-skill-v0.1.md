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
  setup_mode: low_friction_defaults_first
  ask_user_only_when_blocked: true
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
  private_journal_location: use a durable user-owned Markdown folder in the active workspace or documents area
  author_id: use known WKAP investor ID if available; otherwise use a stable local draft identity until public ledger identity is assigned or confirmed
  daily_send_time: infer from the user's behavior pattern after daily investment research; ask only if it cannot be inferred
  research_sources: agent-accessible browser activity, pasted/saved/reviewed items, explicit user requests, and high-quality agent-found market items
  approval_flow: prepare packet, show user, wait for approval; no reply means save privately and submit nothing publicly
```

The agent may briefly confirm the setup after applying defaults, but it should not block installation on questions about journal location, author ID, schedule, source list, or approval flow unless those defaults are impossible to apply.

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

Recommended v0.1 storage is user-owned Markdown storage.

Use a durable default location first. Prefer a `WKAP WoW Journal/` folder in the active workspace, project folder, or user documents area. Ask the user for a path only if no durable writable location is available or the user wants to change it.

Example:

```text
/WKAP/WoW Journal/
  2026-07-05.md
  active-trackables.md
  pending-scoreables.md
  receipts.md
  public-verification.md
```

Pure agent memory can be a cache, but it should not be the only durable journal if avoidable.

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
4. Generate candidate WoWs.
5. Classify each item by wow_type.
6. Rank candidates.
7. Save the prepared packet to the Private WoW Journal.
8. Show the prepared packet and ask the user to approve one, pass, edit, or request more research.
9. If approved, build the final packet and submit to WKAP.
10. If not approved or no reply, keep it private.
11. Reconcile receipt and public site status after attempted submission.
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

Public submission requires user approval.

The agent must not submit a packet publicly to WKAP unless the user approved submission or gave an explicit standing instruction to submit.

Default approval flow is assumed: prepare privately, present the packet to the user, wait for approval, and submit only after approval. Do not ask the user how approval should work unless the current agent environment cannot support this flow.

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

Maintenance responsibilities:

```yaml
capabilities:
  - review_due_trackables
  - prepare_status_update_items
  - resolve_scoreable_signals_against_resolution_source
  - move_unresolved_to_voided_after_grace_window
  - save_every_prepared_packet_to_private_journal
  - reconcile_receipts_with_public_site_status
```

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
