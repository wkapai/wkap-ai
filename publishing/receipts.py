from __future__ import annotations

import uuid

from django.conf import settings
from django.utils import timezone

from core.events import log_event
from ingestion.gmail import send_gmail_message
from ingestion.models import RawEmail
from ledger.models import DailyWoWPacket, LedgerEvent, RadarIssue


def radar_receipt_subject(issue: RadarIssue) -> str:
    return f"WKAP Ledger receipt: Radar Feed logged for {issue.market_date}"


def radar_receipt_body(issue: RadarIssue) -> str:
    return "\n".join(
        [
            "Your WKAP Radar Feed has been logged on WKAP.",
            "",
            f"Market date: {issue.market_date}",
            f"Title: {issue.title}",
            "",
            "Radar URL:",
            issue.canonical_url,
            "",
            "Content SHA256:",
            issue.content_sha256 or "pending",
            "",
            "Manifest URL:",
            issue.manifest_url or "pending",
            "",
            "Proof status:",
            issue.ots_status or "pending",
            "",
            "WKAP publishes the Radar page, proof metadata, and agent-readable facts as a durable public ledger artifact.",
            "",
            "- WKAP",
        ]
    )


def wow_receipt_subject(packet: DailyWoWPacket) -> str:
    return f"WKAP Ledger receipt: Daily WoW logged for {packet.market_date}"


def wow_format_fix_subject(raw_email: RawEmail) -> str:
    return "WKAP Ledger received your Daily WoW Packet - format fix needed"


def wow_format_fix_body(raw_email: RawEmail) -> str:
    return "\n".join(
        [
            "WKAP received your Daily WoW Packet, but it was not published yet because the format could not be parsed.",
            "",
            "What happened:",
            raw_email.error_message or "The packet is missing one or more required fields.",
            "",
            "Your raw email was saved, so the submission was not lost.",
            "",
            "Please resend using the current setup prompt format:",
            f"{settings.WKAP_BASE_URL}/submit-to-wkap-ledger.html",
            "",
            "Minimum required sections:",
            "1. Reading Log",
            "2. Agent Suggested WoW Signals",
            "3. User Selection / Pass",
            "",
            "Minimum required selection field:",
            "selected_wow_id: WOW-[date]-001 / WOW-[date]-002 / WOW-[date]-003 / none",
            "",
            "If selected_wow_id is none, also include:",
            "closest_rejected_idea:",
            "why_pass:",
            "missing_evidence:",
            "",
            "- WKAP",
        ]
    )


def wow_receipt_body(packet: DailyWoWPacket) -> str:
    selected = packet.suggested_wows.filter(wow_id=packet.selected_wow_id).first()
    selection_status = "pass" if packet.selected_wow_id.lower() == "none" else "selected"
    selected_theme = selected.ticker_or_theme if selected else packet.closest_rejected_idea or "Daily WoW Packet"
    lines = [
        f"Your Daily WoW Packet has been logged on WKAP.",
        "",
        f"Investor log: {packet.investor.public_label}",
        f"Market date: {packet.market_date}",
        f"Selection status: {selection_status}",
        f"Selected WoW ID: {packet.selected_wow_id or 'none'}",
        f"Theme: {selected_theme}",
        "",
        f"WoW URL:",
        packet.canonical_url,
        "",
        f"Content SHA256:",
        packet.content_sha256 or "pending",
        "",
        f"Raw email SHA256:",
        packet.raw_email_sha256 or "pending",
        "",
        f"Proof status:",
        packet.ots_status or "pending",
        "",
        "Your email address stays private. WKAP publishes the ledger page, proof metadata, and agent-readable facts, not your private sender address.",
        "",
    ]
    if _wow_packet_was_format_repaired(packet):
        lines.extend(
            [
                "Format note:",
                "WKAP was able to repair and publish this packet, but please use the setup-page format for future Daily WoW Packets:",
                f"{settings.WKAP_BASE_URL}/submit-to-wkap-ledger.html",
                "",
            ]
        )
    lines.extend(
        [
            "Keep the rep small: one market day, one WoW, one logged judgment.",
            "",
            "- WKAP",
        ]
    )
    return "\n".join(lines)


def send_wow_receipt(packet: DailyWoWPacket, *, run_id: uuid.UUID, force: bool = False) -> DailyWoWPacket:
    if packet.receipt_email_sent_at and not force:
        log_event(
            "receipt_email_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=packet.source_email,
            investor=packet.investor,
            artifact=packet,
            details={"reason": "already_sent", "receipt_email_message_id": packet.receipt_email_message_id},
        )
        return packet

    if not settings.WKAP_SEND_RECEIPTS:
        log_event(
            "receipt_email_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=packet.source_email,
            investor=packet.investor,
            artifact=packet,
            details={"reason": "WKAP_SEND_RECEIPTS=false", "preview": wow_receipt_body(packet)},
        )
        return packet

    log_event(
        "receipt_email_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type="wow",
        entity_id=packet.id,
        raw_email=packet.source_email,
        investor=packet.investor,
        artifact=packet,
        details={"to": packet.investor.email_private, "subject": wow_receipt_subject(packet)},
    )
    try:
        message_id = send_gmail_message(
            to_email=packet.investor.email_private,
            subject=wow_receipt_subject(packet),
            body_text=wow_receipt_body(packet),
        )
    except Exception as exc:
        packet.receipt_email_error = str(exc)
        packet.save(update_fields=["receipt_email_error", "updated_at"])
        log_event(
            "receipt_email_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=packet.source_email,
            investor=packet.investor,
            artifact=packet,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        raise

    packet.receipt_email_sent_at = timezone.now()
    packet.receipt_email_message_id = message_id
    packet.receipt_email_error = ""
    packet.save(update_fields=["receipt_email_sent_at", "receipt_email_message_id", "receipt_email_error", "updated_at"])
    log_event(
        "receipt_email_sent",
        run_id=run_id,
        entity_type="wow",
        entity_id=packet.id,
        raw_email=packet.source_email,
        investor=packet.investor,
        artifact=packet,
        details={"receipt_email_message_id": message_id, "to": packet.investor.email_private},
    )
    return packet


def _wow_packet_was_format_repaired(packet: DailyWoWPacket) -> bool:
    return LedgerEvent.objects.filter(
        event_name="wow_format_repaired",
        entity_type="wow",
        entity_id=str(packet.id),
    ).exists()


def send_wow_format_fix_receipt(raw_email: RawEmail, *, run_id: uuid.UUID) -> RawEmail:
    if not settings.WKAP_SEND_RECEIPTS:
        log_event(
            "format_fix_receipt_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="raw_email",
            entity_id=raw_email.id,
            raw_email=raw_email,
            details={"reason": "WKAP_SEND_RECEIPTS=false", "preview": wow_format_fix_body(raw_email)},
        )
        return raw_email

    log_event(
        "format_fix_receipt_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        details={"to": raw_email.sender_email, "subject": wow_format_fix_subject(raw_email)},
    )
    try:
        message_id = send_gmail_message(
            to_email=raw_email.sender_email,
            subject=wow_format_fix_subject(raw_email),
            body_text=wow_format_fix_body(raw_email),
        )
    except Exception as exc:
        log_event(
            "format_fix_receipt_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            entity_type="raw_email",
            entity_id=raw_email.id,
            raw_email=raw_email,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        raise

    log_event(
        "format_fix_receipt_sent",
        run_id=run_id,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        details={"receipt_email_message_id": message_id, "to": raw_email.sender_email},
    )
    return raw_email


def send_radar_receipt(issue: RadarIssue, *, run_id: uuid.UUID, force: bool = False) -> RadarIssue:
    if issue.receipt_email_sent_at and not force:
        log_event(
            "receipt_email_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="radar",
            entity_id=issue.id,
            raw_email=issue.source_email,
            artifact=issue,
            details={"reason": "already_sent", "receipt_email_message_id": issue.receipt_email_message_id},
        )
        return issue

    if not settings.WKAP_SEND_RECEIPTS:
        log_event(
            "receipt_email_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="radar",
            entity_id=issue.id,
            raw_email=issue.source_email,
            artifact=issue,
            details={"reason": "WKAP_SEND_RECEIPTS=false", "preview": radar_receipt_body(issue)},
        )
        return issue

    log_event(
        "receipt_email_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type="radar",
        entity_id=issue.id,
        raw_email=issue.source_email,
        artifact=issue,
        details={"to": issue.source_email.sender_email, "subject": radar_receipt_subject(issue)},
    )
    try:
        message_id = send_gmail_message(
            to_email=issue.source_email.sender_email,
            subject=radar_receipt_subject(issue),
            body_text=radar_receipt_body(issue),
        )
    except Exception as exc:
        issue.receipt_email_error = str(exc)
        issue.save(update_fields=["receipt_email_error", "updated_at"])
        log_event(
            "receipt_email_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            entity_type="radar",
            entity_id=issue.id,
            raw_email=issue.source_email,
            artifact=issue,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        raise

    issue.receipt_email_sent_at = timezone.now()
    issue.receipt_email_message_id = message_id
    issue.receipt_email_error = ""
    issue.save(update_fields=["receipt_email_sent_at", "receipt_email_message_id", "receipt_email_error", "updated_at"])
    log_event(
        "receipt_email_sent",
        run_id=run_id,
        entity_type="radar",
        entity_id=issue.id,
        raw_email=issue.source_email,
        artifact=issue,
        details={"receipt_email_message_id": message_id, "to": issue.source_email.sender_email},
    )
    return issue
