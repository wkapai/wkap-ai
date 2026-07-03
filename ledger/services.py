from __future__ import annotations

import uuid
import hashlib

from django.db import transaction

from core.events import log_event
from ingestion.models import RawEmail
from ingestion.services import ensure_radar_authorized
from ledger.investor_id import find_or_create_investor, set_investor_display_name_from_subject
from ledger.models import AgentSuggestedWoW, DailyWoWPacket, LedgerEvent, RadarIssue, ReadingLogItem
from ledger.parsers import ParseError, parse_radar, parse_wow


def create_radar_issue(raw_email: RawEmail, *, run_id: uuid.UUID) -> RadarIssue:
    if not ensure_radar_authorized(raw_email, run_id=run_id):
        raise PermissionError("Unauthorized Radar sender.")
    try:
        parsed = parse_radar(raw_email)
    except ParseError as exc:
        _mark_parse_failed(raw_email, run_id=run_id, message=str(exc), event_name="radar_parsed")
        raise

    with transaction.atomic():
        issue, _ = RadarIssue.objects.update_or_create(
            market_date=parsed.market_date,
            defaults={
                "title": _radar_title_for_storage(parsed.title),
                "body_text": parsed.body_text,
                "body_html": "",
                "source_email": raw_email,
            },
        )
        raw_email.processing_status = RawEmail.ProcessingStatus.PARSED
        raw_email.save(update_fields=["processing_status", "updated_at"])
        log_event("radar_parsed", run_id=run_id, entity_type="radar", entity_id=issue.id, raw_email=raw_email, artifact=issue)
        log_event("db_record_created", run_id=run_id, entity_type="radar", entity_id=issue.id, raw_email=raw_email, artifact=issue)
    return issue


def _radar_title_for_storage(title: str) -> str:
    max_length = RadarIssue._meta.get_field("title").max_length or 500
    title = title.strip()
    if len(title) <= max_length:
        return title
    return title[: max_length - 3].rstrip() + "..."


def create_wow_submission(raw_email: RawEmail, *, run_id: uuid.UUID) -> DailyWoWPacket:
    investor, _ = find_or_create_investor(raw_email.sender_email, run_id=run_id)
    set_investor_display_name_from_subject(investor, raw_email.subject)
    used_setup_format = _uses_current_wow_setup_format(raw_email.raw_body)
    try:
        parsed = parse_wow(raw_email)
    except ParseError as exc:
        _mark_wow_format_fix_needed(raw_email, run_id=run_id, message=str(exc), investor=investor)
        raise

    with transaction.atomic():
        packet, _ = DailyWoWPacket.objects.update_or_create(
            investor=investor,
            market_date=parsed.market_date,
            defaults={
                "format_version": parsed.format_version,
                "selected_wow_id": parsed.selected_wow_id,
                "reason_for_selection": parsed.reason_for_selection,
                "closest_rejected_idea": parsed.closest_rejected_idea,
                "why_pass": parsed.why_pass,
                "missing_evidence": parsed.missing_evidence,
                "raw_email_sha256": hashlib.sha256(raw_email.raw_body.encode("utf-8")).hexdigest(),
                "source_email": raw_email,
                "submitted_at": parsed.submitted_at,
            },
        )
        packet.reading_items.all().delete()
        ReadingLogItem.objects.bulk_create(
            [
                ReadingLogItem(
                    packet=packet,
                    item_number=item.item_number,
                    source_title=item.source_title,
                    source_url=item.source_url,
                    source_type=item.source_type,
                    published_time=item.published_time,
                    tickers_or_themes=item.tickers_or_themes,
                    reading_origin=item.reading_origin,
                    agent_summary=item.agent_summary,
                )
                for item in parsed.reading_items
            ]
        )
        packet.suggested_wows.all().delete()
        AgentSuggestedWoW.objects.bulk_create(
            [
                AgentSuggestedWoW(
                    packet=packet,
                    item_number=item.item_number,
                    wow_id=item.wow_id,
                    source_refs=item.source_refs,
                    ticker_or_theme=item.ticker_or_theme,
                    whats_worth_watching=item.whats_worth_watching,
                    why_now=item.why_now,
                    evidence_to_watch_for=item.evidence_to_watch_for,
                    selected=bool(parsed.selected_wow_id and item.wow_id == parsed.selected_wow_id),
                )
                for item in parsed.suggested_wows
            ]
        )
        raw_email.processing_status = RawEmail.ProcessingStatus.PARSED
        raw_email.save(update_fields=["processing_status", "updated_at"])
        log_event(
            "wow_parsed",
            run_id=run_id,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=raw_email,
            investor=investor,
            artifact=packet,
        )
        if not used_setup_format:
            log_event(
                "wow_format_repaired",
                run_id=run_id,
                status=LedgerEvent.Status.SUCCEEDED,
                entity_type="wow",
                entity_id=packet.id,
                raw_email=raw_email,
                investor=investor,
                artifact=packet,
                details={
                    "message": "Packet was parseable after deterministic format tolerance; receipt should remind sender to use setup page format."
                },
            )
        log_event(
            "db_record_created",
            run_id=run_id,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=raw_email,
            investor=investor,
            artifact=packet,
        )
    return packet


def _uses_current_wow_setup_format(body: str) -> bool:
    required = (
        "## 1. Reading Log",
        "## 2. Agent Suggested 3 WoWs",
        "## 3. User Selection / Pass",
        "selected_wow_id:",
    )
    return all(value in body for value in required)


def _mark_parse_failed(raw_email: RawEmail, *, run_id: uuid.UUID, message: str, event_name: str, investor=None) -> None:
    raw_email.processing_status = RawEmail.ProcessingStatus.FAILED
    raw_email.error_message = message
    raw_email.save(update_fields=["processing_status", "error_message", "updated_at"])
    log_event(
        event_name,
        run_id=run_id,
        status=LedgerEvent.Status.FAILED,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        investor=investor,
        error_code="parse_error",
        error_message=message,
    )


def _mark_wow_format_fix_needed(raw_email: RawEmail, *, run_id: uuid.UUID, message: str, investor=None) -> None:
    raw_email.processing_status = RawEmail.ProcessingStatus.NEEDS_FORMAT_FIX
    raw_email.error_message = message
    raw_email.save(update_fields=["processing_status", "error_message", "updated_at"])
    log_event(
        "wow_format_fix_needed",
        run_id=run_id,
        status=LedgerEvent.Status.FAILED,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        investor=investor,
        error_code="wow_format_error",
        error_message=message,
    )
