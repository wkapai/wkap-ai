---
name: wkap-wow
description: "Use when helping a user run the WKAP Investor Log / Daily WoW workflow: preparing Worth Watching Workout packets, maintaining a private WoW Journal, classifying wow_type lifecycle items, tracking candidate/trackable/scoreable/thesis/status_update records, asking for user approval before public submission, and submitting approved packets to WKAP Ledger."
---

# WKAP WoW

## Source Of Truth

Before preparing or submitting a packet, read:

- https://wkap.ai/skills/wkap-wow-skill-latest.md
- https://wkap.ai/specs/wow-packet-latest.md

Use the latest public spec when it conflicts with bundled references.

## Core Workflow

1. Apply setup defaults first; do not start with a long interview.
2. Maintain the user's private reading log throughout the day.
3. Save every prepared Daily WoW Packet privately, including no-reply, rejected, pass, draft, and submitted days.
4. Classify every WoW item with `wow_type`: `candidate_wow`, `trackable_wow`, `scoreable_signal`, `thesis_wow`, `context_note`, or `status_update`.
5. Track private lifecycle state: candidates, active trackables, pending scoreable signals, thesis children, due reviews, and status updates.
6. Select up to 10 reading items most worth preserving for the current US market day.
7. Suggest exactly 3 WoW signals with `wow_type`, source refs, and lineage/status fields where applicable.
8. Ask the user to choose exactly one: select 1, select 2, select 3, or pass.
9. Ask for the required reason: `reason_for_selection` when selecting, or `reason_for_pass` when passing.
10. If the choice or reason is missing, ask only for the missing field.
11. Once choice plus reason exists, generate the final v0.1 Daily WoW Packet, save it privately, and submit it to WKAP Ledger.
12. After submission, reconcile both WKAP receipt email and WKAP public site / ledger, then update private lifecycle state.

## Low-Friction Setup Defaults

When installing this skill or setting up a recurring WKAP task, use defaults and infer behavior before asking questions.

- Private journal: create or use local Markdown files in `WKAP WoW Journal/` in the active workspace by default. In this repo, that is `C:\Users\ASUS\Documents\wkap\WKAP WoW Journal`.
- If the journal folder or required files are missing, create them before the first prepared packet.
- Agent memory: may be used as a cache, but must not be the only durable journal when local files are available.
- `author_id`: use the known WKAP investor ID if available. If unknown, use a stable local draft identity and do not block setup. Update the mapping after WKAP assigns or confirms a public investor ID.
- Send time: infer the daily send time from the user's behavior pattern after their usual investment research window. Ask only if it cannot be inferred.
- Research sources: default to agent-accessible browser activity, pasted/saved/reviewed items, explicit user requests, and useful agent-found market items.
- Approval: default to collecting the user's selection/pass plus required reason. That daily choice is submission approval. If the user does not reply, save privately as no-reply and submit nothing publicly.

Ask the user only for information that is required and cannot be inferred or safely defaulted.

## Daily Packet Guardrails

- Default scope is one Daily WoW Packet for the current US market day.
- Do not produce a past-7-day summary, weekly review, or general private research memo unless the user explicitly asks for that.
- Recent history may be used as context, but the output must be today's structured Daily WoW Packet.
- A prose list of top private WoWs is not enough. Save and show the full v0.1 packet structure.
- Do not decide to keep a completed daily choice private on the user's behalf.
- No public submission happens without selection/pass plus reason or an explicit standing instruction.

## Strict Daily Workout

- Show exactly 3 WoW signal options, numbered 1-3.
- Require `selected_wow_id` and `reason_for_selection` when the user selects an option.
- Require `selected_wow_id: none`, `reason_for_pass`, `closest_rejected_idea`, and `missing_evidence` when the user passes.
- Do not run a default edit/research/approval loop. If the user asks for edits or more research, complete that request, then return to selection/pass plus reason.
- Selection/pass plus reason is approval to send the Daily WoW Packet to WKAP Ledger.

## Tracking Review

Before suggesting the 3 WoWs, inspect `active-trackables.md`, `pending-scoreables.md`, `thesis-map.md`, `receipts.md`, `public-verification.md`, and prior daily packets.

Use the tracking review to decide whether each daily option is a new `candidate_wow`, `trackable_wow`, `scoreable_signal`, `thesis_wow`, `context_note`, or append-only `status_update`.

After public submission, update the private tracking files. Never mutate old public artifacts.

## Lifecycle Sync Contract

Keep the agent CRM and WKAP Public Ledger synchronized. Every public lifecycle item or status change must reconcile across:

- backend WKAP parse data plus `LedgerEvent` lifecycle logs
- local Private WoW Journal tracking files
- public WKAP WoW page and agent-readable facts

Use stable IDs as the sync keys: `packet_id`, `author_id`, `wow_id`, `root_wow_id`, `parent_wow_id`, `target_wow_id`, `target_root_wow_id`, and `market_date`.

After public submission, update the local CRM files with the public URL, receipt/public verification status, and any lifecycle transition. A day is not publicly done until it appears on WKAP Ledger.

## Codex Local Journal Layout

For this repo, create/use:

```text
C:\Users\ASUS\Documents\wkap\WKAP WoW Journal\
  daily\
  active-trackables.md
  pending-scoreables.md
  thesis-map.md
  receipts.md
  public-verification.md
```

Daily packets go in `daily\YYYY-MM-DD.md`.

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

Send approved packets to `ledger@wkap.ai`.

Use the Markdown + fenced YAML format in `references/daily-packet-template.md`.

The YAML block is the canonical public packet artifact. Keep it valid YAML and include a top-level `packet:` object.

## Reference Files

- For the packet template, read `references/daily-packet-template.md`.
- For private journal structure, read `references/private-journal-template.md`.
- For the v0.1 protocol snapshot, read `references/wow-packet-v0.1.md`.
