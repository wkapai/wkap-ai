# Daily WoW Packet Template

```markdown
# WKAP Daily WoW Packet

Human summary:
[One short paragraph for the user explaining what this packet preserves.]

```yaml
packet:
  packet_id: WKAP-[investor_id]-[YYYY-MM-DD]
  investor_id: [WKAP investor ID if known, otherwise stable user/agent identity slug]
  market_date: YYYY-MM-DD
  created_at: YYYY-MM-DDTHH:MM:SSZ
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  packet_spec_latest_url: https://wkap.ai/specs/wow-packet-latest.md
  packet_spec_url_requested: https://wkap.ai/specs/wow-packet-latest.md
  packet_spec_url_resolved: https://wkap.ai/specs/wow-packet-v0.2.md
  packet_spec_content_sha256:
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  skill_url_requested: https://wkap.ai/skills/wkap-wow-skill-latest.md
  skill_url_resolved: https://wkap.ai/skills/wkap-wow-skill-v0.2.md
  skill_content_sha256:
  human_view:
    title:
    summary:
    top_wows: []
  agent_facts:
    packet_id: WKAP-[investor_id]-[YYYY-MM-DD]
    investor_id: [same as above]
    packet_spec_version: v0.2
    wow_count: 0
    scoreable_count: 0
    trackable_count: 0
    thesis_count: 0
    candidate_count: 0
    status_update_count: 0
  reading_log: []
  wow_items: []
  selection:
    selected_wow_id: "none"
    reason_for_selection: null
    reason_for_pass: null
    closest_rejected_wow: null
    missing_evidence: null
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
```

Rules:

- Keep the fenced YAML syntactically valid.
- Include every public item under `wow_items`.
- Include exactly 3 `wow_items` for the daily user choice.
- Include up to 10 top reading items in `reading_log`.
- A prose list of top private WoWs is not enough; preserve this full packet structure even when the packet stays private.
- Before asking the user to choose, show exactly 3 numbered options with a visible type label, plain-English title, and why it is worth watching.
- Store `wow_id` internally, but do not show it in the default user-facing choice prompt unless the user asks for technical details.
- The user chooses by number only: `Pick one WoW: 1, 2, 3, or pass.`
- For `scoreable_signal`, visibly show `invalidate_test`, `resolve_by`, and `resolution_source`.
- Default scope is one Daily WoW Packet for the resolved US trading date, not a weekly review.
- Use `status_update` only for append-only updates to existing WoWs, including evidence-only updates that keep the same status.
- Every `status_update` must include `target_wow_type`, `target_wow_id`, `target_root_wow_id`, `update_type`, `previous_status`, and `new_status`.
- Every status transition must follow the allowed Agent CRM status table in the public skill/spec.
- Same-status updates must use `update_type: evidence`. `update_type: evidence` must not change status.
- Use `stale` only when a candidate or trackable has passed review timing without material confirming evidence and today's review finds it no longer merits active monitoring.
- Do not use `pending_scoreable` as a promotion `status_update.new_status`; promotion updates use `promoted_scoreable`, while the new child scoreable signal starts with `signal_status: pending_scoreable`. `pending_scoreable` is valid only for evidence-only same-status updates.
- User selection/pass plus required reason completes the Daily WoW Packet and triggers submission.
- The agent must remove or summarize private/confidential material and keep sensitive details in the Private WoW Journal.
- The pass sentinel is the literal string `"none"`, not YAML null.
- Always include all five `selection` keys. If `selected_wow_id` is not `"none"`, set pass-only fields to YAML null or an empty value.
- If `selected_wow_id` is `"none"`, fill `reason_for_pass`, `closest_rejected_wow`, and `missing_evidence`.
- On pass days, `closest_rejected_wow` must be one of today's suggested `wow_id` values, not prose.
