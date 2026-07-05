from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse

import yaml
from django.utils import timezone

from ingestion.models import RawEmail
from ledger.wow_contract import local_wow_id
from ledger.wow_packet_spec import current_spec


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedRadar:
    market_date: date
    title: str
    body_text: str


@dataclass(frozen=True)
class ParsedReadingLogItem:
    item_number: int
    source_title: str = ""
    source_url: str = ""
    source_type: str = ""
    published_time: str = ""
    tickers_or_themes: str = ""
    reading_origin: str = ""
    agent_summary: str = ""


@dataclass(frozen=True)
class ParsedAgentSuggestedWoW:
    item_number: int
    wow_id: str
    source_refs: str = ""
    ticker_or_theme: str = ""
    whats_worth_watching: str = ""
    why_now: str = ""
    evidence_to_watch_for: str = ""


@dataclass(frozen=True)
class ParsedWoWPacket:
    market_date: date
    format_version: str
    submitted_at: datetime
    packet_id: str = ""
    author_id: str = ""
    packet_spec_version: str = ""
    packet_spec_url: str = ""
    skill_version: str = ""
    skill_url: str = ""
    human_title: str = ""
    human_summary: str = ""
    raw_packet_json: dict = field(default_factory=dict)
    agent_facts_json: dict = field(default_factory=dict)
    validation_results_json: dict = field(default_factory=dict)
    wow_items_json: list[dict] = field(default_factory=list)
    wow_count: int = 0
    scoreable_count: int = 0
    trackable_count: int = 0
    thesis_count: int = 0
    candidate_count: int = 0
    status_update_count: int = 0
    reading_items: list[ParsedReadingLogItem] = field(default_factory=list)
    suggested_wows: list[ParsedAgentSuggestedWoW] = field(default_factory=list)
    selected_wow_id: str = ""
    reason_for_selection: str = ""
    closest_rejected_idea: str = ""
    why_pass: str = ""
    missing_evidence: str = ""


def parse_radar(raw_email: RawEmail) -> ParsedRadar:
    fields = _fields(raw_email.raw_body)
    market_date = _date(
        fields.get("market_date") or fields.get("date") or _standalone_date(raw_email.raw_body),
        default=raw_email.received_at.date(),
    )
    title = fields.get("title") or _radar_title(raw_email.raw_body, market_date) or raw_email.subject or f"WKAP Radar Feed {market_date}"
    body = raw_email.raw_body
    if not body.strip():
        raise ParseError("Radar body is required.")
    return ParsedRadar(market_date=market_date, title=title.strip(), body_text=body.strip())


def parse_wow(raw_email: RawEmail) -> ParsedWoWPacket:
    spec = current_spec()
    text = _normalize_wow_text(raw_email.raw_body)
    structured = _parse_structured_wow(text, raw_email)
    if structured:
        return structured
    market_date = _date(_date_from_subject(raw_email.subject) or _standalone_date(text), default=raw_email.received_at.date())
    reading_section = _section_by_patterns(
        text,
        [r"^\s*#{0,6}\s*(?:\d+\.\s*)?Reading Log\s*$"],
        [
            r"^\s*#{0,6}\s*(?:\d+\.\s*)?Agent Suggested WoW Signals\s*$",
            r"^\s*#{0,6}\s*(?:\d+\.\s*)?Agent Suggested 3 WoWs\s*$",
            r"^\s*#{0,6}\s*Suggested WoWs\s*$",
        ],
    )
    suggested_section = _section_by_patterns(
        text,
        [
            r"^\s*#{0,6}\s*(?:\d+\.\s*)?Agent Suggested WoW Signals\s*$",
            r"^\s*#{0,6}\s*(?:\d+\.\s*)?Agent Suggested 3 WoWs\s*$",
            r"^\s*#{0,6}\s*Suggested WoWs\s*$",
        ],
        [r"^\s*#{0,6}\s*(?:\d+\.\s*)?User Selection / Pass\s*$", r"^\s*#{0,6}\s*User Selection\s*$"],
    )
    selection_section = _section_by_patterns(
        text,
        [r"^\s*#{0,6}\s*(?:\d+\.\s*)?User Selection / Pass\s*$", r"^\s*#{0,6}\s*User Selection\s*$"],
        [],
    )
    if not suggested_section:
        raise ParseError("Daily WoW Packet missing section: 2. Agent Suggested WoW Signals")

    reading_items = _parse_reading_items(reading_section)
    max_reading_items = int(spec["schema_data"].get("reading_log_rules", {}).get("max_items", 10))
    if len(reading_items) > max_reading_items:
        raise ParseError(
            f"Daily WoW Packet Reading Log can include at most {max_reading_items} items. "
            "Ask the agent to pick the top items from the full day history."
        )
    suggested_wows = _parse_suggested_wows(suggested_section)
    if not suggested_wows:
        raise ParseError("Daily WoW Packet must include at least one suggested WoW.")

    selection_fields = _fields(selection_section)
    selected_wow_id = local_wow_id(_first_field(selection_fields, "selected_wow_id", "selected_wow", "selected").strip())
    if not selected_wow_id:
        raise ParseError("selected_wow_id is required. Use a suggested WoW ID or none.")
    pass_fields = {
        "closest_rejected_idea": selection_fields.get("closest_rejected_idea", "").strip(),
        "why_pass": selection_fields.get("why_pass", "").strip(),
        "missing_evidence": selection_fields.get("missing_evidence", "").strip(),
    }
    if selected_wow_id.lower() == "none":
        missing_pass_fields = [name for name, value in pass_fields.items() if not value]
        if missing_pass_fields:
            raise ParseError(f"Pass selection missing required fields: {', '.join(missing_pass_fields)}")
    else:
        known_ids = {wow.wow_id for wow in suggested_wows}
        if selected_wow_id not in known_ids:
            raise ParseError(f"selected_wow_id does not match a suggested WoW: {selected_wow_id}")
        used_pass_fields = [name for name, value in pass_fields.items() if value]
        if used_pass_fields:
            raise ParseError(
                "Pass-only fields must be blank when selected_wow_id is not none: "
                + ", ".join(used_pass_fields)
            )

    return ParsedWoWPacket(
        market_date=market_date,
        format_version=spec["format_version"],
        packet_id=f"WOW-PACKET-{market_date}",
        packet_spec_version=spec["format_version"],
        packet_spec_url="https://wkap.ai/specs/wow-packet-latest.md",
        raw_packet_json={},
        agent_facts_json={
            "packet_spec_version": spec["format_version"],
            "wow_count": len(suggested_wows),
            "scoreable_count": 0,
            "trackable_count": len(suggested_wows),
            "thesis_count": 0,
            "candidate_count": 0,
            "status_update_count": 0,
        },
        validation_results_json={"schema_valid": True, "warnings": ["legacy_wow_packet_v1_parser"]},
        wow_items_json=_legacy_wow_items(suggested_wows),
        wow_count=len(suggested_wows),
        trackable_count=len(suggested_wows),
        reading_items=reading_items,
        suggested_wows=suggested_wows,
        selected_wow_id=selected_wow_id,
        reason_for_selection=_first_field(selection_fields, "reason_for_selection", "user_note", "note").strip(),
        closest_rejected_idea=pass_fields["closest_rejected_idea"],
        why_pass=pass_fields["why_pass"],
        missing_evidence=pass_fields["missing_evidence"],
        submitted_at=raw_email.received_at or timezone.now(),
    )


def _parse_structured_wow(text: str, raw_email: RawEmail) -> ParsedWoWPacket | None:
    block = _structured_block(text)
    if not block:
        return None
    try:
        payload = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"Structured WoW Packet YAML is invalid: {exc}") from exc
    if not isinstance(payload, dict) or "packet" not in payload:
        raise ParseError("Structured WoW Packet must contain a top-level packet object.")
    packet = payload["packet"]
    if not isinstance(packet, dict):
        raise ParseError("Structured WoW Packet packet field must be an object.")

    market_date = _date(
        str(packet.get("market_date") or _date_from_subject(raw_email.subject) or _standalone_date(text) or ""),
        default=raw_email.received_at.date(),
    )
    packet_spec_version = str(packet.get("packet_spec_version") or packet.get("spec_version") or "v0.1")
    author_id = str(packet.get("author_id") or "").strip()
    if not author_id:
        raise ParseError("Structured WoW Packet requires author_id.")
    wow_items = packet.get("wow_items") or []
    if not isinstance(wow_items, list) or not wow_items:
        raise ParseError("Structured WoW Packet requires at least one wow_items entry.")

    reading_items = _structured_reading_items(packet.get("reading_log") or packet.get("reading_items") or [])
    suggested_wows = _structured_wow_items(wow_items)
    selection = packet.get("selection") if isinstance(packet.get("selection"), dict) else {}
    selected_wow_id = local_wow_id(str(selection.get("selected_wow_id") or packet.get("selected_wow_id") or "none").strip())
    reason_for_selection = str(selection.get("reason_for_selection") or packet.get("reason_for_selection") or "").strip()
    closest_rejected_idea = str(selection.get("closest_rejected_idea") or "").strip()
    why_pass = str(selection.get("why_pass") or "").strip()
    missing_evidence = str(selection.get("missing_evidence") or "").strip()

    if selected_wow_id.lower() != "none":
        known_ids = {wow.wow_id for wow in suggested_wows}
        if selected_wow_id not in known_ids:
            raise ParseError(f"selected_wow_id does not match a structured WoW item: {selected_wow_id}")

    human_view = packet.get("human_view") if isinstance(packet.get("human_view"), dict) else {}
    agent_facts = packet.get("agent_facts") if isinstance(packet.get("agent_facts"), dict) else {}
    counts = _wow_type_counts(wow_items)
    raw_packet_json = _json_safe(packet)
    validation = _json_safe(packet.get("validation_notes") if isinstance(packet.get("validation_notes"), dict) else {})
    validation.setdefault("schema_valid", True)
    validation.setdefault("warnings", [])

    return ParsedWoWPacket(
        market_date=market_date,
        format_version="wow_packet_v0.1",
        submitted_at=raw_email.received_at or timezone.now(),
        packet_id=str(packet.get("packet_id") or f"WKAP-{author_id}-{market_date}").strip(),
        author_id=author_id,
        packet_spec_version=packet_spec_version,
        packet_spec_url=str(packet.get("packet_spec_url") or "https://wkap.ai/specs/wow-packet-latest.md"),
        skill_version=str(packet.get("skill_version") or ""),
        skill_url=str(packet.get("skill_url") or ""),
        human_title=str(human_view.get("title") or packet.get("title") or "Daily WoW Packet"),
        human_summary=str(human_view.get("summary") or packet.get("summary") or ""),
        raw_packet_json=raw_packet_json,
        agent_facts_json=_json_safe({**agent_facts, **counts, "packet_spec_version": packet_spec_version}),
        validation_results_json=validation,
        wow_items_json=_json_safe(wow_items),
        wow_count=counts["wow_count"],
        scoreable_count=counts["scoreable_count"],
        trackable_count=counts["trackable_count"],
        thesis_count=counts["thesis_count"],
        candidate_count=counts["candidate_count"],
        status_update_count=counts["status_update_count"],
        reading_items=reading_items,
        suggested_wows=suggested_wows,
        selected_wow_id=selected_wow_id,
        reason_for_selection=reason_for_selection,
        closest_rejected_idea=closest_rejected_idea,
        why_pass=why_pass,
        missing_evidence=missing_evidence,
    )


def _structured_block(text: str) -> str:
    for match in re.finditer(r"```(?:yaml|yml|json)\s*\n(.*?)\n```", text, flags=re.IGNORECASE | re.DOTALL):
        block = match.group(1).strip()
        if re.search(r"^\s*packet\s*:", block, flags=re.MULTILINE) or '"packet"' in block:
            return block
    return ""


def _structured_reading_items(items) -> list[ParsedReadingLogItem]:
    if not isinstance(items, list):
        return []
    parsed = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        parsed.append(
            ParsedReadingLogItem(
                item_number=int(item.get("item_number") or item.get("reading_item") or index),
                source_title=str(item.get("source_title") or item.get("title") or ""),
                source_url=str(item.get("source_url") or item.get("url") or ""),
                source_type=str(item.get("source_type") or ""),
                published_time=str(item.get("published_time") or ""),
                tickers_or_themes=_join_list(item.get("tickers") or item.get("themes") or item.get("tickers_or_themes") or ""),
                reading_origin=str(item.get("reading_origin") or ""),
                agent_summary=str(item.get("agent_summary") or item.get("summary") or ""),
            )
        )
    return parsed


def _structured_wow_items(items: list[dict]) -> list[ParsedAgentSuggestedWoW]:
    parsed = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        wow_id = local_wow_id(str(item.get("wow_id") or f"WOW-ITEM-{index:03d}").strip())
        wow_type = str(item.get("wow_type") or "candidate_wow")
        source_refs = _join_list(item.get("source_refs") or [])
        title = (
            item.get("ticker_or_theme")
            or item.get("theme")
            or item.get("claim")
            or item.get("observation")
            or item.get("thesis_claim")
            or item.get("summary")
            or wow_type
        )
        watch = (
            item.get("what_s_worth_watching")
            or item.get("whats_worth_watching")
            or item.get("why_worth_watching")
            or item.get("claim")
            or item.get("observation")
            or item.get("update_summary")
            or ""
        )
        evidence = item.get("evidence_to_watch") or item.get("what_evidence_should_ai_watch_for") or item.get("invalidate_test") or item.get("evidence_summary") or ""
        parsed.append(
            ParsedAgentSuggestedWoW(
                item_number=index,
                wow_id=wow_id,
                source_refs=source_refs,
                ticker_or_theme=str(title),
                whats_worth_watching=str(watch),
                why_now=str(item.get("why_now") or item.get("review_cadence") or item.get("update_type") or ""),
                evidence_to_watch_for=_join_list(evidence),
            )
        )
    return parsed


def _wow_type_counts(items: list[dict]) -> dict[str, int]:
    values = [str(item.get("wow_type") or "") for item in items if isinstance(item, dict)]
    return {
        "wow_count": len(values),
        "scoreable_count": values.count("scoreable_signal"),
        "trackable_count": values.count("trackable_wow"),
        "thesis_count": values.count("thesis_wow"),
        "candidate_count": values.count("candidate_wow"),
        "status_update_count": values.count("status_update"),
    }


def _legacy_wow_items(suggested_wows: list[ParsedAgentSuggestedWoW]) -> list[dict]:
    return [
        {
            "wow_id": wow.wow_id,
            "wow_type": "trackable_wow",
            "scoreable": False,
            "source_refs": wow.source_refs,
            "claim": wow.whats_worth_watching,
            "evidence_to_watch": wow.evidence_to_watch_for,
            "agent_facts": {"accuracy_endpoint_eligible": False},
        }
        for wow in suggested_wows
    ]


def _join_list(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item is not None)
    return str(value or "")


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_ /\-']{1,100})\s*:\s*(.*)$", line)
        if match:
            current_key = _field_key(match.group(1))
            fields[current_key] = match.group(2).strip()
        elif current_key and line.strip() and line.strip() != "---":
            fields[current_key] = f"{fields[current_key]}\n{line.strip()}".strip()
    return fields


def _field_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    aliases = {
        "ticker_theme": "ticker_theme",
        "ticker_or_theme": "ticker_theme",
        "tickers_themes": "tickers_themes",
        "tickers_or_themes": "tickers_themes",
        "what_is_worth_watching": "what_s_worth_watching",
        "whats_worth_watching": "what_s_worth_watching",
        "what_s_worth_watching": "what_s_worth_watching",
        "evidence_to_watch": "what_evidence_should_ai_watch_for",
        "what_evidence_should_ai_watch": "what_evidence_should_ai_watch_for",
        "what_evidence_should_ai_watch_for": "what_evidence_should_ai_watch_for",
        "selected_wow": "selected_wow_id",
        "selected_wow_id": "selected_wow_id",
        "selection": "selected_wow_id",
    }
    return aliases.get(key, key)


def _section(text: str, start_heading: str, end_heading: str) -> str:
    start = text.find(start_heading)
    if start < 0:
        return ""
    start += len(start_heading)
    end = text.find(end_heading, start) if end_heading else -1
    return text[start:end if end >= 0 else None].strip()


def _section_by_patterns(text: str, start_patterns: list[str], end_patterns: list[str]) -> str:
    starts = []
    for pattern in start_patterns:
        starts.extend(re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    if not starts:
        return ""
    start_match = min(starts, key=lambda match: match.start())
    start = start_match.end()
    ends = []
    for pattern in end_patterns:
        ends.extend(match for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE) if match.start() > start)
    end = min((match.start() for match in ends), default=len(text))
    return text[start:end].strip()


def _normalize_wow_text(text: str) -> str:
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("—", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )


def _parse_reading_items(text: str) -> list[ParsedReadingLogItem]:
    schema = current_spec()["schema_data"]
    allowed_source_types = set(schema.get("source_type_values", []))
    allowed_origins = set(schema.get("reading_origin_values", []))
    items = []
    for index, block in enumerate(_blocks(text, r"^(?:#{1,6}\s*)?Reading Item\s+\[?(\d+)\]?"), start=1):
        number, content = block
        fields = _fields(content)
        source_type = fields.get("source_type", "")
        reading_origin = fields.get("reading_origin", "")
        if source_type and source_type not in allowed_source_types:
            raise ParseError(f"Reading Item {number or index} source_type must be one of: {', '.join(allowed_source_types)}")
        if reading_origin and reading_origin not in allowed_origins:
            raise ParseError(f"Reading Item {number or index} reading_origin must be one of: {', '.join(allowed_origins)}")
        items.append(
            ParsedReadingLogItem(
                item_number=number or index,
                source_title=fields.get("source_title", ""),
                source_url=fields.get("source_url", ""),
                source_type=source_type,
                published_time=fields.get("published_time", ""),
                tickers_or_themes=fields.get("tickers_themes", ""),
                reading_origin=reading_origin,
                agent_summary=fields.get("agent_summary", ""),
            )
        )
    return items


def _parse_suggested_wows(text: str) -> list[ParsedAgentSuggestedWoW]:
    items = []
    for index, block in enumerate(_blocks(text, r"^(?:#{1,6}\s*)?Suggested WoW\s+\[?(\d+)\]?"), start=1):
        number, content = block
        fields = _fields(content)
        wow_id = local_wow_id(fields.get("wow_id", "").strip())
        if not wow_id:
            raise ParseError(f"Suggested WoW {number or index} missing wow_id.")
        items.append(
            ParsedAgentSuggestedWoW(
                item_number=number or index,
                wow_id=wow_id,
                source_refs=fields.get("source_refs", ""),
                ticker_or_theme=fields.get("ticker_theme", ""),
                whats_worth_watching=fields.get("what_s_worth_watching", ""),
                why_now=fields.get("why_now", ""),
                evidence_to_watch_for=fields.get("what_evidence_should_ai_watch_for", ""),
            )
        )
    return items


def _first_field(fields: dict[str, str], *names: str) -> str:
    for name in names:
        if fields.get(name):
            return fields[name]
    return ""


def _blocks(text: str, heading_pattern: str) -> list[tuple[int | None, str]]:
    matches = list(re.finditer(heading_pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    blocks = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        number = int(match.group(1)) if match.group(1).isdigit() else None
        blocks.append((number, text[match.end() : end].strip()))
    return blocks


def _date_from_subject(subject: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", subject or "")
    return match.group(0) if match else ""


def _without_field_lines(text: str) -> str:
    lines = [line for line in text.splitlines() if not re.match(r"^\s*[A-Za-z][A-Za-z0-9_-]{1,80}\s*:", line)]
    return "\n".join(lines).strip()


def _body_field_remainder(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*body\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        body_lines = [match.group(1), *lines[index + 1 :]]
        return "\n".join(body_lines).strip()
    return ""


def _date(value: str | None, *, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise ParseError(f"Invalid market_date: {value}") from exc


def _standalone_date(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
    return ""


def _radar_title(text: str, market_date: date) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_text = str(market_date)
    for index, line in enumerate(lines):
        if line == date_text:
            for candidate in lines[index + 1 :]:
                if not candidate.lower().startswith(("preheader:", "human user", "for your ai agent")):
                    return candidate
    return ""


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
