from __future__ import annotations

import base64
import email.utils
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage

from django.conf import settings


@dataclass(frozen=True)
class GmailMessage:
    gmail_message_id: str
    sender_email: str
    subject: str
    raw_body: str
    received_at: datetime


class GmailNotConfigured(RuntimeError):
    pass


def fetch_gmail_message(gmail_message_id: str) -> GmailMessage:
    service = _gmail_service()
    message = service.users().messages().get(userId=settings.WKAP_GMAIL_ACCOUNT, id=gmail_message_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    sender = email.utils.parseaddr(headers.get("from", ""))[1]
    subject = headers.get("subject", "")
    received_at = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000, tz=timezone.utc)
    body = _payload_text(message.get("payload", {}))
    return GmailMessage(gmail_message_id, sender, subject, body, received_at)


def search_gmail_message_ids(query: str, *, max_results: int = 10) -> list[str]:
    service = _gmail_service()
    response = (
        service.users()
        .messages()
        .list(userId=settings.WKAP_GMAIL_ACCOUNT, q=query, maxResults=max_results)
        .execute()
    )
    return [message["id"] for message in response.get("messages", [])]


def send_gmail_message(*, to_email: str, subject: str, body_text: str) -> str:
    service = _gmail_service()
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = settings.WKAP_RECEIPT_FROM_EMAIL
    message["Subject"] = subject
    message.set_content(body_text)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    response = service.users().messages().send(userId=settings.WKAP_GMAIL_ACCOUNT, body={"raw": raw}).execute()
    return response.get("id", "")


def _gmail_service():
    if not settings.WKAP_GMAIL_CREDENTIALS_FILE or not settings.WKAP_GMAIL_TOKEN_FILE:
        raise GmailNotConfigured(
            "Gmail API credentials are not configured. Set WKAP_GMAIL_CREDENTIALS_FILE and WKAP_GMAIL_TOKEN_FILE."
        )

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_file(settings.WKAP_GMAIL_TOKEN_FILE)
    return build("gmail", "v1", credentials=credentials)


def _payload_text(payload: dict) -> str:
    parts = payload.get("parts") or []
    if parts:
        plain = [_payload_text(part) for part in parts if part.get("mimeType") == "text/plain"]
        html = [_payload_text(part) for part in parts if part.get("mimeType") == "text/html"]
        return "\n".join([text for text in plain or html if text])

    data = payload.get("body", {}).get("data", "")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
