# WKAP WoW Packet Spec v0.1

## Metadata

spec_name: WKAP WoW Packet Spec  
spec_version: v0.1  
spec_url: https://wkap.ai/specs/wow-packet-v0.1.md  
latest_spec_url: https://wkap.ai/specs/wow-packet-latest.md  
recommended_agent_skill: https://wkap.ai/skills/wkap-wow-skill-latest.md
crm_spec: https://wkap.ai/specs/wow-crm-latest.json
intake_flow: https://wkap.ai/specs/wow-intake-flow-latest.json
daily_state_schema: https://wkap.ai/specs/daily-wow-state-latest.schema.json

This Markdown file is the canonical public source of truth for WKAP WoW Packet v0.1.

The machine-readable CRM, intake flow, and daily state JSON specs define the strict agent execution contract for data collection, required fields, and lifecycle transitions:

- https://wkap.ai/specs/wow-crm-latest.json
- https://wkap.ai/specs/wow-intake-flow-latest.json
- https://wkap.ai/specs/daily-wow-state-latest.schema.json

## Agent Facts

```yaml
agent_facts:
  protocol: wkap_wow_packet
  spec_version: v0.1
  required_identity_field: author_id
  valid_wow_types:
    - candidate_wow
    - trackable_wow
    - scoreable_signal
    - thesis_wow
    - context_note
    - status_update
  unresolved_grace_window_days: 30
```

## Purpose

A WoW Packet is a Worth Watching Workout artifact. It records market attention, sources, candidate observations, claims, trackable items, scoreable signals, thesis notes, context, human judgment, and append-only updates.

Agent prepares. User judges. Private Journal preserves the workout trail. WKAP Ledger records what became public.

## Required Packet Fields

Minimum public packet skeleton:

```yaml
packet:
  packet_id: string
  author_id: string
  created_at: ISO timestamp
  packet_spec_version: v0.1
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.1.md
  packet_spec_latest_url: https://wkap.ai/specs/wow-packet-latest.md
  skill_version: string | null
  skill_url: string | null
  human_view:
    title: string
    summary: string
    top_wows: list
  agent_facts:
    packet_id: string
    author_id: string
    packet_spec_version: string
    wow_count: integer
    scoreable_count: integer
    trackable_count: integer
    thesis_count: integer
    candidate_count: integer
    status_update_count: integer
  reading_log: list
  wow_items: list
  selection:
    selected_wow_id: string | none
    reason_for_selection: string | null
    reason_for_pass: string | null
    closest_rejected_wow: string | null
    missing_evidence: string | null
  validation_notes:
    schema_valid: boolean
    missing_fields: list
    warnings: list
```

Persistent identity is required. No persistent identity, no durable calibration record.

## Daily Workout Contract

A Daily WoW Packet represents one market-day workout.

The packet must include:

```yaml
daily_workout_contract:
  reading_log_max_items: 10
  suggested_wow_count: 3
  user_decision:
    - select_1
    - select_2
    - select_3
    - pass
  selection_requires:
    - selected_wow_id
    - reason_for_selection
  pass_requires:
    - selected_wow_id: none
    - reason_for_pass
    - closest_rejected_wow
    - missing_evidence
```

The agent prepares the options. The user performs the judgment by selecting one of the 3 WoW signals or passing. User selection/pass plus the required reason is approval to submit the packet to WKAP Ledger.

Any of the 3 daily options may be a new WoW signal or an append-only `status_update` for an existing WoW signal when today's reading provides new evidence, a promotion, a resolution, or a maintenance event.

When the user passes, `closest_rejected_wow` MUST be the `wow_id` of one of today's 3 suggested WoW signals. It is not a free-text idea field; put the idea text inside the suggested WoW item.

If the user does not provide a choice or required reason, the packet is incomplete for public submission. Save it privately as no-reply or incomplete, and ask only for the missing required field.

## Agent Tracking Workflow

Before finalizing the 3 daily WoW signals, the agent should inspect private journal state:

```yaml
tracking_inputs:
  - active-trackables.md
  - pending-scoreables.md
  - thesis-map.md
  - receipts.md
  - public-verification.md
  - prior daily packets
```

The 3 suggested WoW signals may include new observations, trackables, scoreable signals, thesis children, context notes, or append-only status updates on prior WoWs.

After public submission, the agent should update private lifecycle state. Public artifacts remain immutable.

The Private WoW Journal acts as the agent CRM for investment ideas. Agents should be able to reconstruct the current state of each idea from CRM files plus public WKAP pages.

Daily CRM loop:

```text
1. Load today's top reading candidates.
2. Load active CRM state: candidates, trackables, scoreable signals, theses, context notes, receipts, and public verification.
3. Decide whether today's evidence creates a new WoW or changes an existing WoW.
4. Classify new items with the WoW type decision rules.
5. Express existing-item changes as append-only status_update items.
6. Present exactly 3 daily choices to the user.
7. After the user selects or passes, submit the packet and update private CRM records from the public URL.
```

## Valid WoW Types

Every WoW item must declare `wow_type`.

```yaml
valid_wow_types:
  - candidate_wow
  - trackable_wow
  - scoreable_signal
  - thesis_wow
  - context_note
  - status_update
```

`candidate_wow` is an early observation.  
`trackable_wow` is a claim or pattern worth monitoring but not ready for binary scoring.  
`scoreable_signal` is a falsifiable claim with a declared invalidation test and resolution date.  
`thesis_wow` is a broader thesis supported by child WoWs.  
`context_note` is background context and must not be treated as a market call.  
`status_update` is an append-only maintenance item for an existing WoW.

## WoW Type Decision Rules

```yaml
candidate_wow:
  use_when: Early observation worth saving, but monitorable evidence, review cadence, or falsifiable test is not clear yet.
  default_status: active_candidate
  scoreable: false

trackable_wow:
  use_when: Concrete claim or pattern worth monitoring, with evidence_to_watch and next_review_at, but not cleanly binary.
  default_status: active_trackable
  scoreable: false

scoreable_signal:
  use_when: Specific falsifiable claim with invalidate_test, resolve_by, and resolution_source.
  default_status: pending_scoreable
  scoreable: true

thesis_wow:
  use_when: Higher-level thesis that can collect child WoWs over time.
  default_status: active_thesis
  scoreable: false

context_note:
  use_when: Useful background context, source quality note, vocabulary, or framing that is not an investable claim.
  default_status: active_context
  scoreable: false

status_update:
  use_when: Today's reading changes the CRM state of an existing WoW.
  required_target_fields:
    - target_wow_type
    - target_wow_id
    - target_root_wow_id
    - previous_status
    - new_status
  scoreable: false
```

If an item is not clearly scoreable, do not force it into `scoreable_signal`.

## Type-Level Requirements

```yaml
candidate_wow:
  wow_type: candidate_wow
  observation: string
  why_worth_watching: string
  source_refs: list
  created_at: ISO timestamp
  scoreable: false
  parent_wow_id: string | null
  root_wow_id: string

trackable_wow:
  wow_type: trackable_wow
  claim: string
  evidence_to_watch: list
  review_cadence: string
  next_review_at: ISO date
  trackable_status: active
  source_refs: list
  created_at: ISO timestamp
  scoreable: false
  parent_wow_id: string | null
  root_wow_id: string

scoreable_signal:
  wow_type: scoreable_signal
  claim: string
  invalidate_test: string
  resolve_by: ISO date
  resolution_source: string
  signal_status: pending_scoreable
  source_refs: list
  created_at: ISO timestamp
  scoreable: true
  parent_wow_id: string | null
  root_wow_id: string

thesis_wow:
  wow_type: thesis_wow
  thesis_claim: string
  key_subclaims: list
  evidence_to_watch: list
  review_cadence: string
  next_review_at: ISO date
  source_refs: list
  created_at: ISO timestamp
  scoreable: false
  parent_wow_id: string | null
  root_wow_id: string

context_note:
  wow_type: context_note
  summary: string
  source_refs: list
  created_at: ISO timestamp
  scoreable: false
  parent_wow_id: string | null
  root_wow_id: string
```

## Scoreability Rule

Not every WoW is scoreable. Only `scoreable_signal` earns calibration credit.

Non-scoreable WoWs can be valuable as attention, context, thesis, lineage, or maintenance artifacts. They do not count toward accuracy or calibration records.

```yaml
scoreable_signal:
  scoreable: true
  accuracy_endpoint_eligible: true

candidate_wow:
  scoreable: false
  accuracy_endpoint_eligible: false

trackable_wow:
  scoreable: false
  accuracy_endpoint_eligible: false

thesis_wow:
  scoreable: false
  accuracy_endpoint_eligible: false

context_note:
  scoreable: false
  accuracy_endpoint_eligible: false

status_update:
  scoreable: false
  accuracy_endpoint_eligible: false
```

## Trackable Review Rule

Trackables are not right/wrong scored, but they are discipline-scored.

Trackable statuses:

```yaml
trackable_status:
  - active
  - promoted
  - killed
  - stale
```

A trackable must eventually become promoted, killed, or stale. A trackable that never promotes, dies, or receives timely reviews becomes visible dead weight in the ledger.

## Signal Resolution Statuses

```yaml
signal_status:
  - pending_scoreable
  - resolved_correct
  - resolved_incorrect
  - unresolved
  - invalid_test
  - voided
```

`pending_scoreable` means the resolution date or event has not arrived.
`resolved_correct` means the claim resolved in favor of the author under the declared test.  
`resolved_incorrect` means the claim was invalidated under the declared test.  
`unresolved` means the resolve date arrived, but available evidence is not sufficient to judge. It is pending-past-due, not neutral, and it is not terminal.  
`invalid_test` means the original test was malformed, vague, circular, or non-binding at submission time.  
`voided` means the original test was reasonable, but later became unmeasurable or non-binding due to changed external conditions.

Default grace window:

```yaml
unresolved_grace_window_days: 30
pending_statuses:
  - pending_scoreable
  - unresolved
```

## Status-to-Record Mapping

```yaml
signal_status_record_mapping:
  resolved_correct:
    accuracy_record: counts
    discipline_record: counts
  resolved_incorrect:
    accuracy_record: counts
    discipline_record: counts
  voided:
    accuracy_record: neutral
    discipline_record: visible
  invalid_test:
    accuracy_record: excluded
    discipline_record: penalty
  unresolved:
    accuracy_record: pending
    discipline_record: visible
```

`invalid_test` is a discipline penalty, not a mulligan.  
`voided` is calibration-neutral but visible.  
`unresolved` is pending-past-due, not accuracy-neutral, and cannot live forever.

## Resolution Authority

For v0.1, resolution status is author-declared against the stated `resolution_source`.

Author-declared resolution must cite or summarize the declared resolution source when available. WKAP verification and adjudication are deferred.

## v0.1 Status Updates and Transitions

Status changes are append-only. A `status_update` is a later packet item, not a mutation of the original WoW artifact.

```yaml
status_update:
  wow_type: status_update
  wow_id: string
  target_wow_type: candidate_wow | trackable_wow | scoreable_signal | thesis_wow | context_note
  target_wow_id: string
  target_root_wow_id: string
  update_type: resolution | promotion | killed | stale | voided | invalid_test | thesis_update | context_update | other
  previous_status: string
  new_status: string
  created_at: ISO timestamp
  author_id: string
  source_refs: list
  update_summary: string
  scoreable: false
  accuracy_endpoint_eligible: false
  lineage_node: false
```

For resolution updates:

```yaml
required_fields:
  - signal_status
  - resolution_source_used
  - evidence_summary
```

For lifecycle updates:

```yaml
required_fields:
  - trackable_status
  - evidence_summary
```

Original WoW artifacts remain immutable. Current state is derived from the original WoW plus later update items.

Every public `status_update` must be machine-reconcilable across WKAP backend logs, the public WoW page, and the user's Private WoW Journal.

WKAP stores parsed lifecycle items in packet JSON and writes backend `LedgerEvent` lifecycle logs. Agents should mirror the same transition in local CRM files after public verification.

## Agent CRM Status Model

Agents should maintain Private WoW Journal CRM files using the same status model exposed on WKAP pages.

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
    active_candidate:
      - promoted_trackable
      - promoted_scoreable
      - killed
      - stale
    stale:
      - active_candidate
      - killed
  trackable_wow:
    active_trackable:
      - promoted_scoreable
      - killed
      - stale
    stale:
      - active_trackable
      - killed
  scoreable_signal:
    pending_scoreable:
      - resolved_correct
      - resolved_incorrect
      - unresolved
      - invalid_test
      - voided
    unresolved:
      - resolved_correct
      - resolved_incorrect
      - invalid_test
      - voided
  thesis_wow:
    active_thesis:
      - supported
      - weakened
      - retired
    supported:
      - weakened
      - retired
    weakened:
      - supported
      - retired
  context_note:
    active_context:
      - superseded
      - retired
```

Every `status_update` MUST include `target_wow_type`, `previous_status`, `new_status`, `target_wow_id`, and `target_root_wow_id`. Agents must reject or repair packets that attempt a status transition outside this table.

Status update playbook:

```yaml
candidate_to_trackable:
  target_wow_type: candidate_wow
  previous_status: active_candidate
  new_status: promoted_trackable
  update_type: promotion

candidate_to_scoreable:
  target_wow_type: candidate_wow
  previous_status: active_candidate
  new_status: promoted_scoreable
  update_type: promotion
  note: The new child scoreable_signal starts separately with signal_status pending_scoreable.

trackable_to_scoreable:
  target_wow_type: trackable_wow
  previous_status: active_trackable
  new_status: promoted_scoreable
  update_type: promotion
  note: The new child scoreable_signal starts separately with signal_status pending_scoreable.

scoreable_resolved_correct:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: resolved_correct
  update_type: resolution

scoreable_resolved_incorrect:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: resolved_incorrect
  update_type: resolution

scoreable_unresolved:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable
  new_status: unresolved
  update_type: resolution

scoreable_invalid_test:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: invalid_test
  update_type: invalid_test

scoreable_voided:
  target_wow_type: scoreable_signal
  previous_status: pending_scoreable | unresolved
  new_status: voided
  update_type: voided
```

Do not use `pending_scoreable` as the `new_status` of a status update. A promotion status update marks the prior candidate or trackable as `promoted_scoreable`; the new scoreable child item carries `signal_status: pending_scoreable`.

## Status Update Authority

In v0.1, a `status_update` is valid only if its `author_id` matches the target WoW author_id.

Third-party status updates, third-party annotations, and WKAP adjudication are deferred.

## Status Update Lineage Exemption

`status_update` items are exempt from `parent_wow_id` and `root_wow_id` requirements.

They must use `target_wow_id` and `target_root_wow_id`.

A `status_update` is not a lineage node.

## Lineage Rule

Normal WoW items must include:

```yaml
parent_wow_id: string | null
root_wow_id: string
```

Root rule:

```text
If parent_wow_id is null, root_wow_id must equal wow_id.
```

Child rule:

```text
If parent_wow_id is not null, root_wow_id should equal the root_wow_id of the parent lineage when the parent is publicly known.
```

Do not require `lineage_depth` or `transition_reason` in v0.1.

## Public Lineage Proof Rule

Private journal lineage is context, not public proof.

A public WoW may reference a private `parent_wow_id` from the user's Private WoW Journal, but public lineage proof weight starts at the earliest publicly ledgered ancestor.

Private noticed is not public proof. Private lineage trains the agent. Public lineage proves timing.

## Agent Facts Rule

Minimum item-level facts for normal WoW items:

```yaml
agent_facts:
  wow_id: string
  wow_type: candidate_wow | trackable_wow | scoreable_signal | thesis_wow | context_note
  scoreable: boolean
  accuracy_endpoint_eligible: boolean
  parent_wow_id: string | null
  root_wow_id: string
  created_at: ISO timestamp
  source_refs: list
```

For `scoreable_signal`, include `claim`, `invalidate_test`, `resolve_by`, and `resolution_source`.

For `trackable_wow`, include `claim`, `evidence_to_watch`, `review_cadence`, `next_review_at`, and `trackable_status`.

For `status_update`, include `lineage_node: false`, `target_wow_id`, `target_root_wow_id`, `update_type`, `previous_status`, and `new_status`.

## Public Status / Receipt Role

Receipt is useful confirmation, not the sole source of truth.

If a packet is published on `wkap.ai`, it is public even if the receipt email was missed.

Agents should reconcile public status using both WKAP receipt email and WKAP public site / ledger checks.

## Minimal Packet Skeleton

```yaml
packet:
  packet_id: string
  author_id: string
  market_date: ISO date
  created_at: ISO timestamp
  reading_log:
    - item_number: integer
      source_title: string
      source_url: string | null
      source_type: string
      tickers: list
      themes: list
      reading_origin: user_browsed | agent_suggested
      agent_summary: string
  wow_items:
    - wow_id: string
      wow_type: string
      scoreable: boolean
      source_refs: list
      agent_facts: object
  selection:
    selected_wow_id: string | none
    reason_for_selection: string | null
    reason_for_pass: string | null
    closest_rejected_wow: string | null
    missing_evidence: string | null
```

Private journal state fields do not need to be included in public packets unless explicitly submitted as part of a public artifact.

## Future-Proofing / Version-Aware Storage Note

Future packet formats will change.

The database should not store the current WoW format as if it were permanent. It should store historical WoW artifacts produced under known spec versions.

Recommended future storage model:

```text
1. Store raw artifact immutably.
2. Store packet_spec_version and packet_spec_url on every packet.
3. Extract only stable indexing fields into normal columns.
4. Store evolving packet/item payloads in JSON or JSONB.
5. Validate, render, and score packets based on the spec_version used at submission time.
6. Never destructively migrate old packets just because a new spec is released.
7. Derive current WoW state from original item plus subsequent status_update items.
8. Derive public status from WKAP publication records, receipts, and site verification.
9. Treat private journal lineage as context unless publicly ledgered.
```

A packet submitted under `wow-packet-v0.1` remains a v0.1 packet forever.

## Changelog

v0.1 - Initial public draft

- Added canonical Markdown source-of-truth files.
- Added 302 latest-to-versioned redirect model.
- Added required `author_id`.
- Added WoW type taxonomy.
- Added `status_update` as a valid non-scoreable `wow_type`.
- Added `scoreable_signal` requirements.
- Added trackable review semantics.
- Added signal status `voided`.
- Added status-to-record mapping.
- Fixed `unresolved` as pending, not accuracy-neutral.
- Added `invalid_test` discipline penalty rule.
- Added unresolved grace window rule.
- Added v0.1 resolution authority: author-declared against `resolution_source`.
- Added v0.1 status updates as subsequent packet items referencing `target_wow_id`.
- Added status update authority: `author_id` must match target WoW `author_id`.
- Added status update lineage exemption.
- Added append-only state model.
- Added minimal lineage fields: `parent_wow_id` and `root_wow_id`.
- Added root lineage rule.
- Added public lineage proof rule.
- Added private journal lineage as context, not public proof.
- Added agent facts requirements.
- Added future-proofing note for version-aware flexible storage.
- Excluded fake hash fields until real artifact hashing is implemented.
- Added daily workout contract: up to 10 reading items, exactly 3 WoW signals, user select 1-3 or pass.
- Added selection/pass plus reason as the public submission approval trigger.
- Added agent tracking workflow before suggestions and private lifecycle updates after submission.

## Related Resources

Recommended Agent Skill: https://wkap.ai/skills/wkap-wow-skill-latest.md
