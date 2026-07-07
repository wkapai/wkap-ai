# Private WoW Journal Template

Recommended user-owned Markdown structure:

Default first. Use local Markdown files in `WKAP WoW Journal/` in the active workspace or user documents area unless the user asks for a different path. Create the folder and required files if missing. Do not hardcode a machine-specific path; resolve the final path from the active workspace or another user-owned durable location.

```text
WKAP WoW Journal/
  daily/
  active-trackables.md
  pending-scoreables.md
  thesis-map.md
  receipts.md
  public-verification.md
```

Daily packets go in:

```text
WKAP WoW Journal/daily/YYYY-MM-DD.md
```

Each daily entry should preserve:

```yaml
daily_packet_record:
  local_journal_entry_id:
  prepared_at:
  packet_spec_version: v0.2
  packet_spec_url_requested:
  packet_spec_url_resolved:
  skill_url_requested:
  skill_url_resolved:
  packet_spec_content_sha256:
  skill_content_sha256:
  skill_version: v0.2
  selection_status: incomplete
  private_status: incomplete_private
  submission_status: not_submitted
  receipt_status: no_receipt
  public_status: not_public
  public_url: null
  receipt_id: null
  packet_id: null
```

Track:

- prepared packets
- rejected packets
- no-reply days
- active trackables
- pending scoreable signals
- thesis children
- status updates
- receipt checks
- public page verification
