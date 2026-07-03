from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings


def spec_root() -> Path:
    return settings.BASE_DIR / "specs" / "wow_packet"


def current_spec() -> dict:
    pointer = json.loads((spec_root() / "current.json").read_text(encoding="utf-8"))
    schema_path = settings.BASE_DIR / pointer["schema"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return {**pointer, "schema_data": schema, "format_version": schema["format_version"]}


def current_prompt() -> str:
    pointer = json.loads((spec_root() / "current.json").read_text(encoding="utf-8"))
    return (settings.BASE_DIR / pointer["prompt"]).read_text(encoding="utf-8")
