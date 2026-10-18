from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import yaml
from django.utils import timezone

from ingestion.models import RawEmail
from ledger.wow_contract import local_wow_id
from ledger.wow_lifecycle_rules import VALID_WOW_TYPES, validate_status_transition
from ledger.wow_packet_spec import current_spec


class ParseError(ValueError):
    pass


DAILY_MARKET_MEME_CHALLENGE = (
    "Roast our take, spot an egg, or show us your market meme. "
    "Tell us what today\u0027s market is missing."
)


WOW_TYPE_REQUIRED_FIELDS = {
    "candidate_wow": ("observation", "why_worth_watching", "candidate_status", "source_refs"),
    "trackable_wow": ("claim", "evidence_to_watch", "review_cadence", "next_review_at", "trackable_status", "source_refs"),
    "scoreable_signal": ("claim", "invalidate_test", "resolve_by", "resolution_source", "signal_status", "source_refs"),
    "thesis_wow": ("thesis_claim", "thesis_status", "source_refs"),
}


@dataclass(frozen=True)
class ParsedRadar:
    market_date: date
    title: str
    body_text: str
    edition_version: int | None = None
    cover_image_source_url: str = ""
    cover_image_sha256: str = ""
    cover_logo_verified: bool = False
    challenge_invitation: str = ""


@dataclass(frozen=True)
class ParsedCreativeEdition:
    market_date: date
    edition_version: int
    format_version: str
    title: str
    article_url: str
    image_source_url: str
    creator_human: str
    creator_ai: str
    publisher: str
    journal_json: dict
    article_word_count: int = 0
    cover_logo_verified: bool = False


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
    investor_id: str = ""
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
        _date_from_subject(raw_email.subject)
        or fields.get("market_date")
        or fields.get("date")
        or _standalone_date(raw_email.raw_body),
        default=raw_email.received_at.date(),
    )
    title = fields.get("title") or _radar_title(raw_email.raw_body, market_date) or raw_email.subject or f"WKAP Radar Feed {market_date}"
    body = raw_email.raw_body
    if not body.strip():
        raise ParseError("Radar body is required.")
    edition_version, cover_url, cover_sha256, logo_verified, challenge = _radar_edition_metadata(fields)
    if edition_version and str(fields.get("article_url") or "").strip():
        raise ParseError("Revamp Radar must omit article_url; the exact Article link is added only after publication.")
    return ParsedRadar(
        market_date=market_date,
        title=title.strip(),
        body_text=body.strip(),
        edition_version=edition_version,
        cover_image_source_url=cover_url,
        cover_image_sha256=cover_sha256,
        cover_logo_verified=logo_verified,
        challenge_invitation=challenge,
    )


def parse_creative_edition(raw_email: RawEmail) -> ParsedCreativeEdition:
    block = _creative_structured_block(raw_email.raw_body)
    if not block:
        raise ParseError("Creative Edition requires one fenced YAML or JSON creative_edition block.")
    try:
        payload = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ParseError(f"Creative Edition YAML is invalid: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("wkap_edition"), dict):
        return _parse_wkap_edition(raw_email, payload["wkap_edition"])
    if not isinstance(payload, dict) or not isinstance(payload.get("creative_edition"), dict):
        raise ParseError("Edition must contain one top-level wkap_edition or legacy creative_edition object.")
    edition = payload["creative_edition"]
    allowed = {
        "format_version",
        "market_date",
        "edition_version",
        "title",
        "article_url",
        "image_source_url",
        "episode_premise",
        "market_hooks",
        "scenes",
        "credits",
        "rejected_choices",
        "corrections",
        "lesson_next_time",
    }
    unexpected = sorted(set(edition) - allowed)
    if unexpected:
        raise ParseError(f"Creative Edition contains unsupported public fields: {', '.join(unexpected)}")

    format_version = _required_text(edition, "format_version", max_length=64)
    if format_version != "creative_edition_v1":
        raise ParseError("Creative Edition format_version must be creative_edition_v1.")
    market_date = _date(_required_text(edition, "market_date", max_length=10), default=raw_email.received_at.date())
    subject_date = _date_from_subject(raw_email.subject)
    if not subject_date or subject_date != str(market_date):
        raise ParseError("Creative Edition subject date must exactly match creative_edition.market_date.")
    received_ict_date = raw_email.received_at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    if market_date != received_ict_date:
        raise ParseError("Creative Edition market_date must match the ICT receipt date; backdating is not allowed.")

    subject_version_match = re.search(r"\bv\s*(\d+)\b", raw_email.subject or "", flags=re.IGNORECASE)
    if not subject_version_match:
        raise ParseError("Creative Edition subject must include an explicit version such as v1.")
    try:
        edition_version = int(edition.get("edition_version"))
    except (TypeError, ValueError) as exc:
        raise ParseError("Creative Edition edition_version must be a positive integer.") from exc
    if edition_version < 1 or edition_version != int(subject_version_match.group(1)):
        raise ParseError("Creative Edition body version must be positive and match the subject version.")

    title = _required_text(edition, "title", max_length=500)
    article_url = _required_https_url(edition, "article_url")
    image_source_url = _required_https_url(edition, "image_source_url")
    if urlparse(image_source_url).hostname not in {"pbs.twimg.com"}:
        raise ParseError("Creative Edition image_source_url must be the actual public X cover on pbs.twimg.com.")

    episode_premise = _required_text(edition, "episode_premise", max_length=1400)
    market_hooks = _creative_market_hooks(edition.get("market_hooks"))
    scenes = _creative_scenes(edition.get("scenes"))
    credits = edition.get("credits")
    if not isinstance(credits, dict):
        raise ParseError("Creative Edition credits must be an object.")
    _reject_creative_unknown_fields(
        credits,
        {"human_contribution", "ai_contribution", "publisher"},
        label="credits",
    )
    creator_human = _required_text(credits, "human_contribution", max_length=300)
    creator_ai = _required_text(credits, "ai_contribution", max_length=300)
    publisher = _required_text(credits, "publisher", max_length=200)
    rejected_choices = _required_text_list(edition, "rejected_choices", max_items=8, max_item_length=600)
    corrections = _required_text_list(edition, "corrections", max_items=8, max_item_length=600)
    lesson_next_time = _required_text(edition, "lesson_next_time", max_length=1200)

    source_links = []
    for item in [*market_hooks, *scenes]:
        for source_url in item["source_urls"]:
            if source_url not in source_links:
                source_links.append(source_url)

    journal_json = {
        "format_version": format_version,
        "market_date": str(market_date),
        "edition_version": edition_version,
        "title": title,
        "article_url": article_url,
        "image_source_url": image_source_url,
        "episode_premise": episode_premise,
        "market_hooks": market_hooks,
        "scenes": scenes,
        "credits": {
            "human_contribution": creator_human,
            "ai_contribution": creator_ai,
            "publisher": publisher,
        },
        "rejected_choices": rejected_choices,
        "corrections": corrections,
        "lesson_next_time": lesson_next_time,
        "source_links": source_links,
    }
    if len(json.dumps(journal_json, ensure_ascii=False)) > 24000:
        raise ParseError("Creative Edition public journal is too long; keep it concise and curated.")
    return ParsedCreativeEdition(
        market_date=market_date,
        edition_version=edition_version,
        format_version=format_version,
        title=title,
        article_url=article_url,
        image_source_url=image_source_url,
        creator_human=creator_human,
        creator_ai=creator_ai,
        publisher=publisher,
        journal_json=journal_json,
    )


def _parse_wkap_edition(raw_email: RawEmail, edition: dict) -> ParsedCreativeEdition:
    allowed = {
        "format_version",
        "market_date",
        "edition_version",
        "title",
        "article_url",
        "image_source_url",
        "cover_logo_verified",
        "analysis",
        "episode_premise",
        "market_hooks",
        "scenes",
        "challenge",
        "credits",
        "rejected_choices",
        "corrections",
        "lesson_next_time",
    }
    _reject_creative_unknown_fields(edition, allowed, label="wkap_edition")
    format_version = _required_text(edition, "format_version", max_length=64)
    if format_version != "wkap_edition_v1":
        raise ParseError("WKAP Edition format_version must be wkap_edition_v1.")

    market_date = _date(_required_text(edition, "market_date", max_length=10), default=raw_email.received_at.date())
    subject_date = _date_from_subject(raw_email.subject)
    if not subject_date or subject_date != str(market_date):
        raise ParseError("WKAP Edition subject date must exactly match wkap_edition.market_date.")
    received_ict_date = raw_email.received_at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    if market_date != received_ict_date:
        raise ParseError("WKAP Edition market_date must match the ICT receipt date; backdating is not allowed.")

    subject_version_match = re.search(r"\bv\s*(\d+)\b", raw_email.subject or "", flags=re.IGNORECASE)
    if not subject_version_match:
        raise ParseError("WKAP Edition subject must include an explicit version such as v1.")
    try:
        edition_version = int(edition.get("edition_version"))
    except (TypeError, ValueError) as exc:
        raise ParseError("WKAP Edition edition_version must be a positive integer.") from exc
    if edition_version < 1 or edition_version != int(subject_version_match.group(1)):
        raise ParseError("WKAP Edition body version must be positive and match the subject version.")

    title = _required_text(edition, "title", max_length=500)
    article_url = _required_https_url(edition, "article_url")
    _require_x_publication_url(article_url, label="article_url", allow_article=True)
    image_source_url = _required_https_url(edition, "image_source_url")
    if (urlparse(image_source_url).hostname or "").lower() != "pbs.twimg.com":
        raise ParseError("WKAP Edition image_source_url must be the actual public X cover on pbs.twimg.com.")
    if edition.get("cover_logo_verified") is not True:
        raise ParseError("WKAP Edition cover_logo_verified must be true after actual-pixel watermark QA.")

    analysis, article_word_count = _wkap_analysis(edition.get("analysis"))
    episode_premise = _required_text(edition, "episode_premise", max_length=900)
    market_hooks = _creative_market_hooks(edition.get("market_hooks"))
    scenes = _creative_scenes(edition.get("scenes"), require_show_seed=False)
    challenge = _wkap_challenge(edition.get("challenge"))
    credits = edition.get("credits")
    if not isinstance(credits, dict):
        raise ParseError("WKAP Edition credits must be an object.")
    _reject_creative_unknown_fields(credits, {"human_contribution", "ai_contribution", "publisher"}, label="credits")
    creator_human = _required_text(credits, "human_contribution", max_length=300)
    creator_ai = _required_text(credits, "ai_contribution", max_length=300)
    publisher = _required_text(credits, "publisher", max_length=200)
    rejected_choices = _required_text_list(edition, "rejected_choices", max_items=8, max_item_length=600)
    corrections = _required_text_list(edition, "corrections", max_items=8, max_item_length=600)
    lesson_next_time = _required_text(edition, "lesson_next_time", max_length=1200)

    source_links: list[str] = []
    for section in analysis["sections"]:
        for source_url in section["source_urls"]:
            if source_url not in source_links:
                source_links.append(source_url)
    for item in [*market_hooks, *scenes]:
        for source_url in item["source_urls"]:
            if source_url not in source_links:
                source_links.append(source_url)

    journal_json = {
        "format_version": format_version,
        "market_date": str(market_date),
        "edition_version": edition_version,
        "title": title,
        "article_url": article_url,
        "image_source_url": image_source_url,
        "cover_logo_verified": True,
        "analysis": analysis,
        "episode_premise": episode_premise,
        "market_hooks": market_hooks,
        "scenes": scenes,
        "challenge": challenge,
        "credits": {
            "human_contribution": creator_human,
            "ai_contribution": creator_ai,
            "publisher": publisher,
        },
        "rejected_choices": rejected_choices,
        "corrections": corrections,
        "lesson_next_time": lesson_next_time,
        "source_links": source_links,
    }
    if len(json.dumps(journal_json, ensure_ascii=False)) > 120000:
        raise ParseError("WKAP Edition is too long for the public edition envelope.")
    return ParsedCreativeEdition(
        market_date=market_date,
        edition_version=edition_version,
        format_version=format_version,
        title=title,
        article_url=article_url,
        image_source_url=image_source_url,
        creator_human=creator_human,
        creator_ai=creator_ai,
        publisher=publisher,
        journal_json=journal_json,
        article_word_count=article_word_count,
        cover_logo_verified=True,
    )


def parse_wow(raw_email: RawEmail, *, assigned_investor_id: str = "") -> ParsedWoWPacket:
    spec = current_spec()
    text = _normalize_wow_text(raw_email.raw_body)
    structured = _parse_structured_wow(text, raw_email, assigned_investor_id=assigned_investor_id)
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
    required_wow_count = int(spec["schema_data"].get("suggested_wow_rules", {}).get("required_count", 3))
    if len(suggested_wows) != required_wow_count:
        raise ParseError(f"Daily WoW Packet must include exactly {required_wow_count} suggested WoW signals.")

    selection_fields = _fields(selection_section)
    selected_wow_id = local_wow_id(_first_field(selection_fields, "selected_wow_id", "selected_wow", "selected").strip())
    if not selected_wow_id:
        raise ParseError("selected_wow_id is required. Use a suggested WoW ID or none.")
    pass_fields = {
        "reason_for_pass": _first_field(selection_fields, "reason_for_pass", "why_pass").strip(),
        "closest_rejected_idea": _first_field(selection_fields, "closest_rejected_wow", "closest_rejected_idea").strip(),
        "missing_evidence": selection_fields.get("missing_evidence", "").strip(),
    }
    if selected_wow_id.lower() == "none":
        missing_pass_fields = [name for name, value in pass_fields.items() if not value]
        if missing_pass_fields:
            raise ParseError(f"Pass selection missing required fields: {_public_pass_field_names(missing_pass_fields)}")
        _validate_closest_rejected_wow(pass_fields["closest_rejected_idea"], suggested_wows)
    else:
        known_ids = {wow.wow_id for wow in suggested_wows}
        if selected_wow_id not in known_ids:
            raise ParseError(f"selected_wow_id does not match a suggested WoW: {selected_wow_id}")
        if not _first_field(selection_fields, "reason_for_selection", "user_note", "note").strip():
            raise ParseError("Selection missing required field: reason_for_selection")
        used_pass_fields = [name for name, value in pass_fields.items() if value]
        if used_pass_fields:
            raise ParseError(
                "Pass-only fields must be blank when selected_wow_id is not none: "
                + _public_pass_field_names(used_pass_fields)
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
        validation_results_json={"schema_valid": True, "warnings": ["plain_text_wow_packet_parser"]},
        wow_items_json=_legacy_wow_items(suggested_wows),
        wow_count=len(suggested_wows),
        trackable_count=len(suggested_wows),
        reading_items=reading_items,
        suggested_wows=suggested_wows,
        selected_wow_id=selected_wow_id,
        reason_for_selection=_first_field(selection_fields, "reason_for_selection", "user_note", "note").strip(),
        closest_rejected_idea=pass_fields["closest_rejected_idea"],
        why_pass=pass_fields["reason_for_pass"],
        missing_evidence=pass_fields["missing_evidence"],
        submitted_at=raw_email.received_at or timezone.now(),
    )


def _parse_structured_wow(text: str, raw_email: RawEmail, *, assigned_investor_id: str = "") -> ParsedWoWPacket | None:
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
    packet_spec_version = str(packet.get("packet_spec_version") or packet.get("spec_version") or "v0.2")
    investor_id = _structured_packet_investor_id(packet, assigned_investor_id=assigned_investor_id)
    wow_items = packet.get("wow_items") or []
    if not isinstance(wow_items, list) or not wow_items:
        raise ParseError("Structured WoW Packet requires at least one wow_items entry.")
    if len(wow_items) != 3:
        raise ParseError("Structured WoW Packet must include exactly 3 wow_items entries.")
    _validate_structured_wow_items(wow_items, packet_investor_id=investor_id, assigned_investor_id=assigned_investor_id)

    reading_items = _structured_reading_items(packet.get("reading_log") or packet.get("reading_items") or [])
    if len(reading_items) > 10:
        raise ParseError(
            "Structured WoW Packet Reading Log can include at most 10 items. "
            "Ask the agent to pick the top items from the full day history."
        )
    suggested_wows = _structured_wow_items(wow_items)
    selection = packet.get("selection") if isinstance(packet.get("selection"), dict) else {}
    selected_wow_id = local_wow_id(str(selection.get("selected_wow_id") or packet.get("selected_wow_id") or "none").strip())
    reason_for_selection = str(selection.get("reason_for_selection") or packet.get("reason_for_selection") or "").strip()
    closest_rejected_idea = str(selection.get("closest_rejected_wow") or selection.get("closest_rejected_idea") or "").strip()
    why_pass = str(selection.get("reason_for_pass") or selection.get("why_pass") or "").strip()
    missing_evidence = str(selection.get("missing_evidence") or "").strip()

    if selected_wow_id.lower() != "none":
        known_ids = {wow.wow_id for wow in suggested_wows}
        if selected_wow_id not in known_ids:
            raise ParseError(f"selected_wow_id does not match a structured WoW item: {selected_wow_id}")
        if not reason_for_selection:
            raise ParseError("Selection missing required field: reason_for_selection")
        used_pass_fields = [
            name
            for name, value in {
                "reason_for_pass": why_pass,
                "closest_rejected_wow": closest_rejected_idea,
                "missing_evidence": missing_evidence,
            }.items()
            if value
        ]
        if used_pass_fields:
            raise ParseError(
                "Pass-only fields must be blank when selected_wow_id is not none: "
                + ", ".join(used_pass_fields)
            )
    else:
        missing_pass_fields = [
            name
            for name, value in {
                "reason_for_pass": why_pass,
                "closest_rejected_wow": closest_rejected_idea,
                "missing_evidence": missing_evidence,
            }.items()
            if not value
        ]
        if missing_pass_fields:
            raise ParseError(f"Pass selection missing required fields: {_public_pass_field_names(missing_pass_fields)}")
        _validate_closest_rejected_wow(closest_rejected_idea, suggested_wows)

    human_view = packet.get("human_view") if isinstance(packet.get("human_view"), dict) else {}
    agent_facts = packet.get("agent_facts") if isinstance(packet.get("agent_facts"), dict) else {}
    counts = _wow_type_counts(wow_items)
    raw_packet_json = _canonical_parsed_packet_json(packet, investor_id=investor_id)
    validation = _json_safe(packet.get("validation_notes") if isinstance(packet.get("validation_notes"), dict) else {})
    validation.setdefault("schema_valid", True)
    validation.setdefault("warnings", [])

    return ParsedWoWPacket(
        market_date=market_date,
        format_version="wow_packet_v0.2",
        submitted_at=raw_email.received_at or timezone.now(),
        packet_id=str(packet.get("packet_id") or f"WKAP-{investor_id}-{market_date}").strip(),
        investor_id=investor_id,
        packet_spec_version=packet_spec_version,
        packet_spec_url=str(packet.get("packet_spec_url") or "https://wkap.ai/specs/wow-packet-latest.md"),
        skill_version=str(packet.get("skill_version") or ""),
        skill_url=str(packet.get("skill_url") or ""),
        human_title=str(human_view.get("title") or packet.get("title") or "Daily WoW Packet"),
        human_summary=str(human_view.get("summary") or packet.get("summary") or ""),
        raw_packet_json=raw_packet_json,
        agent_facts_json=_canonical_parsed_agent_facts(agent_facts, counts=counts, packet_spec_version=packet_spec_version, investor_id=investor_id),
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


def _creative_structured_block(text: str) -> str:
    blocks = []
    for match in re.finditer(r"```(?:yaml|yml|json)\s*\n(.*?)\n```", text, flags=re.IGNORECASE | re.DOTALL):
        block = match.group(1).strip()
        if (
            re.search(r"^\s*(?:wkap_edition|creative_edition)\s*:", block, flags=re.MULTILINE)
            or '"wkap_edition"' in block
            or '"creative_edition"' in block
        ):
            blocks.append(block)
    if len(blocks) > 1:
        raise ParseError("Edition email must contain exactly one wkap_edition or legacy creative_edition block.")
    return blocks[0] if blocks else ""


def _reject_creative_unknown_fields(payload: dict, allowed: set[str], *, label: str) -> None:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ParseError(f"Creative Edition {label} contains unsupported fields: {', '.join(unexpected)}")


def _required_text(payload: dict, field_name: str, *, max_length: int) -> str:
    value = str(payload.get(field_name) or "").strip()
    if not value:
        raise ParseError(f"Creative Edition missing required field: {field_name}")
    if len(value) > max_length:
        raise ParseError(f"Creative Edition {field_name} exceeds {max_length} characters.")
    return value


def _required_text_list(payload: dict, field_name: str, *, max_items: int, max_item_length: int) -> list[str]:
    values = payload.get(field_name)
    if not isinstance(values, list) or not values:
        raise ParseError(f"Creative Edition {field_name} must be a non-empty list.")
    if len(values) > max_items:
        raise ParseError(f"Creative Edition {field_name} can contain at most {max_items} items.")
    cleaned = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            raise ParseError(f"Creative Edition {field_name} cannot contain blank items.")
        if len(text) > max_item_length:
            raise ParseError(f"Creative Edition {field_name} item exceeds {max_item_length} characters.")
        cleaned.append(text)
    return cleaned


def _required_https_url(payload: dict, field_name: str) -> str:
    value = _required_text(payload, field_name, max_length=1000)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ParseError(f"Creative Edition {field_name} must be an HTTPS URL.")
    return value


def _creative_source_urls(value, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ParseError(f"Creative Edition {label} requires at least one source URL.")
    if len(value) > 8:
        raise ParseError(f"Creative Edition {label} can reference at most 8 source URLs.")
    result = []
    for item in value:
        url = str(item or "").strip()
        if not _is_http_url(url):
            raise ParseError(f"Creative Edition {label} contains an invalid source URL.")
        if url not in result:
            result.append(url)
    return result


def _creative_market_hooks(value) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ParseError("Creative Edition market_hooks must be a non-empty list.")
    if len(value) > 6:
        raise ParseError("Creative Edition market_hooks can contain at most 6 items.")
    result = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ParseError(f"Creative Edition market_hook {index} must be an object.")
        _reject_creative_unknown_fields(item, {"story", "why_it_matters", "source_urls"}, label=f"market_hook {index}")
        result.append(
            {
                "story": _required_text(item, "story", max_length=700),
                "why_it_matters": _required_text(item, "why_it_matters", max_length=700),
                "source_urls": _creative_source_urls(item.get("source_urls"), label=f"market_hook {index}"),
            }
        )
    return result


def _creative_scenes(value, *, require_show_seed: bool = True) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ParseError("Creative Edition scenes must be a non-empty list.")
    if len(value) > 8:
        raise ParseError("Creative Edition scenes can contain at most 8 items.")
    result = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ParseError(f"Creative Edition scene {index} must be an object.")
        allowed_fields = {
                "story",
                "source_urls",
                "visual_joke",
                "character_choices",
                "character_rationale",
                "relationship_semantics",
                "interaction_or_action",
            }
        if require_show_seed:
            allowed_fields.add("show_seed")
        _reject_creative_unknown_fields(
            item,
            allowed_fields,
            label=f"scene {index}",
        )
        scene = {
                "story": _required_text(item, "story", max_length=700),
                "source_urls": _creative_source_urls(item.get("source_urls"), label=f"scene {index}"),
                "visual_joke": _required_text(item, "visual_joke", max_length=700),
                "character_choices": _required_text(item, "character_choices", max_length=700),
                "character_rationale": _required_text(item, "character_rationale", max_length=900),
                "relationship_semantics": _required_text(item, "relationship_semantics", max_length=900),
                "interaction_or_action": _required_text(item, "interaction_or_action", max_length=700),
            }
        show_seed = str(item.get("show_seed") or "").strip()
        if require_show_seed:
            show_seed = _required_text(item, "show_seed", max_length=700)
        if show_seed:
            scene["show_seed"] = show_seed
        result.append(scene)
    return result


def _radar_edition_metadata(fields: dict) -> tuple[int | None, str, str, bool, str]:
    raw_version = str(fields.get("edition_version") or "").strip()
    cover_url = str(fields.get("cover_image_source_url") or fields.get("image_source_url") or "").strip()
    cover_sha256 = str(fields.get("cover_image_sha256") or fields.get("image_sha256") or "").strip().lower()
    challenge = str(fields.get("challenge_invitation") or fields.get("daily_market_meme_challenge") or "").strip()
    logo_raw = str(fields.get("cover_logo_verified") or "").strip().lower()
    present = any((raw_version, cover_url, cover_sha256, challenge, logo_raw))
    if not present:
        return None, "", "", False, ""
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise ParseError("Radar edition_version must be a positive integer when cover metadata is supplied.") from exc
    if version < 1:
        raise ParseError("Radar edition_version must be a positive integer.")
    if not _is_http_url(cover_url) or (urlparse(cover_url).hostname or "").lower() != "pbs.twimg.com":
        raise ParseError("Radar cover_image_source_url must be the actual public X cover on pbs.twimg.com.")
    if not re.fullmatch(r"[0-9a-f]{64}", cover_sha256):
        raise ParseError("Radar cover_image_sha256 must be the exact 64-character lowercase SHA-256 digest.")
    if logo_raw != "true":
        raise ParseError("Radar cover_logo_verified must be true after actual-pixel watermark QA.")
    if challenge != DAILY_MARKET_MEME_CHALLENGE:
        raise ParseError("Radar challenge_invitation must use the fixed Daily Market Meme Challenge wording.")
    return version, cover_url, cover_sha256, True, challenge


def _require_x_publication_url(url: str, *, label: str, allow_article: bool = False) -> None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        raise ParseError(f"WKAP Edition {label} must be a public X URL.")
    allowed_segments = {"status"}
    if allow_article:
        allowed_segments.add("article")
    path_segments = {segment.lower() for segment in parsed.path.split("/") if segment}
    if not (allowed_segments & path_segments) or not re.search(r"/\d+(?:/|$)", parsed.path):
        raise ParseError(f"WKAP Edition {label} must include a public X {'Article or status' if allow_article else 'status'} ID.")


def _wkap_analysis(value) -> tuple[dict, int]:
    if not isinstance(value, dict):
        raise ParseError("WKAP Edition analysis must be an object.")
    _reject_creative_unknown_fields(
        value,
        {"market_take", "what_market_misses", "watch_next", "invalidation", "sections"},
        label="analysis",
    )
    sections = value.get("sections")
    if not isinstance(sections, list) or not 3 <= len(sections) <= 12:
        raise ParseError("WKAP Edition analysis.sections must contain 3 to 12 sections.")
    parsed_sections = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise ParseError(f"WKAP Edition analysis section {index} must be an object.")
        _reject_creative_unknown_fields(section, {"heading", "paragraphs", "source_urls"}, label=f"analysis section {index}")
        paragraphs = section.get("paragraphs")
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 12:
            raise ParseError(f"WKAP Edition analysis section {index} must contain 1 to 12 paragraphs.")
        cleaned_paragraphs = []
        for paragraph in paragraphs:
            text = str(paragraph or "").strip()
            if not text or len(text) > 2400:
                raise ParseError(f"WKAP Edition analysis section {index} paragraphs must be non-blank and at most 2400 characters.")
            cleaned_paragraphs.append(text)
        parsed_sections.append(
            {
                "heading": _required_text(section, "heading", max_length=300),
                "paragraphs": cleaned_paragraphs,
                "source_urls": _creative_source_urls(section.get("source_urls"), label=f"analysis section {index}"),
            }
        )
    analysis = {
        "market_take": _required_text(value, "market_take", max_length=1800),
        "what_market_misses": _required_text(value, "what_market_misses", max_length=1800),
        "watch_next": _required_text_list(value, "watch_next", max_items=10, max_item_length=1200),
        "invalidation": _required_text_list(value, "invalidation", max_items=10, max_item_length=1200),
        "sections": parsed_sections,
    }
    article_text = " ".join(
        [
            analysis["market_take"],
            analysis["what_market_misses"],
            *analysis["watch_next"],
            *analysis["invalidation"],
            *(part for section in parsed_sections for part in [section["heading"], *section["paragraphs"]]),
        ]
    )
    return analysis, len(re.findall(r"\b\w+\b", article_text, flags=re.UNICODE))


def _wkap_challenge(value) -> dict:
    if not isinstance(value, dict):
        raise ParseError("WKAP Edition challenge must be an object.")
    _reject_creative_unknown_fields(value, {"invitation", "x_url", "moltbook_url", "featured_contribution"}, label="challenge")
    invitation = _required_text(value, "invitation", max_length=300)
    if invitation != DAILY_MARKET_MEME_CHALLENGE:
        raise ParseError("WKAP Edition challenge invitation must use the fixed Daily Market Meme Challenge wording.")
    x_url = _required_https_url(value, "x_url")
    _require_x_publication_url(x_url, label="challenge.x_url")
    result = {"invitation": invitation, "x_url": x_url}
    moltbook_url = str(value.get("moltbook_url") or "").strip()
    if moltbook_url:
        parsed = urlparse(moltbook_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {"moltbook.com", "www.moltbook.com"}:
            raise ParseError("WKAP Edition challenge.moltbook_url must be a public Moltbook URL.")
        result["moltbook_url"] = moltbook_url
    featured = value.get("featured_contribution")
    if featured is not None:
        if not isinstance(featured, dict):
            raise ParseError("WKAP Edition challenge.featured_contribution must be an object.")
        _reject_creative_unknown_fields(featured, {"credit", "source_url"}, label="challenge.featured_contribution")
        source_url = _required_https_url(featured, "source_url")
        result["featured_contribution"] = {
            "credit": _required_text(featured, "credit", max_length=500),
            "source_url": source_url,
        }
    return result


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


def _canonical_parsed_packet_json(packet: dict, *, investor_id: str) -> dict:
    payload = _json_safe(packet)
    payload.pop("author_id", None)
    payload["investor_id"] = investor_id
    if isinstance(payload.get("agent_facts"), dict):
        payload["agent_facts"].pop("author_id", None)
        payload["agent_facts"]["investor_id"] = investor_id
    for item in payload.get("wow_items") or []:
        if isinstance(item, dict):
            item.pop("author_id", None)
            if isinstance(item.get("agent_facts"), dict):
                item["agent_facts"].pop("author_id", None)
            if str(item.get("wow_type") or "") == "status_update":
                item["investor_id"] = str(item.get("investor_id") or investor_id)
    return payload


def _canonical_parsed_agent_facts(agent_facts: dict, *, counts: dict, packet_spec_version: str, investor_id: str) -> dict:
    payload = _json_safe({**agent_facts, **counts, "packet_spec_version": packet_spec_version})
    payload.pop("author_id", None)
    payload["investor_id"] = investor_id
    return payload


def _structured_packet_investor_id(packet: dict, *, assigned_investor_id: str = "") -> str:
    assigned = str(assigned_investor_id or "").strip().lower()
    supplied = {
        "investor_id": str(packet.get("investor_id") or "").strip(),
        "author_id": str(packet.get("author_id") or "").strip(),
    }
    public_values = {field: value.lower() for field, value in supplied.items() if _is_public_investor_id(value)}
    if assigned:
        for field, value in public_values.items():
            if value != assigned:
                raise ParseError(
                    f"Structured WoW Packet {field} must match sender-assigned investor_id: {assigned}"
                )
        return assigned
    if public_values:
        unique_values = set(public_values.values())
        if len(unique_values) > 1:
            raise ParseError("Structured WoW Packet investor_id conflicts with legacy author_id.")
        return next(iter(unique_values))
    investor_id = supplied["investor_id"] or supplied["author_id"]
    if not investor_id:
        raise ParseError("Structured WoW Packet requires investor_id.")
    return investor_id


def _is_public_investor_id(value: str) -> bool:
    return bool(re.match(r"^w\d{4}$", str(value or "").strip(), flags=re.IGNORECASE))


def _public_wow_owner_id(value: str) -> str:
    match = re.match(r"^WOW-(w\d{4})-\d{4}-\d{2}-\d{2}-\d{3}$", str(value or "").strip(), flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _validate_structured_wow_items(items: list[dict], *, packet_investor_id: str = "", assigned_investor_id: str = "") -> None:
    assigned = str(assigned_investor_id or "").strip().lower()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ParseError(f"Structured WoW item {index} must be an object.")
        wow_id = str(item.get("wow_id") or "").strip()
        if not wow_id:
            raise ParseError(f"Structured WoW item {index} missing wow_id.")
        if assigned:
            _validate_public_wow_ids_belong_to_sender(item, wow_id=wow_id, assigned_investor_id=assigned)
        wow_type = str(item.get("wow_type") or "").strip() or "candidate_wow"
        if wow_type not in VALID_WOW_TYPES:
            raise ParseError(f"Structured WoW item {wow_id} has invalid wow_type: {wow_type}")
        if wow_type == "scoreable_signal" and str(item.get("signal_status") or "").strip() == "pending":
            item["signal_status"] = "pending_scoreable"
        if wow_type == "status_update":
            item_investor_id = str(item.get("investor_id") or item.get("author_id") or "").strip()
            if (
                item_investor_id
                and packet_investor_id
                and _is_public_investor_id(item_investor_id)
                and item_investor_id.lower() != packet_investor_id.lower()
            ):
                raise ParseError(
                    f"status_update {wow_id} investor_id must match packet investor_id: {packet_investor_id}"
                )
            missing = [
                field
                for field in (
                    "target_wow_type",
                    "target_wow_id",
                    "target_root_wow_id",
                    "update_type",
                    "previous_status",
                    "update_summary",
                    "evidence_summary",
                )
                if not str(item.get(field) or "").strip()
            ]
            new_status = str(item.get("new_status") or item.get("signal_status") or item.get("trackable_status") or "").strip()
            if not new_status:
                missing.append("new_status")
            update_type = str(item.get("update_type") or "").strip()
            if update_type == "resolution" and new_status in {"resolved_correct", "resolved_incorrect"}:
                if not str(item.get("resolution_source_used") or "").strip():
                    missing.append("resolution_source_used")
            if missing:
                raise ParseError(f"status_update {wow_id} missing required fields: {', '.join(missing)}")
            transition_error = validate_status_transition(
                target_wow_type=str(item.get("target_wow_type") or "").strip(),
                previous_status=str(item.get("previous_status") or "").strip(),
                new_status=new_status,
                update_type=update_type,
            )
            if transition_error:
                raise ParseError(f"status_update {wow_id} invalid transition: {transition_error}")
            continue
        _validate_required_wow_type_fields(item, wow_id, wow_type)
        root_wow_id = str(item.get("root_wow_id") or "").strip()
        if not root_wow_id:
            raise ParseError(f"Structured WoW item {wow_id} missing root_wow_id.")
        parent_wow_id = item.get("parent_wow_id")
        if parent_wow_id in (None, "") and root_wow_id != wow_id:
            raise ParseError(f"Structured WoW item {wow_id} root_wow_id must equal wow_id when parent_wow_id is null.")


def _validate_public_wow_ids_belong_to_sender(item: dict, *, wow_id: str, assigned_investor_id: str) -> None:
    for field in ("wow_id", "parent_wow_id", "root_wow_id", "target_wow_id", "target_root_wow_id"):
        owner_id = _public_wow_owner_id(str(item.get(field) or ""))
        if owner_id and owner_id != assigned_investor_id:
            raise ParseError(f"{field} on {wow_id} must use sender investor_id: {assigned_investor_id}")


def _validate_required_wow_type_fields(item: dict, wow_id: str, wow_type: str) -> None:
    missing = [field for field in WOW_TYPE_REQUIRED_FIELDS.get(wow_type, ()) if not _has_value(item.get(field))]
    if missing:
        raise ParseError(f"{wow_type} {wow_id} missing required fields: {', '.join(missing)}")


def _has_value(value) -> bool:
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())


def _validate_closest_rejected_wow(value: str, suggested_wows: list[ParsedAgentSuggestedWoW]) -> None:
    rejected_wow_id = local_wow_id(value)
    known_ids = {wow.wow_id for wow in suggested_wows}
    if rejected_wow_id not in known_ids:
        raise ParseError(f"closest_rejected_wow must match one of today's suggested WoW IDs: {', '.join(sorted(known_ids))}")


def _public_pass_field_names(names: list[str]) -> str:
    return ", ".join("closest_rejected_wow" if name == "closest_rejected_idea" else name for name in names)


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
    match = re.search(r"\b(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\b", subject or "")
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


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
