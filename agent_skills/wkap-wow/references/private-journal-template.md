# Private WoW Journal Template

Recommended user-owned Markdown structure:

Default first. Use local Markdown files in `WKAP WoW Journal/` in the active workspace or user documents area unless the user asks for a different path. Create the folder and required files if missing. When running in this repo, use:

```text
C:\Users\ASUS\Documents\wkap\WKAP WoW Journal
```

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
  skill_version: v0.2
  private_status: prepared_private
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
