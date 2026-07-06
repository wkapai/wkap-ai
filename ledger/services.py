from __future__ import annotations

import uuid
import hashlib
from copy import deepcopy

from django.db import transaction

from core.events import log_event
from ingestion.models import RawEmail
from ingestion.services import ensure_radar_authorized
from ledger.investor_id import find_or_create_investor, set_investor_display_name_from_subject
from ledger.lifecycle_events import ensure_wow_lifecycle_events
from ledger.models import AgentSuggestedWoW, DailyWoWPacket, LedgerEvent, RadarIssue, ReadingLogItem
from ledger.parsers import ParseError, parse_radar, parse_wow
from ledger.wow_contract import local_wow_id, public_wow_id


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
                "receipt_email_sent_at": None,
                "receipt_email_message_id": "",
                "receipt_email_error": "",
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
        parsed = parse_wow(raw_email, assigned_investor_id=investor.investor_id)
    except ParseError as exc:
        _mark_wow_format_fix_needed(raw_email, run_id=run_id, message=str(exc), investor=investor)
        raise

    canonical_packet_id = f"WKAP-{investor.investor_id}-{parsed.market_date}"
    raw_packet_json = _canonical_raw_packet_json(
        parsed.raw_packet_json,
        investor_id=investor.investor_id,
        packet_id=canonical_packet_id,
    )
    agent_facts_json = _canonical_agent_facts_json(
        parsed.agent_facts_json,
        investor_id=investor.investor_id,
        packet_id=canonical_packet_id,
    )
    wow_items_json = _canonical_wow_items_json(parsed.wow_items_json, investor_id=investor.investor_id)

    with transaction.atomic():
        packet, _ = DailyWoWPacket.objects.update_or_create(
            investor=investor,
            market_date=parsed.market_date,
            defaults={
                "format_version": parsed.format_version,
                "packet_id": canonical_packet_id,
                "packet_spec_version": parsed.packet_spec_version,
                "packet_spec_url": parsed.packet_spec_url,
                "skill_version": parsed.skill_version,
                "skill_url": parsed.skill_url,
                "selected_wow_id": parsed.selected_wow_id,
                "reason_for_selection": parsed.reason_for_selection,
                "closest_rejected_idea": parsed.closest_rejected_idea,
                "why_pass": parsed.why_pass,
                "missing_evidence": parsed.missing_evidence,
                "human_title": parsed.human_title,
                "human_summary": parsed.human_summary,
                "raw_packet_json": raw_packet_json,
                "agent_facts_json": agent_facts_json,
                "validation_results_json": parsed.validation_results_json,
                "wow_items_json": wow_items_json,
                "wow_count": parsed.wow_count,
                "scoreable_count": parsed.scoreable_count,
                "trackable_count": parsed.trackable_count,
                "thesis_count": parsed.thesis_count,
                "candidate_count": parsed.candidate_count,
                "status_update_count": parsed.status_update_count,
                "public_status": "published_on_wkap",
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
        ensure_wow_lifecycle_events(packet, run_id=run_id)
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


def _canonical_raw_packet_json(raw_packet_json: dict, *, investor_id: str, packet_id: str) -> dict:
    packet = deepcopy(raw_packet_json) if isinstance(raw_packet_json, dict) else {}
    packet["packet_id"] = packet_id
    packet.pop("author_id", None)
    packet["investor_id"] = investor_id
    if isinstance(packet.get("agent_facts"), dict):
        packet["agent_facts"]["packet_id"] = packet_id
        packet["agent_facts"].pop("author_id", None)
        packet["agent_facts"]["investor_id"] = investor_id
    if isinstance(packet.get("human_view"), dict) and isinstance(packet["human_view"].get("top_wows"), list):
        packet["human_view"]["top_wows"] = [
            _canonical_public_wow_id(value, investor_id=investor_id) for value in packet["human_view"]["top_wows"]
        ]
    if isinstance(packet.get("selection"), dict):
        for field in ("selected_wow_id", "closest_rejected_wow", "closest_rejected_idea"):
            if packet["selection"].get(field):
                packet["selection"][field] = _canonical_public_wow_id(packet["selection"][field], investor_id=investor_id)
    if isinstance(packet.get("wow_items"), list):
        packet["wow_items"] = _canonical_wow_items_json(packet["wow_items"], investor_id=investor_id)
    return packet


def _canonical_agent_facts_json(agent_facts_json: dict, *, investor_id: str, packet_id: str) -> dict:
    agent_facts = deepcopy(agent_facts_json) if isinstance(agent_facts_json, dict) else {}
    agent_facts["packet_id"] = packet_id
    agent_facts.pop("author_id", None)
    agent_facts["investor_id"] = investor_id
    return agent_facts


def _canonical_wow_items_json(wow_items_json: list, *, investor_id: str) -> list[dict]:
    items = deepcopy(wow_items_json) if isinstance(wow_items_json, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        item.pop("author_id", None)
        if str(item.get("wow_type") or "") == "status_update":
            item["investor_id"] = investor_id
        for field in ("wow_id", "parent_wow_id", "root_wow_id", "target_wow_id", "target_root_wow_id"):
            if item.get(field):
                item[field] = _canonical_public_wow_id(item[field], investor_id=investor_id)
        agent_facts = item.get("agent_facts")
        if isinstance(agent_facts, dict):
            agent_facts.pop("author_id", None)
            for field in ("target_wow_id", "target_root_wow_id"):
                if agent_facts.get(field):
                    agent_facts[field] = _canonical_public_wow_id(agent_facts[field], investor_id=investor_id)
    return items


def _canonical_public_wow_id(value, *, investor_id: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return text
    return public_wow_id(investor_id, local_wow_id(text))


def _uses_current_wow_setup_format(body: str) -> bool:
    required = (
        "## 1. Reading Log",
        "## 2. Agent Suggested WoW Signals",
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
