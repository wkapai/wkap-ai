# WKAP Operations Contract

This document is the working standard for keeping WKAP boring, auditable, and agent-friendly.

## System Guarantees

- Every inbound email is saved as `RawEmail` before classification or parsing.
- Cloudflare Email Worker ingest must POST raw MIME to Render and keep Gmail forwarding as backup during V0.
- Radar Feed bodies are human-curated and must be published verbatim from `RawEmail.raw_body`.
- Daily WoW Packet raw emails are ledger artifacts and must be committed alongside generated HTML and manifests.
- Public pages are HTML-first. Agent-readable facts live in page metadata and compact facts sections, not public JSON APIs.
- No core workflow should fail silently. If a step succeeds, skips, rejects, repairs, or fails, it should create a `LedgerEvent`.

## Email Outcomes

Radar:

- Authorized sender: parse, publish, ledger, timestamp, receipt.
- Unauthorized sender: save, reject, log, do not publish, do not receipt.
- Authorized senders are configured with `WKAP_RADAR_AUTHORIZED_SENDERS`.

Daily WoW Packet:

- `published`: packet parsed cleanly, public page published, normal receipt generated.
- `received_needs_format_fix`: raw email saved. If deterministic parser tolerance can safely repair it, publish and include a setup-format reminder in the normal receipt. If it cannot be repaired, mark the raw email `needs_format_fix`, do not publish, and generate a format-fix receipt.
- `rejected_spam_or_empty`: save/classify as unknown or reject, do not publish, do not receipt.

## Ledger Event Standard

Each workflow should produce enough `LedgerEvent` rows for an agent to reconstruct what happened without reading server logs.

Core event families:

- Ingestion: `email_received`, `raw_email_saved`, `email_classified`, `ingestion_failed`.
- Cloudflare Email Worker ingestion: `cloudflare_email_received`, `cloudflare_email_auth_failed`, `cloudflare_email_ingest_failed`, `cloudflare_email_not_published`.
- Radar authorization: `radar_authorized`, `radar_rejected`.
- Parsing: `radar_parsed`, `wow_parsed`, `wow_format_repaired`, `wow_format_fix_needed`.
- Publishing: `publish_started`, `html_generated`, `index_rebuilt`, `manifest_created`, `github_commit_started`, `github_commit_succeeded`, `github_commit_failed`, `opentimestamp_started`, `opentimestamp_succeeded`, `page_published`, `publish_succeeded`.
- Receipts: `receipt_email_started`, `receipt_email_sent`, `receipt_email_skipped`, `receipt_email_failed`, `format_fix_receipt_started`, `format_fix_receipt_sent`, `format_fix_receipt_skipped`, `format_fix_receipt_failed`.
- Recovery: `retry_started`, `retry_succeeded`, `retry_failed`.

Event rows should include the most specific available evidence fields:

- `run_id`
- `entity_type`
- `entity_id`
- `gmail_message_id`
- `sender_email`
- `investor_id`
- `market_date`
- `content_hash`
- `canonical_url`
- `github_file_url`
- `github_commit_sha`
- `ots_status`
- `error_code`
- `error_message`
- `details`

## CLI Standard

All commands should return deterministic status and exit code:

- `succeeded`: exit 0
- `skipped`: exit 0
- `failed`: exit 1

Use `--json` for agent workflows. JSON responses should include the command, generated run ID, status, relevant entity fields, errors, next action, and command-specific details.

Operator commands:

```powershell
python manage.py wkap --json environment-check
python manage.py wkap --json validate-all
python manage.py wkap --json run-regression
python manage.py wkap --json show-events --limit 20
python manage.py wkap --json show-events --run-id <run-id>
python manage.py wkap --json show-events --entity-type wow --entity-id <id>
python manage.py wkap --json show-events --gmail-message-id <gmail-message-id>
```

## Production Ledger Config

Production ledger config requires both a writable checkout path and clone URL:

```env
WKAP_LEDGER_REPO_PATH=/var/data/wkap/ledger
WKAP_LEDGER_REPO_URL=git@github.com:ORG/REPO.git
WKAP_LEDGER_DEPLOY_KEY_BASE64=<base64 private deploy key>
WKAP_LEDGER_GITHUB_BASE_URL=https://github.com/ORG/REPO/blob/main
```

Render runs `scripts/render_release.sh`, which clones or fast-forwards the ledger repo before deploy checks. Live `commit-ledger` writes, commits, and pushes generated HTML, manifests, and WoW raw email artifacts.

## Testing Standard

Before deployment or any ingestion/publishing refactor, run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py wkap --json validate-all
```

Regression coverage should protect:

- email save before parse
- classification
- Radar authorization and rejection
- Radar body verbatim publishing
- Daily WoW Packet parsing, tolerant repair, and format-fix failures
- investor ID assignment and reuse
- HTML generation and index rebuilds
- manifest and hash generation
- raw WoW email ledger artifact generation
- OpenTimestamp queued/status fields
- receipt preview/send/skip behavior
- `LedgerEvent` evidence fields
- CLI JSON shape and exit codes

## Major Version Release Gate

Before every major version deploy to production, run a focused scan for these three areas:

1. Documentation: README, operations docs, specs, setup page copy, and deployment instructions match the current product behavior.
2. Logging: every major workflow path has `LedgerEvent` coverage for success, skip, reject, repair, and failure states.
3. CLI and tests: agent-operable CLI commands have deterministic JSON output, correct exit codes, and unit/regression coverage for changed behavior.

Minimum commands:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py wkap --json environment-check
.\.venv\Scripts\python.exe manage.py wkap --json validate-all
.\.venv\Scripts\python.exe manage.py wkap --json run-regression
.\.venv\Scripts\python.exe manage.py wkap --json show-events --limit 20
```

Do not treat a major version as production-ready until these three scans are clean.

## Change Rule

When changing a workflow, update the relevant spec or operations doc first, then update code, then tests. For WoW Packet format changes, update `specs/wow_packet/` first so the parser, setup page, and tests follow one source of truth.
