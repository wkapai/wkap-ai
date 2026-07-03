from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import timezone as datetime_timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.events import log_event
from ingestion.gmail import fetch_gmail_message
from ingestion.models import RawEmail
from ledger.parsers import ParseError
from ledger.models import LedgerEvent


RADAR_TERMS = ("wkap radar", "radar feed", "market context")
WOW_TERMS = (
    "daily wow packet",
    "agent suggested 3 wows",
    "suggested wow",
    "reading log",
    "selected_wow_id:",
    "selected wow",
    "worth watching",
)


@dataclass(frozen=True)
class CloudflareEmailPayload:
    message_id: str
    sender_email: str
    recipient_email: str
    subject: str
    raw_body: str
    received_at: object
    raw_mime_sha256: str


def ingest_email(gmail_message_id: str, *, run_id: uuid.UUID) -> RawEmail:
    message = fetch_gmail_message(gmail_message_id)
    with transaction.atomic():
        raw_email, _ = RawEmail.objects.update_or_create(
            gmail_message_id=message.gmail_message_id,
            defaults={
                "sender_email": message.sender_email.lower(),
                "subject": message.subject,
                "raw_body": message.raw_body,
                "received_at": message.received_at,
                "processing_status": RawEmail.ProcessingStatus.SAVED,
            },
        )
        log_event("email_received", run_id=run_id, raw_email=raw_email)
        log_event("raw_email_saved", run_id=run_id, entity_type="raw_email", entity_id=raw_email.id, raw_email=raw_email)
    return raw_email


def ingest_cloudflare_email_payload(payload: dict, *, run_id: uuid.UUID) -> RawEmail:
    parsed = parse_cloudflare_email_payload(payload)
    gmail_message_id = f"cloudflare:{parsed.message_id}"
    with transaction.atomic():
        raw_email, _ = RawEmail.objects.update_or_create(
            gmail_message_id=gmail_message_id,
            defaults={
                "sender_email": parsed.sender_email.lower(),
                "subject": parsed.subject,
                "raw_body": parsed.raw_body,
                "received_at": parsed.received_at,
                "processing_status": RawEmail.ProcessingStatus.SAVED,
            },
        )
        log_event(
            "cloudflare_email_received",
            run_id=run_id,
            entity_type="raw_email",
            entity_id=raw_email.id,
            raw_email=raw_email,
            details={
                "recipient_email": parsed.recipient_email,
                "raw_mime_sha256": parsed.raw_mime_sha256,
            },
        )
        log_event("raw_email_saved", run_id=run_id, entity_type="raw_email", entity_id=raw_email.id, raw_email=raw_email)
    return raw_email


def parse_cloudflare_email_payload(payload: dict) -> CloudflareEmailPayload:
    raw_mime_base64 = str(payload.get("raw_mime_base64") or "")
    if not raw_mime_base64:
        raise ValueError("raw_mime_base64 is required.")

    raw_mime = base64.b64decode(raw_mime_base64, validate=True)
    message = BytesParser(policy=policy.default).parsebytes(raw_mime)
    sender = parseaddr(str(payload.get("from") or message.get("from") or ""))[1]
    recipient = parseaddr(str(payload.get("to") or message.get("to") or ""))[1]
    subject = str(payload.get("subject") or message.get("subject") or "")
    message_id = _cloudflare_message_id(payload, message, raw_mime)
    received_at = _cloudflare_received_at(payload, message)
    raw_body = _message_text_body(message)
    if not raw_body.strip():
        raw_body = raw_mime.decode("utf-8", errors="replace")
    if not sender:
        raise ValueError("Sender email is required.")

    return CloudflareEmailPayload(
        message_id=message_id,
        sender_email=sender,
        recipient_email=recipient,
        subject=subject,
        raw_body=raw_body,
        received_at=received_at,
        raw_mime_sha256=hashlib.sha256(raw_mime).hexdigest(),
    )


def process_raw_email_for_publish(raw_email: RawEmail, *, run_id: uuid.UUID):
    from ledger.services import create_radar_issue, create_wow_submission
    from publishing.receipts import send_wow_format_fix_receipt
    from publishing.services import publish_artifact

    classification = classify_email(raw_email, run_id=run_id)
    if classification == RawEmail.Classification.RADAR:
        issue = create_radar_issue(raw_email, run_id=run_id)
        return publish_artifact("radar", issue.id, run_id=run_id)
    if classification == RawEmail.Classification.WOW:
        try:
            submission = create_wow_submission(raw_email, run_id=run_id)
        except ParseError:
            send_wow_format_fix_receipt(raw_email, run_id=run_id)
            return raw_email
        return publish_artifact("wow", submission.id, run_id=run_id)

    log_event(
        "cloudflare_email_not_published",
        run_id=run_id,
        status=LedgerEvent.Status.SKIPPED,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        details={"classification": classification},
    )
    return raw_email


def classify_email(raw_email: RawEmail, *, run_id: uuid.UUID) -> str:
    text = f"{raw_email.subject}\n{raw_email.raw_body}".lower()
    if any(term in text for term in RADAR_TERMS):
        classification = RawEmail.Classification.RADAR
    elif any(term in text for term in WOW_TERMS):
        classification = RawEmail.Classification.WOW
    elif re.search(r"\b(spam|unsubscribe|casino|lottery)\b", text):
        classification = RawEmail.Classification.SPAM
    else:
        classification = RawEmail.Classification.UNKNOWN

    raw_email.classification = classification
    raw_email.processing_status = RawEmail.ProcessingStatus.CLASSIFIED
    raw_email.error_message = ""
    raw_email.save(update_fields=["classification", "processing_status", "error_message", "updated_at"])
    log_event(
        "email_classified",
        run_id=run_id,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        details={"classification": classification},
    )
    return classification


def _cloudflare_message_id(payload: dict, message, raw_mime: bytes) -> str:
    value = str(payload.get("message_id") or message.get("message-id") or "").strip()
    if value:
        value = value.strip("<>")
    else:
        value = hashlib.sha256(raw_mime).hexdigest()
    return re.sub(r"[^A-Za-z0-9_.:@+-]+", "-", value)[:220]


def _cloudflare_received_at(payload: dict, message):
    value = str(payload.get("received_at") or "").strip()
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            return parsed if parsed.tzinfo else timezone.make_aware(parsed, timezone=datetime_timezone.utc)
        except (TypeError, ValueError):
            pass
    try:
        parsed = parsedate_to_datetime(str(message.get("date") or ""))
        return parsed if parsed.tzinfo else timezone.make_aware(parsed, timezone=datetime_timezone.utc)
    except (TypeError, ValueError):
        return timezone.now()


def _message_text_body(message) -> str:
    if message.is_multipart():
        text_parts = []
        html_parts = []
        for part in message.walk():
            content_disposition = str(part.get_content_disposition() or "")
            if content_disposition == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                text_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(_html_to_text(part.get_content()))
        return "\n\n".join(text_parts or html_parts).strip()
    if message.get_content_type() == "text/html":
        return _html_to_text(message.get_content()).strip()
    return str(message.get_content() or "").strip()


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", html)
    text = re.sub(r"(?i)</\s*p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def ensure_radar_authorized(raw_email: RawEmail, *, run_id: uuid.UUID) -> bool:
    authorized = raw_email.sender_email.lower() in settings.WKAP_RADAR_AUTHORIZED_SENDERS
    if authorized:
        log_event("radar_authorized", run_id=run_id, entity_type="raw_email", entity_id=raw_email.id, raw_email=raw_email)
        return True

    raw_email.processing_status = RawEmail.ProcessingStatus.REJECTED
    raw_email.error_message = "Sender is not authorized to publish WKAP Radar Feed."
    raw_email.save(update_fields=["processing_status", "error_message", "updated_at"])
    log_event(
        "radar_rejected",
        run_id=run_id,
        status=LedgerEvent.Status.REJECTED,
        entity_type="raw_email",
        entity_id=raw_email.id,
        raw_email=raw_email,
        error_code="unauthorized_radar_sender",
        error_message=raw_email.error_message,
    )
    return False
