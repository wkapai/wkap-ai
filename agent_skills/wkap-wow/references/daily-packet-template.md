# Daily WoW Packet Template

```markdown
# WKAP Daily WoW Packet

Human summary:
[One short paragraph for the user explaining what this packet preserves.]

```yaml
packet:
  packet_id: WKAP-[author_id]-[YYYY-MM-DD]
  author_id: [WKAP investor ID if known, otherwise stable user/agent identity slug]
  market_date: YYYY-MM-DD
  created_at: YYYY-MM-DDTHH:MM:SSZ
  packet_spec_version: v0.1
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.1.md
  packet_spec_latest_url: https://wkap.ai/specs/wow-packet-latest.md
  skill_version: v0.1
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title:
    summary:
    top_wows: []
  agent_facts:
    packet_id: WKAP-[author_id]-[YYYY-MM-DD]
    author_id: [same as above]
    packet_spec_version: v0.1
    wow_count: 0
    scoreable_count: 0
    trackable_count: 0
    thesis_count: 0
    candidate_count: 0
    status_update_count: 0
  reading_log: []
  wow_items: []
  selection:
    selected_wow_id: none
    reason_for_selection:
    reason_for_pass:
    closest_rejected_idea:
    missing_evidence:
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
- Default scope is one Daily WoW Packet for the current US market day, not a weekly review.
- Use `status_update` only for append-only updates to existing WoWs.
- User selection/pass plus required reason is approval to submit.
- If `selected_wow_id` is not `none`, leave pass-only fields blank.
- If `selected_wow_id` is `none`, fill `reason_for_pass`, `closest_rejected_idea`, and `missing_evidence`.
