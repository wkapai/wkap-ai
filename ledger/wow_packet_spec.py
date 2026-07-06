from __future__ import annotations

import json

from django.conf import settings


def current_spec() -> dict:
    daily_state = json.loads((settings.BASE_DIR / "specs/public/daily-wow-state-v0.2.schema.json").read_text(encoding="utf-8"))
    crm = json.loads((settings.BASE_DIR / "specs/public/wow-crm-v0.2.json").read_text(encoding="utf-8"))
    return {
        "current_version": "v0.2",
        "format_version": "wow_packet_v0.2",
        "schema_data": {
            "format_version": "wow_packet_v0.2",
            "reading_log_rules": {"max_items": daily_state["properties"]["reading_log"]["maxItems"]},
            "source_type_values": daily_state["properties"]["reading_log"]["items"]["properties"]["source_type"]["enum"],
            "reading_origin_values": daily_state["properties"]["reading_log"]["items"]["properties"]["reading_origin"]["enum"],
            "suggested_wow_rules": {"required_count": daily_state["properties"]["wow_options"]["minItems"]},
            "crm": crm,
        },
    }
