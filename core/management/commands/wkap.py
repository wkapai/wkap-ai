from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.cli import CommandResult, error_result
from core.environment import environment_errors
from core.events import log_event, new_run_id
from core.regression import run_local_regression
from ingestion.gmail import search_gmail_message_ids
from ingestion.models import RawEmail
from ingestion.services import classify_email, ingest_email
from ledger.investor_id import find_or_create_investor
from ledger.models import LedgerEvent
from ledger.parsers import ParseError
from ledger.services import create_radar_issue, create_wow_submission
from publishing.services import (
    commit_ledger,
    generate_manifest,
    generate_radar_html,
    generate_wow_html,
    publish_artifact,
    rebuild_indexes,
    timestamp_pending_artifacts,
    timestamp_artifact,
    upgrade_opentimestamps,
    validate_all,
    validate_ledger,
    warm_radar_cache,
)
from publishing.receipts import (
    radar_receipt_body,
    radar_receipt_subject,
    send_radar_receipt,
    send_wow_format_fix_receipt,
    send_wow_receipt,
    wow_format_fix_body,
    wow_format_fix_subject,
    wow_receipt_body,
    wow_receipt_subject,
)


class Command(BaseCommand):
    help = "Agent-operable WKAP CLI."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        subparsers = parser.add_subparsers(dest="subcommand", required=True)

        ingest = subparsers.add_parser("ingest-email")
        ingest.add_argument("--gmail-message-id", required=True)

        ingest_query = subparsers.add_parser("ingest-gmail-query")
        ingest_query.add_argument("--query", required=True)
        ingest_query.add_argument("--limit", type=int, default=10)
        ingest_query.add_argument("--publish", action="store_true")

        classify = subparsers.add_parser("classify-email")
        classify.add_argument("--raw-email-id", required=True, type=int)

        parse_radar = subparsers.add_parser("parse-radar")
        parse_radar.add_argument("--raw-email-id", required=True, type=int)

        parse_wow = subparsers.add_parser("parse-wow")
        parse_wow.add_argument("--raw-email-id", required=True, type=int)

        assign = subparsers.add_parser("assign-investor-id")
        assign.add_argument("--email", required=True)

        radar_html = subparsers.add_parser("generate-radar-html")
        radar_html.add_argument("--radar-id", required=True, type=int)

        wow_html = subparsers.add_parser("generate-wow-html")
        wow_html.add_argument("--wow-id", required=True, type=int)

        receipt = subparsers.add_parser("send-wow-receipt")
        receipt.add_argument("--wow-id", required=True, type=int)
        receipt.add_argument("--force", action="store_true")
        receipt.add_argument("--preview", action="store_true")

        radar_receipt = subparsers.add_parser("send-radar-receipt")
        radar_receipt.add_argument("--radar-id", required=True, type=int)
        radar_receipt.add_argument("--force", action="store_true")
        radar_receipt.add_argument("--preview", action="store_true")

        manifest = subparsers.add_parser("generate-manifest")
        self._add_entity_args(manifest)

        commit = subparsers.add_parser("commit-ledger")
        self._add_entity_args(commit)

        timestamp = subparsers.add_parser("timestamp-artifact")
        self._add_entity_args(timestamp)

        timestamp_pending = subparsers.add_parser("timestamp-pending-artifacts")
        timestamp_pending.add_argument("--entity-type", choices=["radar", "wow"])
        timestamp_pending.add_argument("--entity-id", type=int)
        timestamp_pending.add_argument("--limit", type=int)

        upgrade_ots = subparsers.add_parser("upgrade-opentimestamps")
        upgrade_ots.add_argument("--entity-type", choices=["radar", "wow"])
        upgrade_ots.add_argument("--entity-id", type=int)

        subparsers.add_parser("rebuild-indexes")

        warm_radar = subparsers.add_parser("warm-radar-cache")
        warm_radar.add_argument("--market-date", required=True)

        validate = subparsers.add_parser("validate-ledger")
        self._add_entity_args(validate)

        subparsers.add_parser("validate-all")

        retry = subparsers.add_parser("retry-failed")
        retry.add_argument("--run-id", required=True)

        events = subparsers.add_parser("show-events")
        events.add_argument("--run-id")
        events.add_argument("--entity-type")
        events.add_argument("--entity-id")
        events.add_argument("--gmail-message-id")
        events.add_argument("--limit", type=int, default=50)

        subparsers.add_parser("environment-check")

        subparsers.add_parser("run-regression")

    def handle(self, *args, **options):
        run_id = new_run_id()
        command = options["subcommand"]
        try:
            result = self._dispatch(command, run_id=run_id, options=options)
        except Exception as exc:
            log_event(
                "ingestion_failed",
                run_id=run_id,
                status=LedgerEvent.Status.FAILED,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            result = error_result(command, str(run_id), str(exc))

        result.emit(as_json=options["json"])
        result.exit()

    def _dispatch(self, command: str, *, run_id, options) -> CommandResult:
        if command == "ingest-email":
            raw_email = ingest_email(options["gmail_message_id"], run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="raw_email",
                entity=raw_email,
                next_action=f"wkap classify-email --raw-email-id {raw_email.id}",
            )

        if command == "ingest-gmail-query":
            return self._ingest_gmail_query(command, run_id, options)

        if command == "classify-email":
            raw_email = RawEmail.objects.get(id=options["raw_email_id"])
            classification = classify_email(raw_email, run_id=run_id)
            next_action = {
                RawEmail.Classification.RADAR: f"wkap parse-radar --raw-email-id {raw_email.id}",
                RawEmail.Classification.WOW: f"wkap parse-wow --raw-email-id {raw_email.id}",
            }.get(classification, "saved_not_published")
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="raw_email",
                entity=raw_email,
                next_action=next_action,
            )

        if command == "parse-radar":
            issue = create_radar_issue(RawEmail.objects.get(id=options["raw_email_id"]), run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="radar",
                entity=issue,
                next_action=f"wkap generate-radar-html --radar-id {issue.id}",
            )

        if command == "parse-wow":
            raw_email = RawEmail.objects.get(id=options["raw_email_id"])
            try:
                submission = create_wow_submission(raw_email, run_id=run_id)
            except ParseError:
                send_wow_format_fix_receipt(raw_email, run_id=run_id)
                result = CommandResult.from_entity(
                    command=command,
                    run_id=str(run_id),
                    status="skipped",
                    entity_type="raw_email",
                    entity=raw_email,
                    errors=[raw_email.error_message],
                    next_action="format_fix_receipt_generated",
                )
                result.details = {
                    "to": raw_email.sender_email,
                    "subject": wow_format_fix_subject(raw_email),
                    "body": wow_format_fix_body(raw_email),
                }
                return result
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="wow",
                entity=submission,
                next_action=f"wkap generate-wow-html --wow-id {submission.id}",
            )

        if command == "assign-investor-id":
            investor, created = find_or_create_investor(options["email"], run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="investor",
                entity=investor,
                next_action="created" if created else "reused",
            )

        if command == "generate-radar-html":
            from ledger.models import RadarIssue

            issue = generate_radar_html(RadarIssue.objects.get(id=options["radar_id"]), run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="radar",
                entity=issue,
                next_action=f"wkap generate-manifest --entity-type radar --entity-id {issue.id}",
            )

        if command == "generate-wow-html":
            from ledger.models import DailyWoWPacket

            submission = generate_wow_html(DailyWoWPacket.objects.get(id=options["wow_id"]), run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="wow",
                entity=submission,
                next_action=f"wkap generate-manifest --entity-type wow --entity-id {submission.id}",
            )

        if command == "send-wow-receipt":
            from ledger.models import DailyWoWPacket

            submission = DailyWoWPacket.objects.select_related("investor", "source_email").get(id=options["wow_id"])
            if options["preview"]:
                result = CommandResult.from_entity(
                    command=command,
                    run_id=str(run_id),
                    status="succeeded",
                    entity_type="wow",
                    entity=submission,
                    next_action="remove --preview to send when WKAP_SEND_RECEIPTS=true",
                )
                result.details = {
                    "to": submission.investor.email_private,
                    "subject": wow_receipt_subject(submission),
                    "body": wow_receipt_body(submission),
                }
                return result
            submission = send_wow_receipt(submission, run_id=run_id, force=options["force"])
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="wow",
                entity=submission,
                next_action="done",
            )

        if command == "send-radar-receipt":
            from ledger.models import RadarIssue

            issue = RadarIssue.objects.select_related("source_email").get(id=options["radar_id"])
            if options["preview"]:
                result = CommandResult.from_entity(
                    command=command,
                    run_id=str(run_id),
                    status="succeeded",
                    entity_type="radar",
                    entity=issue,
                    next_action="remove --preview to send when WKAP_SEND_RECEIPTS=true",
                )
                result.details = {
                    "to": issue.source_email.sender_email,
                    "subject": radar_receipt_subject(issue),
                    "body": radar_receipt_body(issue),
                }
                return result
            issue = send_radar_receipt(issue, run_id=run_id, force=options["force"])
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type="radar",
                entity=issue,
                next_action="done",
            )

        if command == "generate-manifest":
            generate_manifest(options["entity_type"], options["entity_id"], run_id=run_id)
            return self._entity_result(command, run_id, options["entity_type"], options["entity_id"], "commit-ledger")

        if command == "commit-ledger":
            artifact = commit_ledger(options["entity_type"], options["entity_id"], run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type=options["entity_type"],
                entity=artifact,
                next_action=f"wkap timestamp-artifact --entity-type {options['entity_type']} --entity-id {artifact.id}",
            )

        if command == "timestamp-artifact":
            artifact = timestamp_artifact(options["entity_type"], options["entity_id"], run_id=run_id)
            return CommandResult.from_entity(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type=options["entity_type"],
                entity=artifact,
                next_action=f"wkap validate-ledger --entity-type {options['entity_type']} --entity-id {artifact.id}",
            )

        if command == "timestamp-pending-artifacts":
            if options.get("entity_id") and not options.get("entity_type"):
                raise CommandError("--entity-id requires --entity-type")
            stamped = timestamp_pending_artifacts(
                run_id=run_id,
                entity_type=options.get("entity_type"),
                entity_id=options.get("entity_id"),
                limit=options.get("limit"),
            )
            result = CommandResult(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type=options.get("entity_type") or "opentimestamp",
                entity_id=str(options.get("entity_id") or ""),
                next_action="done",
            )
            result.details = {
                "processed_count": len(stamped),
                "artifacts": [f"{'radar' if artifact.__class__.__name__ == 'RadarIssue' else 'wow'}:{artifact.id}" for artifact in stamped],
            }
            return result

        if command == "upgrade-opentimestamps":
            if options.get("entity_id") and not options.get("entity_type"):
                raise CommandError("--entity-id requires --entity-type")
            upgraded = upgrade_opentimestamps(run_id=run_id, entity_type=options.get("entity_type"), entity_id=options.get("entity_id"))
            result = CommandResult(
                command=command,
                run_id=str(run_id),
                status="succeeded",
                entity_type=options.get("entity_type") or "opentimestamp",
                entity_id=str(options.get("entity_id") or ""),
                next_action="done",
            )
            result.details = {"upgraded_count": len(upgraded), "ids": [artifact.id for artifact in upgraded]}
            return result

        if command == "rebuild-indexes":
            rebuild_indexes(run_id=run_id)
            return CommandResult(command=command, run_id=str(run_id), status="succeeded", next_action="wkap validate-all")

        if command == "warm-radar-cache":
            results = warm_radar_cache(options["market_date"], run_id=run_id)
            errors = [result for result in results if result.get("error")]
            result = CommandResult(
                command=command,
                run_id=str(run_id),
                status="failed" if errors else "succeeded",
                entity_type="radar",
                market_date=options["market_date"],
                next_action="run again and confirm cf_cache_status is HIT",
            )
            result.details = {"results": results}
            result.errors = [f"{item['url']}: {item['error']}" for item in errors]
            return result

        if command == "validate-ledger":
            errors = validate_ledger(options["entity_type"], options["entity_id"])
            return self._entity_result(
                command,
                run_id,
                options["entity_type"],
                options["entity_id"],
                "done" if not errors else "repair_missing_evidence",
                errors,
            )

        if command == "validate-all":
            errors = validate_all()
            return CommandResult(
                command=command,
                run_id=str(run_id),
                status="succeeded" if not errors else "failed",
                errors=errors,
                next_action="done" if not errors else "repair_missing_evidence",
            )

        if command == "retry-failed":
            return self._retry_failed(command, str(options["run_id"]), run_id)

        if command == "show-events":
            return self._show_events(command, run_id, options)

        if command == "environment-check":
            errors = environment_errors()
            return CommandResult(
                command=command,
                run_id=str(run_id),
                status="succeeded" if not errors else "failed",
                errors=errors,
                next_action="done" if not errors else "fix environment variables",
            )

        if command == "run-regression":
            regression = run_local_regression(run_id=run_id)
            errors = regression["errors"]
            return CommandResult(
                command=command,
                run_id=str(run_id),
                status="succeeded" if not errors else "failed",
                entity_type="regression",
                entity_id=f"radar:{regression['radar_id']},wow:{regression['wow_id']}",
                investor_id=regression["investor_id"],
                market_date=regression["market_date"],
                canonical_url=regression["wow_url"],
                errors=errors,
                next_action="done" if not errors else "inspect validate-all output",
            )

        raise CommandError(f"Unknown command: {command}")

    def _show_events(self, command: str, run_id, options) -> CommandResult:
        events = LedgerEvent.objects.order_by("-timestamp", "-id")
        if options.get("run_id"):
            events = events.filter(run_id=options["run_id"])
        if options.get("entity_type"):
            events = events.filter(entity_type=options["entity_type"])
        if options.get("entity_id"):
            events = events.filter(entity_id=str(options["entity_id"]))
        if options.get("gmail_message_id"):
            events = events.filter(gmail_message_id=options["gmail_message_id"])

        limit = max(1, min(options.get("limit") or 50, 500))
        rows = [
            {
                "id": event.id,
                "timestamp": event.timestamp.isoformat(),
                "event_name": event.event_name,
                "status": event.status,
                "environment": event.environment,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "run_id": str(event.run_id),
                "gmail_message_id": event.gmail_message_id,
                "sender_email": event.sender_email,
                "investor_id": event.investor_id,
                "market_date": str(event.market_date or ""),
                "content_hash": event.content_hash,
                "canonical_url": event.canonical_url,
                "github_file_url": event.github_file_url,
                "github_commit_sha": event.github_commit_sha,
                "ots_status": event.ots_status,
                "error_code": event.error_code,
                "error_message": event.error_message,
                "details": event.details,
            }
            for event in events[:limit]
        ]
        return CommandResult(
            command=command,
            run_id=str(run_id),
            status="succeeded",
            entity_type="ledger_events",
            details={"count": len(rows), "events": rows},
            next_action="done",
        )

    def _entity_result(self, command, run_id, entity_type, entity_id, next_action, errors=None):
        from publishing.services import _artifact

        artifact = _artifact(entity_type, entity_id)
        return CommandResult.from_entity(
            command=command,
            run_id=str(run_id),
            status="succeeded" if not errors else "failed",
            entity_type=entity_type,
            entity=artifact,
            errors=errors or [],
            next_action=next_action,
        )

    def _retry_failed(self, command: str, original_run_id: str, run_id) -> CommandResult:
        failed = LedgerEvent.objects.filter(run_id=original_run_id, status=LedgerEvent.Status.FAILED).order_by("timestamp")
        log_event(
            "retry_started",
            run_id=run_id,
            status=LedgerEvent.Status.STARTED,
            details={"original_run_id": original_run_id, "failed_count": failed.count()},
        )
        if not failed.exists():
            log_event("retry_succeeded", run_id=run_id, details={"original_run_id": original_run_id})
            return CommandResult(command=command, run_id=str(run_id), status="skipped", next_action="no_failed_events")

        log_event(
            "retry_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            details={"original_run_id": original_run_id, "failed_events": list(failed.values_list("event_name", flat=True))},
        )
        return CommandResult(
            command=command,
            run_id=str(run_id),
            status="failed",
            errors=["Automatic retry requires the failed command inputs; inspect LedgerEvent details."],
            next_action="rerun specific wkap command",
        )

    def _ingest_gmail_query(self, command: str, run_id, options) -> CommandResult:
        message_ids = search_gmail_message_ids(options["query"], max_results=options["limit"])
        raw_email_ids = []
        published = []
        skipped = []
        errors = []
        last_entity = None
        for message_id in message_ids:
            try:
                raw_email = ingest_email(message_id, run_id=run_id)
                raw_email_ids.append(raw_email.id)
                classification = classify_email(raw_email, run_id=run_id)
                last_entity = raw_email
                if not options["publish"]:
                    continue
                if classification == RawEmail.Classification.RADAR:
                    issue = create_radar_issue(raw_email, run_id=run_id)
                    last_entity = publish_artifact("radar", issue.id, run_id=run_id)
                    published.append(f"radar:{issue.id}")
                elif classification == RawEmail.Classification.WOW:
                    try:
                        submission = create_wow_submission(raw_email, run_id=run_id)
                    except ParseError:
                        send_wow_format_fix_receipt(raw_email, run_id=run_id)
                        skipped.append(f"raw_email:{raw_email.id}:needs_format_fix")
                        last_entity = raw_email
                        continue
                    last_entity = publish_artifact("wow", submission.id, run_id=run_id)
                    published.append(f"wow:{submission.id}")
                else:
                    skipped.append(f"raw_email:{raw_email.id}:{classification}")
            except Exception as exc:
                errors.append(f"{message_id}: {exc}")

        result = CommandResult.from_entity(
            command=command,
            run_id=str(run_id),
            status="succeeded" if not errors else "failed",
            entity_type="gmail_query",
            entity=last_entity,
            errors=errors,
            next_action="done" if not errors else "inspect errors and LedgerEvent logs",
        )
        result.details = {
            "gmail_account": settings.WKAP_GMAIL_ACCOUNT,
            "query": options["query"],
            "gmail_message_ids": message_ids,
            "raw_email_ids": raw_email_ids,
            "published": published,
            "skipped": skipped,
        }
        return result

    @staticmethod
    def _add_entity_args(parser):
        parser.add_argument("--entity-type", required=True, choices=["radar", "wow"])
        parser.add_argument("--entity-id", required=True, type=int)
