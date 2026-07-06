from __future__ import annotations

import json

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


SOURCE_PATH = "specs/source/wow_protocol_v0_2.yaml"
CRM_PATH = "specs/public/wow-crm-v0.2.json"
INTAKE_PATH = "specs/public/wow-intake-flow-v0.2.json"
DAILY_STATE_PATH = "specs/public/daily-wow-state-v0.2.schema.json"
PACKET_SPEC_PATH = "specs/public/wow-packet-v0.2.md"
SKILL_SPEC_PATH = "specs/public/wkap-wow-skill-v0.2.md"


class Command(BaseCommand):
    help = "Build or check generated WKAP WoW protocol JSON specs from one source file."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Fail if generated protocol specs differ from committed files.")

    def handle(self, *args, **options):
        source = _load_source()
        generated = _generated_files(source)
        drift = []
        for relative_path, expected in generated.items():
            path = settings.BASE_DIR / relative_path
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != expected:
                drift.append(relative_path)
                if not options["check"]:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(expected, encoding="utf-8")

        markdown_errors = _markdown_contract_errors(source)
        if options["check"] and (drift or markdown_errors):
            messages = []
            if drift:
                messages.append("Generated protocol files are stale: " + ", ".join(drift))
            messages.extend(markdown_errors)
            raise CommandError("; ".join(messages))
        if markdown_errors:
            raise CommandError("; ".join(markdown_errors))

        status = "checked" if options["check"] else "built"
        self.stdout.write(self.style.SUCCESS(f"WKAP WoW protocol {status}: {len(generated)} generated JSON files."))


def _load_source() -> dict:
    path = settings.BASE_DIR / SOURCE_PATH
    if not path.exists():
        raise CommandError(f"Missing protocol source: {SOURCE_PATH}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _generated_files(source: dict) -> dict[str, str]:
    return {
        CRM_PATH: _json_text(_crm_spec(source)),
        INTAKE_PATH: _json_text(_intake_spec(source)),
        DAILY_STATE_PATH: _json_text(_daily_state_schema(source)),
    }


def _crm_spec(source: dict) -> dict:
    urls = source["urls"]
    crm = source["crm"]
    return {
        "protocol": "wkap-wow-crm",
        "version": source["protocol_version"],
        "latest_url": urls["wow_crm_latest"],
        "packet_spec_url": urls["wow_packet_latest"],
        "intake_flow_url": urls["wow_intake_flow_latest"],
        "daily_state_schema_url": urls["daily_wow_state_latest"],
        "principle": crm["principle"],
        "wow_types": crm["wow_types"],
        "allowed_status_transitions": crm["allowed_status_transitions"],
        "update_type_to_new_status": crm["update_type_to_new_status"],
        "selection_rules": crm["selection_rules"],
        "backend_behavior": crm["backend_behavior"],
    }


def _intake_spec(source: dict) -> dict:
    urls = source["urls"]
    intake = source["intake_flow"]
    return {
        "protocol": "wkap-wow-intake-flow",
        "version": source["protocol_version"],
        "latest_url": urls["wow_intake_flow_latest"],
        "crm_spec_url": urls["wow_crm_latest"],
        "goal": intake["goal"],
        "states": intake["states"],
        "normalization_rules": intake["normalization_rules"],
        "submission_rules": intake["submission_rules"],
    }


def _daily_state_schema(source: dict) -> dict:
    version = source["protocol_version"]
    daily_state = source["daily_state"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://wkap.ai/specs/daily-wow-state-v0.2.schema.json",
        "title": "WKAP Daily WoW State v0.2",
        "type": "object",
        "required": ["version", "market_date", "investor_id", "state", "reading_log", "wow_options", "selection"],
        "additionalProperties": False,
        "properties": {
            "version": {"const": version},
            "market_date": {"type": "string", "format": "date"},
            "investor_id": {"type": "string", "minLength": 1},
            "journal_path": {"type": "string"},
            "state": {"type": "string", "enum": daily_state["states"]},
            "reading_log": {
                "type": "array",
                "maxItems": daily_state["max_reading_items"],
                "items": {
                    "type": "object",
                    "required": ["item_number", "source_title", "source_url", "source_type", "reading_origin", "agent_summary"],
                    "additionalProperties": True,
                    "properties": {
                        "item_number": {"type": "integer", "minimum": 1},
                        "source_title": {"type": "string"},
                        "source_url": {"type": "string"},
                        "source_type": {"type": "string", "enum": daily_state["source_type_values"]},
                        "published_time": {"type": "string"},
                        "tickers": {"type": "array", "items": {"type": "string"}},
                        "themes": {"type": "array", "items": {"type": "string"}},
                        "reading_origin": {"type": "string", "enum": daily_state["reading_origin_values"]},
                        "agent_summary": {"type": "string"},
                    },
                },
            },
            "wow_options": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "object", "required": daily_state["wow_option_required_fields"], "additionalProperties": True},
            },
            "selection": {
                "type": "object",
                "required": ["selected_wow_id", "reason_for_selection", "reason_for_pass", "closest_rejected_wow", "missing_evidence"],
                "additionalProperties": False,
                "properties": {
                    "selected_wow_id": {"type": "string"},
                    "reason_for_selection": {"type": "string"},
                    "reason_for_pass": {"type": "string"},
                    "closest_rejected_wow": {"type": "string"},
                    "missing_evidence": {"type": "string"},
                },
            },
            "validation_errors": {"type": "array", "items": {"type": "string"}},
            "public_url": {"type": "string"},
            "receipt_status": {"type": "string"},
        },
    }


def _markdown_contract_errors(source: dict) -> list[str]:
    errors = []
    required = [
        source["protocol_version"],
        source["mismatch_policy"],
        source["urls"]["wow_crm_latest"],
        source["urls"]["wow_intake_flow_latest"],
        source["urls"]["daily_wow_state_latest"],
    ]
    for relative_path in (PACKET_SPEC_PATH, SKILL_SPEC_PATH):
        body = (settings.BASE_DIR / relative_path).read_text(encoding="utf-8")
        missing = [value for value in required if value not in body]
        if missing:
            errors.append(f"{relative_path} missing protocol source values: {', '.join(missing)}")
    return errors


def _json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
