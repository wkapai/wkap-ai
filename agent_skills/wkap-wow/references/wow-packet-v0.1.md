# WKAP WoW Packet v0.1 Snapshot

Authoritative latest URL:

https://wkap.ai/specs/wow-packet-latest.md

Required `wow_type` values:

- candidate_wow
- trackable_wow
- scoreable_signal
- thesis_wow
- context_note
- status_update

Only `scoreable_signal` is calibration-scoreable.

Normal WoW items use `parent_wow_id` and `root_wow_id`.

Root WoWs use `parent_wow_id: null` and `root_wow_id: wow_id`.

Status updates are append-only maintenance events. They use `target_wow_id` and `target_root_wow_id` and are not lineage nodes.

Private lineage trains the agent. Public lineage proves timing.

Daily workout rule:

1. Select up to 10 reading items.
2. Suggest exactly 3 WoW signals.
3. User selects 1, 2, 3, or passes.
4. Selection requires `reason_for_selection`.
5. Pass requires `reason_for_pass`, `closest_rejected_idea`, and `missing_evidence`.
6. Selection/pass plus required reason is approval to submit to WKAP Ledger.

Agent tracking rule:

- Inspect private journal state before suggestions.
- One daily option may be an append-only `status_update`.
- Update private lifecycle files after public submission.
