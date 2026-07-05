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
