from django.db import migrations


def clean_wow_identity_json(apps, schema_editor):
    DailyWoWPacket = apps.get_model("ledger", "DailyWoWPacket")
    LedgerEvent = apps.get_model("ledger", "LedgerEvent")

    for packet in DailyWoWPacket.objects.select_related("investor").all():
        investor_id = packet.investor.investor_id
        packet.raw_packet_json = _clean_packet_json(packet.raw_packet_json, investor_id=investor_id)
        packet.agent_facts_json = _clean_facts(packet.agent_facts_json, investor_id=investor_id)
        packet.wow_items_json = _clean_wow_items(packet.wow_items_json, investor_id=investor_id)
        packet.save(update_fields=["raw_packet_json", "agent_facts_json", "wow_items_json", "updated_at"])

    for event in LedgerEvent.objects.filter(entity_type="wow"):
        details = event.details
        if not isinstance(details, dict):
            continue
        investor_id = event.investor_id or str(details.get("investor_id") or details.get("author_id") or "").strip()
        if not investor_id:
            continue
        cleaned = _clean_details(details, investor_id=investor_id)
        if cleaned != details:
            event.details = cleaned
            event.save(update_fields=["details"])


def _clean_packet_json(packet, *, investor_id: str):
    if not isinstance(packet, dict):
        packet = {}
    packet = dict(packet)
    packet.pop("author_id", None)
    packet["investor_id"] = investor_id
    if isinstance(packet.get("agent_facts"), dict):
        packet["agent_facts"] = _clean_facts(packet["agent_facts"], investor_id=investor_id)
    if isinstance(packet.get("wow_items"), list):
        packet["wow_items"] = _clean_wow_items(packet["wow_items"], investor_id=investor_id)
    return packet


def _clean_facts(facts, *, investor_id: str):
    if not isinstance(facts, dict):
        facts = {}
    facts = dict(facts)
    facts.pop("author_id", None)
    facts["investor_id"] = investor_id
    return facts


def _clean_wow_items(items, *, investor_id: str):
    cleaned = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        next_item = dict(item)
        next_item.pop("author_id", None)
        if str(next_item.get("wow_type") or "") == "status_update":
            next_item["investor_id"] = str(next_item.get("investor_id") or investor_id)
        if isinstance(next_item.get("agent_facts"), dict):
            next_item["agent_facts"] = _clean_facts(next_item["agent_facts"], investor_id=investor_id)
        cleaned.append(next_item)
    return cleaned


def _clean_details(details, *, investor_id: str):
    cleaned = dict(details)
    cleaned.pop("author_id", None)
    cleaned["investor_id"] = investor_id
    if isinstance(cleaned.get("agent_facts"), dict):
        cleaned["agent_facts"] = _clean_facts(cleaned["agent_facts"], investor_id=investor_id)
    return cleaned


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0012_alter_dailywowpacket_format_version"),
    ]

    operations = [
        migrations.RunPython(clean_wow_identity_json, migrations.RunPython.noop),
    ]
