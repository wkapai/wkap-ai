from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings

from ledger.models import LedgerEvent


def new_run_id() -> uuid.UUID:
    return uuid.uuid4()


def log_event(
    event_name: str,
    *,
    run_id: uuid.UUID,
    status: str = LedgerEvent.Status.SUCCEEDED,
    entity_type: str = "",
    entity_id: str | int | None = "",
    raw_email=None,
    investor=None,
    artifact=None,
    error_code: str = "",
    error_message: str = "",
    details: dict[str, Any] | None = None,
) -> LedgerEvent:
    market_date = getattr(artifact, "market_date", None)
    return LedgerEvent.objects.create(
        event_name=event_name,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        run_id=run_id,
        status=status,
        environment=getattr(settings, "WKAP_ENVIRONMENT", "local"),
        gmail_message_id=getattr(raw_email, "gmail_message_id", "") or "",
        sender_email=getattr(raw_email, "sender_email", "") or "",
        investor_id=getattr(investor, "investor_id", "")
        or getattr(getattr(artifact, "investor", None), "investor_id", "")
        or "",
        market_date=market_date,
        content_hash=getattr(artifact, "content_sha256", "") or "",
        canonical_url=getattr(artifact, "canonical_url", "") or "",
        github_file_url=getattr(artifact, "github_file_url", "") or "",
        github_commit_sha=getattr(artifact, "github_commit_sha", "") or "",
        ots_status=getattr(artifact, "ots_status", "") or "",
        error_code=error_code,
        error_message=error_message,
        details=details or {},
    )
