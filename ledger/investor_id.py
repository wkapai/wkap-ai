from __future__ import annotations

import re

from django.db import transaction

from core.events import log_event
from ledger.models import Investor

INVESTOR_ID_START = 202


def find_or_create_investor(email: str, *, run_id) -> tuple[Investor, bool]:
    normalized = email.lower().strip()
    with transaction.atomic():
        existing = Investor.objects.filter(email_private=normalized).first()
        if existing:
            log_event("investor_found", run_id=run_id, entity_type="investor", entity_id=existing.id, investor=existing)
            return existing, False

        investor = Investor.objects.create(email_private=normalized, investor_id=next_investor_id_locked())
        log_event("investor_created", run_id=run_id, entity_type="investor", entity_id=investor.id, investor=investor)
        log_event("investor_id_assigned", run_id=run_id, entity_type="investor", entity_id=investor.id, investor=investor)
        return investor, True


def display_name_from_wow_subject(subject: str) -> str:
    match = re.search(r"daily\s+wow\s+packet\s*-\s*\d{4}-\d{2}-\d{2}\s*-\s*(.+)$", subject or "", flags=re.IGNORECASE)
    if not match:
        return ""
    name = re.sub(r"\s+", " ", match.group(1)).strip()
    if "@" in name:
        return ""
    return name[:120]


def set_investor_display_name_from_subject(investor: Investor, subject: str) -> None:
    display_name = display_name_from_wow_subject(subject)
    if display_name and not investor.display_name:
        investor.display_name = display_name
        investor.save(update_fields=["display_name"])


def next_investor_id_locked() -> str:
    values = list(Investor.objects.select_for_update().values_list("investor_id", flat=True))
    numeric = [int(investor_id[1:]) for investor_id in values if investor_id.startswith("w") and investor_id[1:].isdigit()]
    next_number = max(numeric, default=INVESTOR_ID_START - 1) + 1
    return f"w{next_number:04d}"
