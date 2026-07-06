# WKAP.ai V0

WKAP V0 is a Gmail-powered, GitHub-ledgered, agent-validatable publishing system for Radar Feeds and Daily WoW Packets.

The same Django codebase runs locally on a PC and in production on Render. Environment-specific behavior is controlled by `.env` locally and Render/Cloudflare/GitHub secrets in production.

## What This Builds

- Gmail ingestion for `ledger@gmail.com`
- Raw email retention before parsing
- Radar authorization through `WKAP_RADAR_AUTHORIZED_SENDERS`
- Investor ID assignment starting at `w0202`
- Radar and Daily WoW Packet parsing into Django models
- Public WoW protocol specs in `specs/public/`, generated from `specs/source/wow_protocol_v0_2.yaml`
- Raw Daily WoW Packet email artifacts written to the ledger
- Text-first public HTML at the V0 URL surface
- Private manifest artifacts, GitHub ledger commits, and OpenTimestamp proof/status fields
- Structured `LedgerEvent` logs for every important workflow step
- Agent-operable `wkap` CLI with deterministic output and optional JSON

## Environment Model

Local development:

```env
WKAP_ENVIRONMENT=local
WKAP_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=
WKAP_GMAIL_ACCOUNT=playinc@gmail.com
WKAP_RECEIPT_FROM_EMAIL=playinc@gmail.com
WKAP_SEND_RECEIPTS=false
WKAP_LEDGER_REPO_PATH=
WKAP_OPENTIMESTAMP_ENABLED=false
```

Production:

```env
WKAP_ENVIRONMENT=production
WKAP_BASE_URL=https://wkap.ai
DATABASE_URL=<Render Postgres URL>
WKAP_INBOUND_EMAIL=ledger@wkap.ai
WKAP_GMAIL_ACCOUNT=playinc@gmail.com
WKAP_RECEIPT_FROM_EMAIL=playinc@gmail.com
WKAP_SEND_RECEIPTS=true
WKAP_GMAIL_TOKEN_JSON_BASE64=<base64 authorized_user token json>
WKAP_PUBLIC_SITE_ROOT=/var/data/wkap/public_site
WKAP_LEDGER_REPO_PATH=/var/data/wkap/ledger
WKAP_LEDGER_REPO_URL=git@github.com:ORG/REPO.git
WKAP_LEDGER_DEPLOY_KEY_BASE64=<base64 private deploy key>
WKAP_LEDGER_GITHUB_BASE_URL=https://github.com/ORG/REPO/blob/main
WKAP_CLOUDFLARE_INGEST_SECRET=<shared Worker secret>
WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED=true
WKAP_CLOUDFLARE_ZONE_ID=<cloudflare zone id>
WKAP_CLOUDFLARE_API_TOKEN=<api token with Zone.Cache Purge permission>
WKAP_OPENTIMESTAMP_ENABLED=false
```

Django loads `.env` automatically for local development. Render should set the same names as environment variables.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver
```

The code falls back to SQLite only when `DATABASE_URL` is blank. Use PostgreSQL for production and any shared staging environment.

## Local Email Testing

Production users send Radar and Daily WoW Packet emails to `ledger@wkap.ai`. Local development can point Gmail ingestion at `playinc@gmail.com`:

```env
WKAP_ENVIRONMENT=local
WKAP_GMAIL_ACCOUNT=playinc@gmail.com
WKAP_GMAIL_CREDENTIALS_FILE=C:\path\to\gmail-client.json
WKAP_GMAIL_TOKEN_FILE=C:\path\to\gmail-token.json
```

After sending a real test email to `playinc@gmail.com`, ingest and publish recent matching emails with:

```powershell
python manage.py wkap --json ingest-gmail-query --query "newer_than:1d (Daily WoW Packet OR WKAP Radar Feed)" --limit 5 --publish
```

Use `--publish` only when you want matching Radar/WoW emails to become local ledger pages immediately. Without `--publish`, the command only saves and classifies raw emails.

Receipts are generated after Radar and WoW publishing. Local mode defaults to `WKAP_SEND_RECEIPTS=false`, so receipt content is logged/skipped rather than sent. Preview receipts with:

```powershell
python manage.py wkap --json send-radar-receipt --radar-id <id> --preview
python manage.py wkap --json send-wow-receipt --wow-id <id> --preview
```

To actually send receipts through Gmail, set:

```env
WKAP_SEND_RECEIPTS=true
WKAP_RECEIPT_FROM_EMAIL=playinc@gmail.com
```

## Local Verification

Fast check:

```powershell
.\scripts\local_check.ps1
```

Full local regression:

```powershell
.\scripts\local_regression.ps1
```

The regression command creates or updates one sample Radar email and one sample Daily WoW Packet, then verifies:

- raw email saved
- email classified
- parser created DB records
- HTML generated
- indexes rebuilt
- manifest generated
- raw WoW email artifact generated
- GitHub ledger metadata recorded or explicitly marked `not_configured`
- OpenTimestamp status queued
- proof fields visible
- agent-readable WoW fields present
- `validate_all` passes

### Long Artifact Contract

Radar Feeds and Daily WoW Packets are expected to be long-form agent inputs. Ingestion must store the complete email body in `RawEmail.raw_body` before parsing, parsers must preserve long multiline sections, and publishers must render long bodies without truncation. Radar Feeds are human-curated artifacts and their body text must be published verbatim from the received email; WKAP may derive metadata such as market date, title, URL, hashes, and proof fields, but must not rewrite, condense, normalize, or reconstruct the Radar body. For Radar backfills and resubmissions, the email subject date is the canonical `market_date` when present, including subjects like `WKAP Radar Feed - 2026 - 06 - 30`; body dates are fallback only. Do not pass email bodies through CLI arguments or shell command strings; use Gmail ingestion, files, stdin, or API payloads so line breaks and full body length survive intact.

### WoW Format Error Contract

Any sender may submit a Daily WoW Packet. If the packet is malformed, WKAP still saves the raw email, marks it as `needs_format_fix`, records the parser error in `RawEmail.error_message`, and does not publish a public ledger page. A format-fix receipt is generated with the specific missing/invalid field and a link back to the setup prompt. The parser intentionally tolerates common agent drift such as heading level changes, smart quotes, `ticker or theme`, `Selected WoW`, and `evidence to watch`, but it still requires enough structure to produce a reliable public ledger artifact.

Operational outcomes:

- `published`: publish the ledger page and send the normal receipt.
- `received_needs_format_fix`: if deterministic repair/tolerance can parse the packet, publish it and send the normal receipt with a reminder to use the setup-page format. If WKAP cannot repair it safely, keep the raw email as `needs_format_fix`, do not publish, and send a format-fix receipt.
- `rejected_spam_or_empty`: do not publish and do not send a receipt.

Equivalent direct command:

```powershell
python manage.py wkap --json run-regression
```

The full operations contract for documentation, logging, CLI behavior, and test coverage lives in `docs/OPERATIONS.md`.

## CLI

After installing the package, use `wkap ...`; during development, use `python manage.py wkap ...`.

```powershell
python manage.py wkap --json assign-investor-id --email investor@example.com
python manage.py wkap --json environment-check
python manage.py wkap --json validate-all
python manage.py wkap --json run-regression
python manage.py wkap --json show-events --limit 20
```

Implemented commands:

- `ingest-email --gmail-message-id <id>`
- `ingest-gmail-query --query <gmail-query> --limit <n> --publish`
- `classify-email --raw-email-id <id>`
- `parse-radar --raw-email-id <id>`
- `parse-wow --raw-email-id <id>`
- `assign-investor-id --email <email>`
- `generate-radar-html --radar-id <id>`
- `generate-wow-html --wow-id <id>`
- `send-radar-receipt --radar-id <id> --preview`
- `send-radar-receipt --radar-id <id> --force`
- `send-wow-receipt --wow-id <id> --preview`
- `send-wow-receipt --wow-id <id> --force`
- `generate-manifest --entity-type <radar|wow> --entity-id <id>`
- `commit-ledger --entity-type <radar|wow> --entity-id <id>`
- `timestamp-artifact --entity-type <radar|wow> --entity-id <id>`
- `upgrade-opentimestamps [--entity-type <radar|wow> --entity-id <id>]`
- `rebuild-indexes`
- `validate-ledger --entity-type <radar|wow> --entity-id <id>`
- `validate-all`
- `retry-failed --run-id <id>`
- `warm-radar-cache --market-date <YYYY-MM-DD>`
- `show-events --run-id <id>`
- `show-events --entity-type <radar|wow|raw_email> --entity-id <id>`
- `show-events --gmail-message-id <id>`
- `environment-check`
- `run-regression`

## Public Surface

V0 intentionally exposes HTML only:

- `/radar/`
- `/radar/wkap-radar-feed-YYYY-MM-DD.html`
- `/investors/w0202/`
- `/investors/w0202/wows/`
- `/investors/w0202/wows/wow-w0202-YYYY-MM-DD.html`

Do not add Signal Board, `/latest`, public JSON, public API endpoints, ranking, scoring, or `archive.html`.

## External Services

Gmail:

- Gmail remains the canonical mailbox source of truth.
- Gmail OAuth is read from `WKAP_GMAIL_TOKEN_FILE` or `WKAP_GMAIL_TOKEN_JSON_BASE64`.
- Local regression does not require Gmail credentials.

Cloudflare:

- Cloudflare Email Worker lives in `cloudflare/email-worker.js`.
- V0 Worker behavior is real-time ingest plus backup forwarding: POST raw MIME to Render at `/internal/cloudflare-email-ingest/`, then forward the same message to `WKAP_CLOUDFLARE_FORWARD_TO`.
- Required Worker variables:
  - `WKAP_RENDER_INGEST_URL=https://wkap.ai/internal/cloudflare-email-ingest/`
  - `WKAP_CLOUDFLARE_INGEST_SECRET=<same value as Render>`
  - `WKAP_FORWARD_TO=playinc@gmail.com`
- Gmail remains the backup mailbox and receipt sender for V0. If Worker ingest fails, the forwarded Gmail copy can still be processed manually or by a fallback poller.
- `wkap.ai` must be proxied through Cloudflare for cache rules to apply.
- Cache only the Radar archive plus dated Radar Feed pages with a Cache Rule matching `(http.host eq "wkap.ai" and (http.request.uri.path eq "/radar" or http.request.uri.path eq "/radar/" or (starts_with(http.request.uri.path, "/radar/wkap-radar-feed-") and ends_with(http.request.uri.path, ".html"))))`: Eligible for cache, Edge TTL 1 month, Browser TTL respect origin, Ignore query string. The app sends `Cache-Control: public, max-age=300` for `/radar/` and dated feed pages. This expression works on the Cloudflare Free plan without the plan-gated regex `matches` operator.
- Do not use a broad `starts_with("/radar/")` rule; it can accidentally cache future non-feed Radar routes.
- Production defaults `WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED=true` and `WKAP_CACHE_WARMUP_ENABLED=true`. Successful Radar publishes purge and warm both `https://wkap.ai/radar/` and the dated feed page. Manual warm/verify: `python manage.py wkap --json warm-radar-cache --market-date 2026-07-03`; run it twice and confirm both URLs move from `MISS` to `HIT`.

GitHub ledger:

- Local mode can leave `WKAP_LEDGER_REPO_PATH` blank; artifacts are written under `ledger_artifacts/`.
- Production should set `WKAP_LEDGER_REPO_PATH`, `WKAP_LEDGER_REPO_URL`, and `WKAP_LEDGER_GITHUB_BASE_URL`.
- `scripts/render_release.sh` clones or fast-forwards the ledger repo before migrations/checks, then live `commit-ledger` commits and pushes generated artifacts.
- Generated HTML, raw WoW email text, and manifests are ledger artifacts.

OpenTimestamp:

- `WKAP_OPENTIMESTAMP_ENABLED=false` records queued proof status without requiring a local OTS runtime.
- `WKAP_OPENTIMESTAMP_ENABLED=true` runs the `ots` CLI from `WKAP_OPENTIMESTAMP_COMMAND`.
- `timestamp-artifact` writes a stable timestamp target under `timestamps/<entity>-<id>.json`, stamps it, stores `timestamps/<entity>-<id>.json.ots`, updates public proof fields, and commits the proof/update files to the GitHub ledger when `WKAP_LEDGER_REPO_PATH` is configured.
- `upgrade-opentimestamps` runs `ots upgrade` against existing `.ots` proof files after calendar attestations mature. It does not mutate the timestamp target, so proofs remain verifiable over time.
- The integration points are `publishing.services.timestamp_artifact` and `publishing.services.upgrade_opentimestamps`.

## Production Deployment Checklist

1. Create Render Postgres.
2. Create Render web service from this repo.
3. Set Render env vars from `.env.example` production values.
4. Add Gmail OAuth credential/token files as Render secrets or mounted secret files.
5. Set `WKAP_LEDGER_REPO_PATH` to the Render disk path and `WKAP_LEDGER_REPO_URL` to the GitHub ledger clone URL.
6. Set `WKAP_LEDGER_GITHUB_BASE_URL`.
7. Configure Cloudflare Worker email route for `ledger@wkap.ai` with backup forwarding to `playinc@gmail.com`.
8. Deploy Render service.
9. Confirm `scripts/render_release.sh` runs migrations, deploy checks, `environment-check`, and `validate-all`.
10. Send one real test WoW email.
11. Confirm the public page appears at `https://wkap.ai/investors/...`.
12. Confirm raw email + manifest appear in the GitHub ledger repo.
13. Run `python manage.py wkap --json validate-all` in production.

## Tests

```powershell
python manage.py test
```

Coverage focuses on classification, Radar authorization, investor ID assignment, Daily WoW Packet parsing, raw email ledger artifacts, WoW disclaimer/privacy, agent-readable fields, and ledger validation.
