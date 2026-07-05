from __future__ import annotations

import json
from collections.abc import Iterable

from ledger.wow_contract import public_wow_id


STATUS_UPDATE_EVENT = "wow_lifecycle_status_update_logged"
ITEM_EVENT = "wow_lifecycle_item_logged"


def lifecycle_records(wow_items: Iterable[dict], *, investor_id: str = "", packet_id: str = "") -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, item in enumerate(wow_items or [], start=1):
        if not isinstance(item, dict):
            continue
        wow_type = str(item.get("wow_type") or "candidate_wow").strip()
        wow_id = str(item.get("wow_id") or "").strip()
        agent_facts = item.get("agent_facts") if isinstance(item.get("agent_facts"), dict) else {}
        if wow_type == "status_update":
            records.append(_status_update_record(item, agent_facts, index=index, investor_id=investor_id, packet_id=packet_id))
        else:
            records.append(_item_record(item, agent_facts, index=index, investor_id=investor_id, packet_id=packet_id))
        if wow_id and investor_id:
            records[-1]["public_wow_id"] = public_wow_id(investor_id, wow_id)
    return records


def status_update_records(wow_items: Iterable[dict], *, investor_id: str = "", packet_id: str = "") -> list[dict[str, object]]:
    return [record for record in lifecycle_records(wow_items, investor_id=investor_id, packet_id=packet_id) if record.get("wow_type") == "status_update"]


def lifecycle_records_json(wow_items: Iterable[dict], *, investor_id: str = "", packet_id: str = "") -> str:
    return json.dumps(lifecycle_records(wow_items, investor_id=investor_id, packet_id=packet_id), ensure_ascii=False, sort_keys=True)


def lifecycle_event_name(record: dict[str, object]) -> str:
    return STATUS_UPDATE_EVENT if record.get("wow_type") == "status_update" else ITEM_EVENT


def _item_record(item: dict, agent_facts: dict, *, index: int, investor_id: str, packet_id: str) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "item_number": index,
        "wow_id": _value(item, "wow_id"),
        "wow_type": _value(item, "wow_type", default="candidate_wow"),
        "author_id": _value(item, "author_id", default=investor_id),
        "parent_wow_id": _value(item, "parent_wow_id"),
        "root_wow_id": _value(item, "root_wow_id"),
        "scoreable": _bool_value(item, "scoreable"),
        "accuracy_endpoint_eligible": _bool_value(item, "accuracy_endpoint_eligible"),
        "signal_status": _value(item, "signal_status"),
        "trackable_status": _value(item, "trackable_status"),
        "thesis_status": _value(item, "thesis_status"),
        "claim": _value(item, "claim", "observation", "thesis_claim", "summary"),
        "source_refs": _list_value(item.get("source_refs")),
        "agent_facts": agent_facts,
    }


def _status_update_record(item: dict, agent_facts: dict, *, index: int, investor_id: str, packet_id: str) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "item_number": index,
        "wow_id": _value(item, "wow_id"),
        "wow_type": "status_update",
        "author_id": _value(item, "author_id", default=investor_id),
        "target_wow_id": _value(item, "target_wow_id"),
        "target_root_wow_id": _value(item, "target_root_wow_id"),
        "update_type": _value(item, "update_type", default="other"),
        "previous_status": _value(item, "previous_status"),
        "new_status": _value(item, "new_status", "signal_status", "trackable_status"),
        "signal_status": _value(item, "signal_status"),
        "trackable_status": _value(item, "trackable_status"),
        "resolution_source_used": _value(item, "resolution_source_used"),
        "evidence_summary": _value(item, "evidence_summary"),
        "update_summary": _value(item, "update_summary"),
        "lineage_node": False,
        "scoreable": False,
        "accuracy_endpoint_eligible": False,
        "source_refs": _list_value(item.get("source_refs")),
        "agent_facts": agent_facts,
    }


def _value(item: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _bool_value(item: dict, key: str) -> bool:
    return bool(item.get(key))


def _list_value(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if value is None:
        return []
    return [str(value)]
