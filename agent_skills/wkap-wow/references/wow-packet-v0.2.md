# WKAP WoW Packet v0.2 Snapshot

Authoritative latest URL:

https://wkap.ai/specs/wow-packet-latest.md

Required `wow_type` values:

- candidate_wow
- trackable_wow
- scoreable_signal
- thesis_wow
- status_update

Only `scoreable_signal` is calibration-scoreable.

Type decision shortcuts:

- `candidate_wow`: early observation, not yet clearly monitorable or scoreable.
- `trackable_wow`: concrete pattern to monitor with evidence/cadence, but not binary.
- `scoreable_signal`: falsifiable claim with `invalidate_test`, `resolve_by`, and `resolution_source`; default `signal_status: pending_scoreable`.
- `thesis_wow`: broader thesis with child WoWs.
- `status_update`: append-only CRM state change for an existing WoW.

Every WoW item must start at least as `candidate_wow`. Broad context belongs in the reading log or Private WoW Journal notes, not as its own WoW type.

Normal WoW items use `parent_wow_id` and `root_wow_id`.

Root WoWs use `parent_wow_id: null` and `root_wow_id: wow_id`.

Status updates are append-only maintenance events. They use `target_wow_type`, `target_wow_id`, `target_root_wow_id`, `previous_status`, and `new_status`, and are not lineage nodes.

Status updates must follow the allowed Agent CRM status transition table in the public skill/spec.

Do not use `pending_scoreable` as `status_update.new_status`. A promotion update marks the old candidate or trackable as `promoted_scoreable`; the new child scoreable starts with `signal_status: pending_scoreable`.

Every public lifecycle item or status update must reconcile across WKAP backend `LedgerEvent` lifecycle logs, the public WoW page/agent facts, and the local Private WoW Journal CRM files.

Private lineage trains the agent. Public lineage proves timing.

Daily workout rule:

1. Select up to 10 reading items.
2. Suggest exactly 3 WoW signals.
3. Any of the 3 suggestions may be a new WoW signal or an append-only `status_update` for an existing WoW signal.
4. User selects 1, 2, 3, or passes.
5. Selection requires `reason_for_selection`.
6. Pass requires `reason_for_pass`, `closest_rejected_wow`, and `missing_evidence`.
7. On pass days, `closest_rejected_wow` must be one of today's suggested `wow_id` values.
8. Selection/pass plus required reason completes the Daily WoW Packet and triggers submission to WKAP Ledger.

Daily suggestion display rule:

- Show exactly 3 numbered options before asking the user to pick.
- Each option must show a visible type label, plain-English title, and why it is worth watching.
- Use visible labels: Candidate, Trackable, Scoreable, Thesis, Status Update.
- Store `wow_id` internally, but do not show it in the default user-facing prompt unless the user asks for technical details.
- For `scoreable_signal`, visibly show `invalidate_test`, `resolve_by`, and `resolution_source`.
- For `status_update`, visibly show the target summary, `previous_status`, `new_status`, and `evidence_summary`.
- The user chooses by number: `Pick one WoW: 1, 2, 3, or pass.`

The agent must remove or summarize private/confidential material and keep sensitive details in the Private WoW Journal.

Agent tracking rule:

- Inspect private journal state before suggestions.
- One daily option may be an append-only `status_update`.
- Update private lifecycle files after public submission.
