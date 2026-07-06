from __future__ import annotations

import uuid

from django.db import migrations


ITEM_EVENT = "wow_lifecycle_item_logged"
STATUS_UPDATE_EVENT = "wow_lifecycle_status_update_logged"


def backfill_wow_lifecycle_events(apps, schema_editor):
    DailyWoWPacket = apps.get_model("ledger", "DailyWoWPacket")
    LedgerEvent = apps.get_model("ledger", "LedgerEvent")

    for packet in DailyWoWPacket.objects.select_related("investor", "source_email").all():
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"wkap-wow-lifecycle-backfill-{packet.pk}")
        investor_id = getattr(packet.investor, "investor_id", "") if packet.investor_id else ""
        raw_email = packet.source_email
        for index, item in enumerate(packet.wow_items_json or [], start=1):
            if not isinstance(item, dict):
                continue
            wow_id = str(item.get("wow_id") or "").strip()
            if not wow_id:
                continue
            wow_type = str(item.get("wow_type") or "candidate_wow").strip()
            event_name = STATUS_UPDATE_EVENT if wow_type == "status_update" else ITEM_EVENT
            if LedgerEvent.objects.filter(
                entity_type="wow",
                entity_id=str(packet.pk),
                event_name=event_name,
                details__wow_id=wow_id,
            ).exists():
                continue
            LedgerEvent.objects.create(
                event_name=event_name,
                entity_type="wow",
                entity_id=str(packet.pk),
                run_id=run_id,
                status="succeeded",
                environment="migration",
                gmail_message_id=getattr(raw_email, "gmail_message_id", "") or "",
                sender_email=getattr(raw_email, "sender_email", "") or "",
                investor_id=investor_id,
                market_date=packet.market_date,
                content_hash=packet.content_sha256 or "",
                canonical_url=packet.canonical_url or "",
                github_file_url=packet.github_file_url or "",
                github_commit_sha=packet.github_commit_sha or "",
                ots_status=packet.ots_status or "",
                details=_record(item, index=index, packet_id=packet.packet_id, investor_id=investor_id),
            )


def _record(item: dict, *, index: int, packet_id: str, investor_id: str) -> dict:
    wow_type = str(item.get("wow_type") or "candidate_wow").strip()
    if wow_type == "status_update":
        return {
            "packet_id": packet_id,
            "item_number": index,
            "wow_id": str(item.get("wow_id") or "").strip(),
            "wow_type": "status_update",
            "investor_id": str(item.get("investor_id") or item.get("author_id") or investor_id).strip(),
            "target_wow_id": str(item.get("target_wow_id") or "").strip(),
            "target_root_wow_id": str(item.get("target_root_wow_id") or "").strip(),
            "update_type": str(item.get("update_type") or "other").strip(),
            "previous_status": str(item.get("previous_status") or "").strip(),
            "new_status": str(item.get("new_status") or item.get("signal_status") or item.get("trackable_status") or "").strip(),
            "signal_status": str(item.get("signal_status") or "").strip(),
            "trackable_status": str(item.get("trackable_status") or "").strip(),
            "resolution_source_used": str(item.get("resolution_source_used") or "").strip(),
            "evidence_summary": str(item.get("evidence_summary") or "").strip(),
            "update_summary": str(item.get("update_summary") or "").strip(),
            "lineage_node": False,
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "source_refs": _list_value(item.get("source_refs")),
        }
    return {
        "packet_id": packet_id,
        "item_number": index,
        "wow_id": str(item.get("wow_id") or "").strip(),
        "wow_type": wow_type,
        "investor_id": str(item.get("investor_id") or item.get("author_id") or investor_id).strip(),
        "parent_wow_id": str(item.get("parent_wow_id") or "").strip(),
        "root_wow_id": str(item.get("root_wow_id") or "").strip(),
        "scoreable": bool(item.get("scoreable")),
        "accuracy_endpoint_eligible": bool(item.get("accuracy_endpoint_eligible")),
        "signal_status": str(item.get("signal_status") or "").strip(),
        "trackable_status": str(item.get("trackable_status") or "").strip(),
        "thesis_status": str(item.get("thesis_status") or "").strip(),
        "claim": str(item.get("claim") or item.get("observation") or item.get("thesis_claim") or item.get("summary") or "").strip(),
        "source_refs": _list_value(item.get("source_refs")),
    }


def _list_value(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if value is None:
        return []
    return [str(value)]


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0009_wow_packet_v01_flexible_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_wow_lifecycle_events, migrations.RunPython.noop),
    ]
