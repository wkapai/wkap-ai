from __future__ import annotations

import uuid

from core.events import log_event
from ledger.models import DailyWoWPacket
from ledger.wow_lifecycle import lifecycle_event_name, lifecycle_records


def ensure_wow_lifecycle_events(packet: DailyWoWPacket, *, run_id: uuid.UUID) -> int:
    created = 0
    investor = packet.investor
    raw_email = packet.source_email
    for record in lifecycle_records(packet.wow_items_json, investor_id=investor.investor_id, packet_id=packet.packet_id):
        wow_id = str(record.get("wow_id") or "")
        if not wow_id:
            continue
        event_name = lifecycle_event_name(record)
        exists = packet_events_exist(packet, event_name=event_name, wow_id=wow_id)
        if exists:
            continue
        log_event(
            event_name,
            run_id=run_id,
            entity_type="wow",
            entity_id=packet.id,
            raw_email=raw_email,
            investor=investor,
            artifact=packet,
            details=record,
        )
        created += 1
    return created


def packet_events_exist(packet: DailyWoWPacket, *, event_name: str, wow_id: str) -> bool:
    from ledger.models import LedgerEvent

    return LedgerEvent.objects.filter(
        entity_type="wow",
        entity_id=str(packet.id),
        event_name=event_name,
        details__wow_id=wow_id,
    ).exists()
