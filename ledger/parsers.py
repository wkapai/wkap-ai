from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse

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
        reading_items=reading_items,
        suggested_wows=suggested_wows,
        selected_wow_id=selected_wow_id,
        reason_for_selection=_first_field(selection_fields, "reason_for_selection", "user_note", "note").strip(),
        closest_rejected_idea=pass_fields["closest_rejected_idea"],
        why_pass=pass_fields["why_pass"],
        missing_evidence=pass_fields["missing_evidence"],
        submitted_at=raw_email.received_at or timezone.now(),
    )


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
