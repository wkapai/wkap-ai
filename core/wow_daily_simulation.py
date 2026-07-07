from __future__ import annotations

import json
import re
import shutil
import uuid
from html import unescape
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from ingestion.models import RawEmail
from ledger.models import DailyWoWPacket, Investor, LedgerEvent
from ledger.parsers import ParseError, parse_wow
from ledger.services import create_wow_submission
from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS, validate_status_transition
from publishing.services import publish_artifact, rebuild_indexes, validate_ledger


DAILY_PROMPT = "Pick one WoW: 1, 2, 3, or pass."
SUBMISSION_ACK_PROMPT = "Choice accepted. I will save, submit, and reconcile this in the background."
SIM_INVESTOR_ID = "w0998"
SIM_EMAIL = "wkap-daily-wow-sim@example.com"
SIM_DISPLAY_NAME = "WKAP Daily WoW Simulation Agent"
SIM_GENERATED_BLOCK_ID = "daily-wow-simulation"
SIM_CASE_NAME_MARKERS = (
    "select_scoreable_with_reason",
    "select_missing_reason_then_train",
    "pass_complete",
    "pass_missing_closest_then_fix",
    "natural_language_choice",
    "user_no_reply_private_only",
    "lifecycle_",
)

VISIBLE_TYPE_LABELS = {
    "candidate_wow": "Candidate",
    "trackable_wow": "Trackable",
    "scoreable_signal": "Scoreable",
    "thesis_wow": "Thesis",
    "status_update": "Status Update",
}

NORMAL_WOW_REQUIRED_FIELDS = {
    "candidate_wow": ("wow_id", "wow_type", "parent_wow_id", "root_wow_id", "observation", "why_worth_watching", "candidate_status", "source_refs"),
    "trackable_wow": ("wow_id", "wow_type", "parent_wow_id", "root_wow_id", "claim", "evidence_to_watch", "review_cadence", "next_review_at", "trackable_status", "source_refs"),
    "scoreable_signal": ("wow_id", "wow_type", "parent_wow_id", "root_wow_id", "claim", "invalidate_test", "resolve_by", "resolution_source", "signal_status", "source_refs"),
    "thesis_wow": ("wow_id", "wow_type", "parent_wow_id", "root_wow_id", "thesis_claim", "thesis_status", "source_refs"),
}

STATUS_UPDATE_REQUIRED_FIELDS = (
    "wow_id",
    "wow_type",
    "target_wow_type",
    "target_wow_id",
    "target_root_wow_id",
    "update_type",
    "previous_status",
    "new_status",
    "update_summary",
    "evidence_summary",
    "source_refs",
)

READING_SAMPLES = [
    {
        "source_title": "CoreWeave and Meta announce $21 billion expanded AI infrastructure agreement",
        "source_url": "https://www.coreweave.com/news/coreweave-and-meta-announce-21-billion-expanded-ai-infrastructure-agreement",
        "source_type": "press_release",
        "source_date": "2026-04-09",
        "tickers": ["CRWV", "META", "NVDA"],
        "themes": ["AI infrastructure", "AI inference", "Vera Rubin deployments"],
        "agent_summary": "CoreWeave says Meta will use dedicated AI cloud capacity through 2032, including early NVIDIA Vera Rubin deployments. This gives the agent a concrete capacity-contract data point instead of generic AI capex language.",
    },
    {
        "source_title": "TSMC Q4 2025 earnings transcript",
        "source_url": "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-01/51d09df96cd89ac19d65af39032b038dc2896a24/TSMC%204Q25%20Transcript.pdf",
        "source_type": "earnings_transcript",
        "source_date": "2026-01-16",
        "tickers": ["TSM", "NVDA", "AMD"],
        "themes": ["advanced packaging", "AI accelerators", "Foundry 2.0"],
        "agent_summary": "TSMC guided 2026 foundry growth around robust AI demand and called out leading-edge, specialty, and advanced packaging demand. This is a real evidence stream for whether AI supply bottlenecks move beyond GPUs.",
    },
    {
        "source_title": "Circle reports first quarter 2026 results",
        "source_url": "https://www.circle.com/pressroom/circle-reports-first-quarter-2026-results",
        "source_type": "earnings_release",
        "source_date": "2026-05-11",
        "tickers": ["CRCL", "COIN"],
        "themes": ["stablecoin reserve income", "USDC circulation", "distribution costs"],
        "agent_summary": "Circle reported reserve income up 17% year over year, helped by higher average USDC in circulation and partly offset by a lower reserve return rate. Distribution and transaction costs rose alongside growth, making this a clean scoreable unit-economics sample.",
    },
    {
        "source_title": "BMO introduces tokenized cash and deposit platform with CME Group and Google Cloud",
        "source_url": "https://www.cmegroup.com/media-room/press-releases/2026/3/24/bmo-introduces-tokenized-cash-and-deposit-platform-with-cme-group-and-google-cloud.html",
        "source_type": "press_release",
        "source_date": "2026-03-24",
        "tickers": ["CME", "GOOGL"],
        "themes": ["tokenized deposits", "24/7 settlement", "collateral mobility"],
        "agent_summary": "BMO, CME Group, and Google Cloud described tokenized cash for 24/7 institutional settlement and margin workflows. This gives the agent a market-structure sample that can become a candidate or thesis WoW.",
    },
    {
        "source_title": "Tesla Q1 2026 update",
        "source_url": "https://ir.tesla.com/_flysystem/s3/sec/000162828026026551/tsla-20260422-gen.pdf",
        "source_type": "shareholder_update",
        "source_date": "2026-04-22",
        "tickers": ["TSLA"],
        "themes": ["robotaxi", "unsupervised autonomy", "inference latency"],
        "agent_summary": "Tesla said it upgraded reinforcement learning, vision encoding, compiler iteration speed, and runtime latency for unsupervised autonomy. This is useful only if the user can translate launch language into utilization and safety evidence.",
    },
    {
        "source_title": "Amazon signs data center energy pledge and details grid-cost commitments",
        "source_url": "https://www.aboutamazon.com/news/policy-news-views/amazon-data-centers-power-costs-white-house-pledge",
        "source_type": "company_update",
        "source_date": "2026-03-01",
        "tickers": ["AMZN"],
        "themes": ["AI data centers", "grid upgrades", "power procurement"],
        "agent_summary": "Amazon says it pays full data center energy costs, including new generation and grid upgrades, and points to 700-plus carbon-free projects delivering more than 40 GW. This grounds the AI power bottleneck in utility and ratepayer evidence.",
    },
    {
        "source_title": "Constellation and Microsoft Crane Clean Energy Center agreement",
        "source_url": "https://www.constellationenergy.com/about/locations/crane-clean-energy-center.html",
        "source_type": "project_page",
        "source_date": "2026-07-06",
        "tickers": ["CEG", "MSFT"],
        "themes": ["nuclear power", "AI data centers", "PPA"],
        "agent_summary": "Constellation describes a large Microsoft PPA tied to restarting Three Mile Island Unit 1 as the Crane Clean Energy Center. This is a concrete power-supply evidence item for AI data center deployment.",
    },
]


@dataclass
class ConversationTurn:
    actor: str
    message: str
    state: str
    normalized: dict[str, str] = field(default_factory=dict)


@dataclass
class SimulationCase:
    name: str
    market_date: date
    state: dict[str, Any]
    turns: list[ConversationTurn]
    validation_errors: list[str] = field(default_factory=list)
    packet: dict[str, Any] | None = None
    packet_markdown: str = ""
    parse_error: str = ""
    published_url: str = ""
    published_packet_id: int | None = None
    ledger_errors: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.state.get("state") in {"ready_to_submit", "submission_in_progress", "submitted", "verified"}


def default_journal_path() -> Path:
    return settings.BASE_DIR / "WKAP WoW Journal"


def ensure_private_journal(journal_path: Path) -> list[Path]:
    created: list[Path] = []
    required_files = {
        "active-trackables.md": "# Active Trackables\n\nPrivate WKAP WoW Journal file. Append active `trackable_wow` items here.\n",
        "pending-scoreables.md": "# Pending Scoreables\n\nPrivate WKAP WoW Journal file. Append pending `scoreable_signal` items here, including resolution source and resolve-by date.\n",
        "thesis-map.md": "# Thesis Map\n\nPrivate WKAP WoW Journal file. Track `thesis_wow` items and child WoW relationships here.\n",
        "receipts.md": "# Receipts\n\nPrivate WKAP WoW Journal file. Record WKAP submission receipts and receipt reconciliation here.\n",
        "public-verification.md": "# Public Verification\n\nPrivate WKAP WoW Journal file. Record WKAP public ledger URLs and public site reconciliation here.\n",
    }
    for directory in (journal_path, journal_path / "daily", journal_path / "simulation"):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(directory)
    for filename, body in required_files.items():
        path = journal_path / filename
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            created.append(path)
    return created


def reset_daily_wow_simulation(
    *,
    journal_path: Path | None = None,
    investor_id: str = SIM_INVESTOR_ID,
    rebuild_public: bool = True,
) -> dict[str, Any]:
    journal = journal_path or default_journal_path()
    packet_ids = list(DailyWoWPacket.objects.filter(investor__investor_id=investor_id).values_list("id", flat=True))
    raw_email_count = RawEmail.objects.filter(sender_email=SIM_EMAIL).count()
    investor_count = Investor.objects.filter(investor_id=investor_id, email_private=SIM_EMAIL).count()

    event_filter = Q(investor_id=investor_id) | Q(sender_email=SIM_EMAIL)
    if packet_ids:
        event_filter |= Q(entity_type="wow", entity_id__in=[str(packet_id) for packet_id in packet_ids])
    ledger_event_count = LedgerEvent.objects.filter(event_filter).count()

    LedgerEvent.objects.filter(event_filter).delete()
    DailyWoWPacket.objects.filter(investor__investor_id=investor_id).delete()
    RawEmail.objects.filter(sender_email=SIM_EMAIL).delete()
    Investor.objects.filter(investor_id=investor_id, email_private=SIM_EMAIL).delete()

    ledger_root = _ledger_artifact_root()
    allowed_roots = [settings.BASE_DIR, settings.WKAP_PUBLIC_SITE_ROOT, ledger_root, journal]
    removed_paths: list[str] = []

    def remove(path: Path) -> None:
        removed = _safe_remove_path(path, allowed_roots=allowed_roots)
        if removed:
            removed_paths.append(str(removed))

    remove(settings.WKAP_PUBLIC_SITE_ROOT / "investors" / investor_id)
    for packet_id in packet_ids:
        remove(ledger_root / "manifests" / f"wow-{packet_id}.json")
        remove(ledger_root / "timestamps" / f"wow-{packet_id}.json")
        remove(ledger_root / "timestamps" / f"wow-{packet_id}.json.ots")
    raw_email_dir = ledger_root / "raw-emails" / "wow-packets"
    if raw_email_dir.exists():
        for path in raw_email_dir.glob(f"wow-packet-{investor_id}-*.txt"):
            remove(path)

    daily_dir = journal / "daily"
    if daily_dir.exists():
        for marker in SIM_CASE_NAME_MARKERS:
            for path in daily_dir.glob(f"*-{marker}*.md"):
                remove(path)
    remove(journal / "user-judgment-profile.md")
    remove(journal / "simulation" / "daily-wow-pressure-test-report.md")

    journal_blocks_removed = 0
    for filename in ("receipts.md", "public-verification.md", "active-trackables.md", "pending-scoreables.md", "thesis-map.md"):
        if _remove_generated_block(journal / filename, SIM_GENERATED_BLOCK_ID):
            journal_blocks_removed += 1

    if rebuild_public:
        rebuild_indexes(run_id=uuid.uuid4())

    return {
        "investor_id": investor_id,
        "sender_email": SIM_EMAIL,
        "deleted": {
            "daily_wow_packets": len(packet_ids),
            "raw_emails": raw_email_count,
            "ledger_events": ledger_event_count,
            "investors": investor_count,
            "journal_blocks": journal_blocks_removed,
            "paths": len(removed_paths),
        },
        "removed_paths": removed_paths,
        "public_indexes_rebuilt": rebuild_public,
    }


def reset_all_local_wow_data(*, journal_path: Path | None = None, rebuild_public: bool = True) -> dict[str, Any]:
    journal = journal_path or default_journal_path()
    packet_ids = list(DailyWoWPacket.objects.values_list("id", flat=True))
    raw_email_ids = list(DailyWoWPacket.objects.values_list("source_email_id", flat=True))
    investor_ids = list(DailyWoWPacket.objects.order_by().values_list("investor__investor_id", flat=True).distinct())

    raw_email_filter = (
        Q(id__in=raw_email_ids)
        | Q(classification=RawEmail.Classification.WOW)
        | Q(subject__icontains="Daily WoW Packet")
        | Q(sender_email=SIM_EMAIL)
    )
    raw_email_count = RawEmail.objects.filter(raw_email_filter, radar_issues__isnull=True).distinct().count()

    event_filter = Q(entity_type="wow") | Q(event_name__startswith="wow_")
    if investor_ids:
        event_filter |= Q(investor_id__in=investor_ids) | Q(entity_type="investor", investor_id__in=investor_ids)
    event_filter |= Q(sender_email=SIM_EMAIL)
    ledger_event_count = LedgerEvent.objects.filter(event_filter).count()
    investor_count = Investor.objects.filter(investor_id__in=investor_ids).count()

    LedgerEvent.objects.filter(event_filter).delete()
    DailyWoWPacket.objects.all().delete()
    RawEmail.objects.filter(raw_email_filter, radar_issues__isnull=True).distinct().delete()
    if investor_ids:
        Investor.objects.filter(investor_id__in=investor_ids).delete()

    ledger_root = _ledger_artifact_root()
    allowed_roots = [settings.BASE_DIR, settings.WKAP_PUBLIC_SITE_ROOT, ledger_root, journal]
    removed_paths: list[str] = []

    def remove(path: Path) -> None:
        removed = _safe_remove_path(path, allowed_roots=allowed_roots)
        if removed:
            removed_paths.append(str(removed))

    remove(settings.WKAP_PUBLIC_SITE_ROOT / "investors")
    for packet_id in packet_ids:
        remove(ledger_root / "manifests" / f"wow-{packet_id}.json")
        remove(ledger_root / "timestamps" / f"wow-{packet_id}.json")
        remove(ledger_root / "timestamps" / f"wow-{packet_id}.json.ots")
    raw_email_dir = ledger_root / "raw-emails" / "wow-packets"
    if raw_email_dir.exists():
        for path in raw_email_dir.glob("wow-packet-*.txt"):
            remove(path)
    remove(journal)

    if rebuild_public:
        rebuild_indexes(run_id=uuid.uuid4())

    return {
        "investor_ids": investor_ids,
        "deleted": {
            "daily_wow_packets": len(packet_ids),
            "raw_emails": raw_email_count,
            "ledger_events": ledger_event_count,
            "investors": investor_count,
            "paths": len(removed_paths),
        },
        "removed_paths": removed_paths,
        "public_indexes_rebuilt": rebuild_public,
    }


def verify_published_simulation(
    *,
    investor_id: str = SIM_INVESTOR_ID,
    packet_ids: set[int] | None = None,
    expected_packet_count: int | None = 32,
    require_full_transition_coverage: bool = True,
) -> dict[str, Any]:
    packet_qs = DailyWoWPacket.objects.filter(investor__investor_id=investor_id)
    if packet_ids is not None:
        packet_qs = packet_qs.filter(id__in=packet_ids)
    packets = list(packet_qs.order_by("market_date"))
    errors: list[str] = []
    warnings: list[str] = []
    page_count = 0
    status_update_pages = 0
    repeated_type_pages = 0
    pass_pages = 0
    selected_pages = 0
    expected_transition_set = {
        (target_wow_type, previous_status, new_status)
        for target_wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items()
        for previous_status, new_statuses in previous_map.items()
        for new_status in new_statuses
    }

    if expected_packet_count is not None and len(packets) != expected_packet_count:
        errors.append(f"expected {expected_packet_count} published simulator packets for {investor_id}, found {len(packets)}")

    for packet in packets:
        ledger_errors = validate_ledger("wow", packet.id)
        if ledger_errors:
            errors.append(f"{packet.packet_id}: validate_ledger errors: {ledger_errors}")
        page_path = Path(settings.WKAP_PUBLIC_SITE_ROOT) / urlparse(packet.canonical_url).path.lstrip("/")
        if not page_path.exists():
            errors.append(f"{packet.packet_id}: missing public page {page_path}")
            continue
        page_count += 1
        text = page_path.read_text(encoding="utf-8")
        if text.count("data-packet-wow-id=") < 3:
            errors.append(f"{packet.packet_id}: page exposes fewer than 3 packet wow ids")
        if packet.packet_id not in text:
            errors.append(f"{packet.packet_id}: page missing canonical packet id")

        raw_packet = _page_json_field(text, "raw_packet_json", page_path, errors)
        wow_items = _page_json_field(text, "wow_items_json", page_path, errors)
        lifecycle_events = _page_json_field(text, "lifecycle_events_json", page_path, errors)
        current_wow_state = _page_json_field(text, "current_wow_state_json", page_path, errors)
        status_updates = _page_json_field(text, "status_updates_json", page_path, errors)
        if raw_packet is None or wow_items is None:
            continue

        types = [item.get("wow_type") for item in wow_items]
        if len(set(types)) < len(types):
            repeated_type_pages += 1
        status_update_pages += types.count("status_update")
        if packet.selected_wow_id == "none":
            pass_pages += 1
        else:
            selected_pages += 1
        _verify_page_packet_fields(
            packet=packet,
            investor_id=investor_id,
            raw_packet=raw_packet,
            wow_items=wow_items,
            lifecycle_events=lifecycle_events,
            current_wow_state=current_wow_state,
            status_updates=status_updates,
            text=text,
            errors=errors,
        )

    status_event_qs = LedgerEvent.objects.filter(
        investor_id=investor_id,
        event_name="wow_lifecycle_status_update_logged",
        entity_type="wow",
    )
    if packet_ids is not None:
        status_event_qs = status_event_qs.filter(entity_id__in={str(packet_id) for packet_id in packet_ids})
    status_events = list(status_event_qs)
    actual_transition_set = {
        (event.details.get("target_wow_type"), event.details.get("previous_status"), event.details.get("new_status"))
        for event in status_events
    }
    if require_full_transition_coverage and len(status_events) != len(expected_transition_set):
        errors.append(f"expected {len(expected_transition_set)} status update events, found {len(status_events)}")
    missing_transitions = sorted(expected_transition_set - actual_transition_set) if require_full_transition_coverage else []
    extra_transitions = sorted(actual_transition_set - expected_transition_set)
    if missing_transitions:
        errors.append(f"missing lifecycle transitions: {missing_transitions}")
    if extra_transitions:
        errors.append(f"unexpected lifecycle transitions: {extra_transitions}")
    if require_full_transition_coverage and repeated_type_pages == 0:
        errors.append("all published pages use one of each wow_type; expected at least one repeated-type page to prove the slate is not fixed-format")

    return {
        "investor_id": investor_id,
        "packets": len(packets),
        "packet_ids": sorted(packet_ids) if packet_ids is not None else [packet.id for packet in packets],
        "pages_checked": page_count,
        "status_update_pages": status_update_pages,
        "status_update_events": len(status_events),
        "expected_transition_count": len(expected_transition_set),
        "full_transition_coverage_required": require_full_transition_coverage,
        "repeated_type_pages": repeated_type_pages,
        "selected_pages": selected_pages,
        "pass_pages": pass_pages,
        "errors": errors,
        "warnings": warnings,
    }


def _page_field(text: str, field_name: str) -> str | None:
    match = re.search(rf'<dd data-field="{re.escape(field_name)}">(.*?)</dd>', text, flags=re.DOTALL)
    return unescape(match.group(1)).strip() if match else None


def _page_json_field(text: str, field_name: str, page_path: Path, errors: list[str]) -> Any:
    value = _page_field(text, field_name)
    if value is None:
        errors.append(f"{page_path.name}: missing data-field={field_name}")
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        errors.append(f"{page_path.name}: data-field={field_name} is not parseable JSON: {exc}")
        return None


def _local_public_wow_id(value: str, investor_id: str) -> str:
    value = str(value or "")
    prefix = f"WOW-{investor_id}-"
    return "WOW-" + value[len(prefix) :] if value.startswith(prefix) else value


def _verify_page_packet_fields(
    *,
    packet: DailyWoWPacket,
    investor_id: str,
    raw_packet: dict[str, Any],
    wow_items: list[dict[str, Any]],
    lifecycle_events: list[dict[str, Any]] | None,
    current_wow_state: list[dict[str, Any]] | None,
    status_updates: list[dict[str, Any]] | None,
    text: str,
    errors: list[str],
) -> None:
    if len(wow_items) != 3:
        errors.append(f"{packet.packet_id}: expected 3 wow_items, found {len(wow_items)}")
    types = [item.get("wow_type") for item in wow_items]
    counts = {
        "wow_count": len(types),
        "scoreable_count": types.count("scoreable_signal"),
        "trackable_count": types.count("trackable_wow"),
        "thesis_count": types.count("thesis_wow"),
        "candidate_count": types.count("candidate_wow"),
        "status_update_count": types.count("status_update"),
    }
    stored_counts = {
        "wow_count": packet.wow_count,
        "scoreable_count": packet.scoreable_count,
        "trackable_count": packet.trackable_count,
        "thesis_count": packet.thesis_count,
        "candidate_count": packet.candidate_count,
        "status_update_count": packet.status_update_count,
    }
    if counts != stored_counts:
        errors.append(f"{packet.packet_id}: page counts {counts} do not match DB counts {stored_counts}")
    if raw_packet.get("agent_facts", {}).get("status_update_count") != packet.status_update_count:
        errors.append(f"{packet.packet_id}: raw_packet agent status_update_count mismatch")

    reading_refs = {f"Reading Item {item.get('item_number')}" for item in raw_packet.get("reading_log", [])}
    for item in wow_items:
        missing_refs = [ref for ref in item.get("source_refs", []) if ref not in reading_refs]
        if missing_refs:
            errors.append(f"{packet.packet_id}: {item.get('wow_id')} has unresolved source_refs {missing_refs}")
        if item.get("wow_type") == "status_update":
            if 'data-agent-lifecycle="status_updates"' not in text:
                errors.append(f"{packet.packet_id}: status_update page missing data-agent-lifecycle=status_updates")
            for field_name in ("target_wow_type", "target_wow_id", "target_root_wow_id", "previous_status", "new_status", "update_type", "evidence_summary"):
                if not item.get(field_name):
                    errors.append(f"{packet.packet_id}: status_update {item.get('wow_id')} missing {field_name}")
            explicit_investor = item.get("investor_id")
            if explicit_investor and explicit_investor != investor_id:
                errors.append(f"{packet.packet_id}: status_update investor_id mismatch {explicit_investor}")

    if packet.status_update_count and not status_updates:
        errors.append(f"{packet.packet_id}: status_update_count={packet.status_update_count} but status_updates_json empty")
    if lifecycle_events is not None and len(lifecycle_events) != 3:
        errors.append(f"{packet.packet_id}: lifecycle_events_json expected 3 records, found {len(lifecycle_events)}")
    if current_wow_state is not None and len(current_wow_state) != 3:
        errors.append(f"{packet.packet_id}: current_wow_state_json expected 3 records, found {len(current_wow_state)}")

    selection = raw_packet.get("selection", {})
    option_ids = {_local_public_wow_id(item.get("wow_id"), investor_id) for item in wow_items}
    if packet.selected_wow_id == "none":
        for field_name in ("reason_for_pass", "closest_rejected_wow", "missing_evidence"):
            if not selection.get(field_name):
                errors.append(f"{packet.packet_id}: pass missing {field_name}")
        if _local_public_wow_id(selection.get("closest_rejected_wow"), investor_id) not in option_ids:
            errors.append(f"{packet.packet_id}: closest_rejected_wow is not one of the 3 options")
    else:
        if _local_public_wow_id(packet.selected_wow_id, investor_id) not in option_ids:
            errors.append(f"{packet.packet_id}: selected_wow_id not in 3 options")
        if _local_public_wow_id(selection.get("selected_wow_id"), investor_id) not in option_ids:
            errors.append(f"{packet.packet_id}: raw_packet selected_wow_id not in 3 options")
        if not packet.reason_for_selection:
            errors.append(f"{packet.packet_id}: selected page missing reason_for_selection")


def reading_log_for_day(market_date: date, *, offset: int = 0, count: int = 7) -> list[dict[str, Any]]:
    readings = []
    for index in range(count):
        sample = READING_SAMPLES[(offset + index) % len(READING_SAMPLES)]
        readings.append(
            {
                "item_number": index + 1,
                "source_title": sample["source_title"],
                "source_url": sample["source_url"],
                "source_type": sample["source_type"],
                "published_time": sample.get("source_date", market_date.isoformat()),
                "tickers": sample["tickers"],
                "themes": sample["themes"],
                "reading_origin": "agent_suggested" if index % 2 else "user_browsed",
                "agent_summary": sample["agent_summary"],
            }
        )
    return readings


def _reading_refs_for(
    reading_log: list[dict[str, Any]],
    *,
    themes: tuple[str, ...],
    tickers: tuple[str, ...],
    limit: int = 2,
) -> list[str]:
    matched: list[str] = []
    theme_terms = {theme.lower() for theme in themes}
    ticker_terms = {ticker.lower() for ticker in tickers}
    for item in reading_log:
        item_themes = {str(theme).lower() for theme in item.get("themes", [])}
        item_tickers = {str(ticker).lower() for ticker in item.get("tickers", [])}
        if item_themes & theme_terms or item_tickers & ticker_terms:
            matched.append(f"Reading Item {item['item_number']}")
    if not matched:
        matched = [f"Reading Item {item['item_number']}" for item in reading_log[:limit]]
    return matched[:limit]


def base_daily_options(
    market_date: date,
    *,
    investor_id: str = SIM_INVESTOR_ID,
    reading_log: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    readings = reading_log or reading_log_for_day(market_date)
    ai_refs = _reading_refs_for(readings, themes=("AI infrastructure", "advanced packaging", "grid upgrades", "nuclear power"), tickers=("CRWV", "TSM", "AMZN", "CEG"))
    circle_refs = _reading_refs_for(readings, themes=("stablecoin reserve income", "USDC circulation", "distribution costs"), tickers=("CRCL", "COIN"))
    cme_refs = _reading_refs_for(readings, themes=("tokenized deposits", "24/7 settlement", "collateral mobility"), tickers=("CME", "GOOGL"))
    first_id = wow_id(market_date, 1)
    second_id = wow_id(market_date, 2)
    third_id = wow_id(market_date, 3)
    return [
        with_visible_fields(
            {
                "wow_id": first_id,
                "wow_type": "trackable_wow",
                "scoreable": False,
                "accuracy_endpoint_eligible": False,
                "parent_wow_id": None,
                "root_wow_id": first_id,
                "claim": "AI infrastructure bottlenecks are becoming a combined capacity, packaging, and power problem rather than a simple GPU procurement story.",
                "evidence_to_watch": [
                    "CoreWeave capacity-contract updates",
                    "TSMC advanced packaging and leading-edge capacity commentary",
                    "data center power and grid-upgrade commitments",
                ],
                "review_cadence": "weekly",
                "next_review_at": (market_date + timedelta(days=7)).isoformat(),
                "trackable_status": "active_trackable",
                "source_refs": ai_refs,
                "agent_facts": {"wow_type": "trackable_wow", "scoreable": False, "accuracy_endpoint_eligible": False},
            },
            option_number=1,
            title="AI bottleneck evidence is moving into contracts, packaging, and power",
            why="CoreWeave, TSMC, Amazon, and Constellation give the user real evidence streams to monitor without forcing a binary prediction today.",
        ),
        with_visible_fields(
            {
                "wow_id": second_id,
                "wow_type": "scoreable_signal",
                "scoreable": True,
                "accuracy_endpoint_eligible": True,
                "parent_wow_id": None,
                "root_wow_id": second_id,
                "claim": "Circle's next reported reserve-income growth will be lower than average USDC-in-circulation growth if reserve return pressure remains the dominant offset.",
                "invalidate_test": "Circle reports reserve-income growth equal to or above average USDC-in-circulation growth in its next quarterly results, or does not disclose comparable metrics.",
                "resolve_by": "2026-08-31",
                "resolution_source": "Circle quarterly results press release or investor transcript",
                "signal_status": "pending_scoreable",
                "source_refs": circle_refs,
                "agent_facts": {"wow_type": "scoreable_signal", "scoreable": True, "accuracy_endpoint_eligible": True},
            },
            option_number=2,
            title="Circle reserve-income growth becomes a scoreable unit-economics check",
            why="The Q1 2026 release gives the user a real baseline, a deadline, an invalidate test, and a public resolution source.",
        ),
        with_visible_fields(
            {
                "wow_id": third_id,
                "wow_type": "trackable_wow",
                "scoreable": False,
                "accuracy_endpoint_eligible": False,
                "parent_wow_id": None,
                "root_wow_id": third_id,
                "claim": "Regulated tokenized-cash pilots are becoming monitorable infrastructure evidence rather than a broad crypto thesis.",
                "evidence_to_watch": [
                    "CME tokenized collateral or margin workflow updates",
                    "bank deposit-token adoption beyond pilots",
                    "Google Cloud or other infrastructure partner disclosures",
                ],
                "review_cadence": "monthly",
                "next_review_at": (market_date + timedelta(days=30)).isoformat(),
                "trackable_status": "active_trackable",
                "source_refs": cme_refs,
                "agent_facts": {"wow_type": "trackable_wow", "scoreable": False, "accuracy_endpoint_eligible": False},
            },
            option_number=3,
            title="CME tokenized cash becomes a monitorable settlement-rails signal",
            why="BMO, CME Group, and Google Cloud make this worth tracking, but the investable question is adoption cadence rather than a finished thesis.",
        ),
    ]


def with_visible_fields(item: dict[str, Any], *, option_number: int, title: str, why: str) -> dict[str, Any]:
    item = deepcopy(item)
    item["option_number"] = option_number
    item["visible_type_label"] = VISIBLE_TYPE_LABELS[item["wow_type"]]
    item["plain_english_title"] = title
    item["why_worth_watching"] = why if item["wow_type"] != "candidate_wow" else item.get("why_worth_watching") or why
    if item["wow_type"] == "status_update":
        item.setdefault("target_summary", title)
    return item


def initial_daily_state(
    *,
    investor_id: str,
    market_date: date,
    journal_path: Path,
    reading_log: list[dict[str, Any]],
    wow_options: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": "v0.2",
        "market_date": market_date.isoformat(),
        "investor_id": investor_id,
        "journal_path": str(journal_path),
        "state": "awaiting_user_choice",
        "reading_log": deepcopy(reading_log),
        "wow_options": deepcopy(wow_options),
        "selection": {
            "selected_wow_id": "",
            "reason_for_selection": "",
            "reason_for_pass": "",
            "closest_rejected_wow": "",
            "missing_evidence": "",
        },
    }


def render_daily_options_prompt(wow_options: list[dict[str, Any]]) -> str:
    lines = []
    for option in wow_options:
        lines.append(f"{option['option_number']}. {option['visible_type_label']}: {option['plain_english_title']}")
        lines.append(f"   Why: {option['why_worth_watching']}")
        if option["wow_type"] == "scoreable_signal":
            lines.append(f"   Test: {option['invalidate_test']}")
            lines.append(f"   Resolve by: {option['resolve_by']}")
            lines.append(f"   Resolution source: {option['resolution_source']}")
        elif option["wow_type"] == "trackable_wow":
            lines.append(f"   Watch: {', '.join(option.get('evidence_to_watch') or [])}")
            lines.append(f"   Review: {option.get('review_cadence', '')}, next {option.get('next_review_at', '')}")
        elif option["wow_type"] == "status_update":
            lines.append(f"   Target: {option['target_summary']}")
            lines.append(f"   Status: {option['previous_status']} to {option['new_status']}")
            lines.append(f"   Evidence: {option['evidence_summary']}")
    lines.append(DAILY_PROMPT)
    return "\n".join(lines)


def normalize_user_reply(state: dict[str, Any], user_reply: str) -> tuple[dict[str, Any], str, dict[str, str]]:
    next_state = deepcopy(state)
    normalized: dict[str, str] = {}
    current = next_state.get("state")
    if current == "awaiting_user_choice":
        choice = _choice_from_reply(user_reply, next_state["wow_options"])
        if choice == "pass":
            next_state["selection"]["selected_wow_id"] = "none"
            _merge_pass_fields(next_state, user_reply)
            missing = _missing_pass_fields(next_state)
            if missing:
                next_state["state"] = "awaiting_pass_fields"
                return next_state, _pass_prompt(missing), {"choice": "pass", "missing": ", ".join(missing)}
            next_state["state"] = "submission_in_progress"
            return next_state, SUBMISSION_ACK_PROMPT, {"choice": "pass", "submission": "background"}
        if isinstance(choice, int):
            selected = next_state["wow_options"][choice - 1]["wow_id"]
            reason = _reason_from_reply(user_reply)
            next_state["selection"]["selected_wow_id"] = selected
            normalized["selected_wow_id"] = selected
            if reason:
                next_state["selection"]["reason_for_selection"] = reason
                next_state["state"] = "submission_in_progress"
                normalized["reason_for_selection"] = reason
                normalized["submission"] = "background"
                return next_state, SUBMISSION_ACK_PROMPT, normalized
            next_state["state"] = "awaiting_selection_reason"
            return next_state, "Why did you select this WoW?", normalized
        return next_state, DAILY_PROMPT, {"unrecognized_reply": user_reply}

    if current == "awaiting_selection_reason":
        reason = _reason_from_reply(user_reply) or user_reply.strip()
        next_state["selection"]["reason_for_selection"] = reason
        next_state["state"] = "submission_in_progress"
        return next_state, SUBMISSION_ACK_PROMPT, {"reason_for_selection": reason, "submission": "background"}

    if current == "awaiting_pass_fields":
        _merge_pass_fields(next_state, user_reply)
        missing = _missing_pass_fields(next_state)
        if missing:
            return next_state, _pass_prompt(missing), {"missing": ", ".join(missing)}
        next_state["state"] = "submission_in_progress"
        return next_state, SUBMISSION_ACK_PROMPT, {"choice": "pass", "submission": "background"}

    return next_state, "", {}


def mark_no_reply(state: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    next_state["state"] = "user_no_reply"
    return next_state


def validate_daily_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field_name in ("version", "market_date", "investor_id", "state", "reading_log", "wow_options", "selection"):
        if field_name not in state:
            errors.append(f"daily_state missing required field: {field_name}")
    if errors:
        return errors
    if state["version"] != "v0.2":
        errors.append("daily_state version must be v0.2")
    if len(state["reading_log"]) > 10:
        errors.append("reading_log can include at most 10 items")
    options = state["wow_options"]
    if len(options) != 3:
        errors.append("daily state must include exactly 3 wow_options")
    option_ids = {str(option.get("wow_id") or "") for option in options}
    for index, option in enumerate(options, start=1):
        errors.extend(_validate_option(index, option))
    selected = state["selection"].get("selected_wow_id", "")
    if selected and selected != "none" and selected not in option_ids:
        errors.append("selected_wow_id must be one of today's 3 wow_options")
    if state["state"] in {"ready_to_submit", "submission_in_progress", "submitted", "verified"}:
        errors.extend(_validate_completed_selection(state, option_ids))
    return errors


def packet_from_state(state: dict[str, Any]) -> dict[str, Any]:
    counts = _wow_type_counts(state["wow_options"])
    packet_id = f"WKAP-{state['investor_id']}-{state['market_date']}"
    selected = state["selection"]["selected_wow_id"]
    return {
        "packet_id": packet_id,
        "investor_id": state["investor_id"],
        "market_date": state["market_date"],
        "created_at": f"{state['market_date']}T21:00:00Z",
        "packet_spec_version": "v0.2",
        "packet_spec_url": "https://wkap.ai/specs/wow-packet-v0.2.md",
        "packet_spec_latest_url": "https://wkap.ai/specs/wow-packet-latest.md",
        "skill_version": "v0.2",
        "skill_url": "https://wkap.ai/skills/wkap-wow-skill-latest.md",
        "human_view": {
            "title": _packet_title(state),
            "summary": "Local pressure-test packet generated from realistic market-reading samples.",
            "top_wows": [selected] if selected and selected != "none" else [],
        },
        "agent_facts": {
            "packet_id": packet_id,
            "investor_id": state["investor_id"],
            "packet_spec_version": "v0.2",
            **counts,
        },
        "reading_log": deepcopy(state["reading_log"]),
        "wow_items": [_packet_item(option) for option in state["wow_options"]],
        "selection": deepcopy(state["selection"]),
        "validation_notes": {
            "schema_valid": True,
            "missing_fields": [],
            "warnings": ["local_daily_conversation_simulation"],
        },
    }


def packet_markdown(packet: dict[str, Any]) -> str:
    return "# WKAP Daily WoW Packet\n\n```yaml\n" + yaml.safe_dump({"packet": packet}, sort_keys=False, allow_unicode=True) + "```\n"


def lifecycle_transition_options(
    market_date: date,
    *,
    investor_id: str,
    transition_number: int,
    target_wow_type: str,
    previous_status: str,
    new_status: str,
    reading_log: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    update_type = update_type_for_status(new_status, previous_status=previous_status)
    target_id = f"WOW-2026-06-01-{transition_number:03d}"
    update_id = wow_id(market_date, 1)
    readings = reading_log or reading_log_for_day(market_date, offset=transition_number)
    sample = readings[0]
    update = with_visible_fields(
        {
            "wow_id": update_id,
            "wow_type": "status_update",
            "investor_id": investor_id,
            "target_wow_type": target_wow_type,
            "target_wow_id": target_id,
            "target_root_wow_id": target_id,
            "update_type": update_type,
            "previous_status": previous_status,
            "new_status": new_status,
            "update_summary": f"{target_wow_type} moved from {previous_status} to {new_status}.",
            "target_summary": f"{target_wow_type} lifecycle maintenance for {sample['themes'][0]}",
            "evidence_summary": f"Real source evidence for this maintenance decision: {sample['source_title']} ({sample['source_url']}).",
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "lineage_node": False,
            "source_refs": ["Reading Item 1"],
            "agent_facts": {
                "wow_type": "status_update",
                "lineage_node": False,
                "target_wow_type": target_wow_type,
                "target_wow_id": target_id,
                "target_root_wow_id": target_id,
                "update_type": update_type,
                "previous_status": previous_status,
                "new_status": new_status,
            },
        },
        option_number=1,
        title=f"{target_wow_type} moves from {previous_status} to {new_status}",
        why="Lifecycle maintenance keeps the private CRM and public ledger state reconcilable.",
    )
    if update_type == "resolution" and new_status in {"resolved_correct", "resolved_incorrect"}:
        update["resolution_source_used"] = sample["source_url"]

    second = promotion_child_item(market_date, target_id=target_id, new_status=new_status) or base_daily_options(market_date, investor_id=investor_id, reading_log=readings)[1]
    second["option_number"] = 2
    third = base_daily_options(market_date, investor_id=investor_id, reading_log=readings)[2]
    third["option_number"] = 3
    return [update, second, third]


def promotion_child_item(market_date: date, *, target_id: str, new_status: str) -> dict[str, Any] | None:
    child_id = wow_id(market_date, 2)
    if new_status == "promoted_trackable":
        return with_visible_fields(
            {
                "wow_id": child_id,
                "wow_type": "trackable_wow",
                "scoreable": False,
                "accuracy_endpoint_eligible": False,
                "parent_wow_id": target_id,
                "root_wow_id": target_id,
                "claim": "The promoted idea now has a concrete evidence watchlist and review cadence.",
                "evidence_to_watch": ["repeat public source mentions", "company commentary", "pricing or volume signals"],
                "review_cadence": "weekly",
                "next_review_at": "2026-09-30",
                "trackable_status": "active_trackable",
                "source_refs": ["Reading Item 1"],
                "agent_facts": {"wow_type": "trackable_wow", "scoreable": False, "accuracy_endpoint_eligible": False},
            },
            option_number=2,
            title="Promoted child trackable for the existing candidate",
            why="The idea now has cadence and evidence to monitor.",
        )
    if new_status == "promoted_scoreable":
        return with_visible_fields(
            {
                "wow_id": child_id,
                "wow_type": "scoreable_signal",
                "scoreable": True,
                "accuracy_endpoint_eligible": True,
                "parent_wow_id": target_id,
                "root_wow_id": target_id,
                "claim": "The promoted idea will produce confirmable public evidence before 2026-09-30.",
                "invalidate_test": "No qualifying public evidence appears by resolve_by.",
                "resolve_by": "2026-09-30",
                "resolution_source": "public filings or earnings transcripts",
                "signal_status": "pending_scoreable",
                "source_refs": ["Reading Item 1"],
                "agent_facts": {"wow_type": "scoreable_signal", "scoreable": True, "accuracy_endpoint_eligible": True},
            },
            option_number=2,
            title="Promoted child scoreable signal for the existing idea",
            why="The child carries pending_scoreable while the status update uses promoted_scoreable.",
        )
    return None


def update_type_for_status(new_status: str, *, previous_status: str = "") -> str:
    if previous_status and new_status == previous_status:
        return "evidence"
    if new_status in {"promoted_trackable", "promoted_scoreable"}:
        return "promotion"
    if new_status in {"resolved_correct", "resolved_incorrect", "unresolved"}:
        return "resolution"
    if new_status == "killed":
        return "killed"
    if new_status == "stale":
        return "stale"
    if new_status == "voided":
        return "voided"
    if new_status == "invalid_test":
        return "invalid_test"
    if new_status in {"supported", "weakened", "retired"}:
        return "thesis_update"
    return "other"


def run_daily_wow_simulation(
    *,
    journal_path: Path | None = None,
    start_date: date = date(2026, 7, 6),
    investor_id: str = SIM_INVESTOR_ID,
    publish: bool = False,
    verify_public: bool = False,
    write_journal: bool = True,
    case_name: str | None = None,
) -> dict[str, Any]:
    journal = journal_path or default_journal_path()
    created_paths = ensure_private_journal(journal) if write_journal else []
    cases = build_simulation_cases(journal_path=journal, start_date=start_date, investor_id=investor_id)
    if case_name:
        filtered_cases = [case for case in cases if case.name == case_name]
        if not filtered_cases:
            available = ", ".join(case.name for case in cases)
            raise ValueError(f"unknown simulation case {case_name!r}; available cases: {available}")
        cases = filtered_cases
    run_id = uuid.uuid4()
    if publish:
        Investor.objects.update_or_create(
            investor_id=investor_id,
            defaults={
                "email_private": SIM_EMAIL,
                "display_name": SIM_DISPLAY_NAME,
                "status": Investor.Status.ACTIVE,
            },
        )

    for case in cases:
        case.validation_errors = validate_daily_state(case.state)
        if case.completed and not case.validation_errors:
            case.packet = packet_from_state(case.state)
            case.packet_markdown = packet_markdown(case.packet)
            case.parse_error = _parse_packet_error(case.packet_markdown, case.market_date)
            if publish and not case.parse_error:
                _publish_case(case, run_id=run_id)
        if write_journal:
            write_case_journal(case, journal)

    profile = judgment_profile(cases)
    findings = simulation_findings(cases)
    public_verification: dict[str, Any] = {}
    if verify_public:
        if publish:
            published_packet_ids = {case.published_packet_id for case in cases if case.published_packet_id is not None}
            public_verification = verify_published_simulation(
                investor_id=investor_id,
                packet_ids=published_packet_ids,
                expected_packet_count=len(published_packet_ids),
                require_full_transition_coverage=case_name is None,
            )
            if public_verification["errors"]:
                findings.append(
                    {
                        "severity": "P0",
                        "title": "Published public-page verification failed",
                        "status": "needs_fix",
                        "fix_plan": f"Fix {len(public_verification['errors'])} public verification error(s) before treating the WoW flow as production-ready.",
                    }
                )
        else:
            public_verification = {
                "investor_id": investor_id,
                "errors": ["--verify-public requires --publish"],
                "warnings": [],
            }
    report = {
        "run_id": str(run_id),
        "case_name": case_name or "",
        "journal_path": str(journal),
        "created_paths": [str(path) for path in created_paths],
        "case_count": len(cases),
        "completed_case_count": sum(1 for case in cases if case.completed),
        "published_case_count": sum(1 for case in cases if case.published_url),
        "lifecycle_transition_count": sum(1 for case in cases if case.name.startswith("lifecycle_")),
        "findings": findings,
        "public_verification": public_verification,
        "judgment_profile": profile,
        "cases": [case_summary(case) for case in cases],
    }
    if write_journal:
        write_crm_summary_files(cases, journal)
        write_training_profile(profile, journal)
        write_simulation_report(report, journal)
    return report


def build_simulation_cases(*, journal_path: Path, start_date: date, investor_id: str) -> list[SimulationCase]:
    cases: list[SimulationCase] = []
    day = start_date

    conversation_specs = [
        ("select_scoreable_with_reason", ["I pick 2 because the deadline and source make it easiest to judge later."]),
        ("select_missing_reason_then_train", ["1", "Because I want the agent to keep monitoring power and packaging as a recurring bottleneck."]),
        ("pass_complete", ["pass; closest: 2; reason: the claim is directionally right but I do not trust the source mix yet; missing: named company evidence."]),
        ("pass_missing_closest_then_fix", ["pass; reason: too early to publish; missing: a company disclosure, not just market chatter.", "closest: 3"]),
        ("natural_language_choice", ["The scoreable one, because I want calibration practice when the evidence is clear."]),
    ]
    for index, (name, replies) in enumerate(conversation_specs):
        market_date = day + timedelta(days=index)
        reading_log = reading_log_for_day(market_date, offset=index)
        state = initial_daily_state(
            investor_id=investor_id,
            market_date=market_date,
            journal_path=journal_path,
            reading_log=reading_log,
            wow_options=base_daily_options(market_date, investor_id=investor_id, reading_log=reading_log),
        )
        case = simulate_replies(name=name, market_date=market_date, state=state, replies=replies)
        cases.append(case)

    no_reply_date = day + timedelta(days=len(conversation_specs))
    no_reply_reading_log = reading_log_for_day(no_reply_date, offset=5)
    no_reply_state = initial_daily_state(
        investor_id=investor_id,
        market_date=no_reply_date,
        journal_path=journal_path,
        reading_log=no_reply_reading_log,
        wow_options=base_daily_options(no_reply_date, investor_id=investor_id, reading_log=no_reply_reading_log),
    )
    turns = [ConversationTurn("agent", render_daily_options_prompt(no_reply_state["wow_options"]), "awaiting_user_choice")]
    cases.append(SimulationCase("user_no_reply_private_only", no_reply_date, mark_no_reply(no_reply_state), turns))

    transition_index = 1
    lifecycle_start = no_reply_date + timedelta(days=1)
    for target_wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items():
        for previous_status, new_statuses in previous_map.items():
            for new_status in sorted(new_statuses):
                market_date = lifecycle_start + timedelta(days=transition_index - 1)
                reading_log = reading_log_for_day(market_date, offset=transition_index, count=1)
                options = lifecycle_transition_options(
                    market_date,
                    investor_id=investor_id,
                    transition_number=transition_index,
                    target_wow_type=target_wow_type,
                    previous_status=previous_status,
                    new_status=new_status,
                    reading_log=reading_log,
                )
                state = initial_daily_state(
                    investor_id=investor_id,
                    market_date=market_date,
                    journal_path=journal_path,
                    reading_log=reading_log,
                    wow_options=options,
                )
                name = f"lifecycle_{target_wow_type}_{previous_status}_to_{new_status}"
                cases.append(simulate_replies(name=name, market_date=market_date, state=state, replies=["1 because this is the cleanest lifecycle update today."]))
                transition_index += 1
    return cases


def simulate_replies(*, name: str, market_date: date, state: dict[str, Any], replies: list[str]) -> SimulationCase:
    turns = [ConversationTurn("agent", render_daily_options_prompt(state["wow_options"]), state["state"])]
    current = deepcopy(state)
    for reply in replies:
        turns.append(ConversationTurn("user", reply, current["state"]))
        current, prompt, normalized = normalize_user_reply(current, reply)
        turns.append(ConversationTurn("agent", prompt, current["state"], normalized))
    return SimulationCase(name, market_date, current, turns)


def write_case_journal(case: SimulationCase, journal_path: Path) -> Path:
    path = journal_path / "daily" / f"{case.market_date.isoformat()}-{case.name}.md"
    body = [
        f"# Daily WoW Simulation: {case.name}",
        "",
        "```yaml",
        yaml.safe_dump(
            {
                "daily_packet_record": {
                    "local_journal_entry_id": f"sim-{case.market_date.isoformat()}-{case.name}",
                    "prepared_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    "packet_spec_version": "v0.2",
                    "skill_version": "v0.2",
                    "private_status": "prepared_private",
                    "submission_status": "submitted" if case.published_url else "not_submitted",
                    "receipt_status": "no_receipt",
                    "public_status": "published_on_local_wkap" if case.published_url else "not_public",
                    "public_url": case.published_url or None,
                    "receipt_id": None,
                    "packet_id": case.packet["packet_id"] if case.packet else None,
                }
            },
            sort_keys=False,
        ).strip(),
        "```",
        "",
        "## Conversation",
        "",
    ]
    for turn in case.turns:
        body.append(f"- {turn.actor} [{turn.state}]: {turn.message}")
    body.extend(["", "## Daily WoW State", "", "```json", json.dumps(case.state, indent=2, sort_keys=True), "```"])
    if case.packet_markdown:
        body.extend(["", "## Packet", "", case.packet_markdown])
    if case.validation_errors or case.parse_error or case.ledger_errors:
        body.extend(["", "## Errors", ""])
        for error in [*case.validation_errors, case.parse_error, *case.ledger_errors]:
            if error:
                body.append(f"- {error}")
    path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
    return path


def write_training_profile(profile: dict[str, Any], journal_path: Path) -> Path:
    path = journal_path / "user-judgment-profile.md"
    body = [
        "# User Judgment Profile",
        "",
        "Private training record generated by the Daily WoW simulator. This is agent working memory, not a public packet.",
        "",
        "```json",
        json.dumps(profile, indent=2, sort_keys=True),
        "```",
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def write_crm_summary_files(cases: list[SimulationCase], journal_path: Path) -> None:
    published = [case for case in cases if case.published_url]
    _replace_generated_block(
        journal_path / "receipts.md",
        SIM_GENERATED_BLOCK_ID,
        [
            "## Daily WoW Simulation Receipts",
            "",
            *[
                f"- local simulation: receipt not sent; case={case.name}; public_url={case.published_url}"
                for case in published
            ],
        ],
    )
    _replace_generated_block(
        journal_path / "public-verification.md",
        SIM_GENERATED_BLOCK_ID,
        [
            "## Daily WoW Simulation Public Verification",
            "",
            *[
                f"- verified local page: {case.published_url}; case={case.name}; errors={case.ledger_errors}"
                for case in published
            ],
        ],
    )
    _replace_generated_block(
        journal_path / "active-trackables.md",
        SIM_GENERATED_BLOCK_ID,
        [
            "## Daily WoW Simulation Active Trackables",
            "",
            *_trackable_summary_lines(published),
        ],
    )
    _replace_generated_block(
        journal_path / "pending-scoreables.md",
        SIM_GENERATED_BLOCK_ID,
        [
            "## Daily WoW Simulation Pending Scoreables",
            "",
            *_scoreable_summary_lines(published),
        ],
    )
    _replace_generated_block(
        journal_path / "thesis-map.md",
        SIM_GENERATED_BLOCK_ID,
        [
            "## Daily WoW Simulation Thesis Map",
            "",
            *_thesis_summary_lines(published),
        ],
    )


def _replace_generated_block(path: Path, block_id: str, lines: list[str]) -> None:
    start = f"<!-- {block_id}:start -->"
    end = f"<!-- {block_id}:end -->"
    body = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    pattern = re.compile(rf"\n?{re.escape(start)}.*?{re.escape(end)}\n?", flags=re.DOTALL)
    block = "\n".join([start, *lines, end, ""])
    if pattern.search(body):
        body = pattern.sub("\n" + block, body).rstrip() + "\n"
    else:
        body = body.rstrip() + "\n\n" + block
    path.write_text(body, encoding="utf-8")


def _remove_generated_block(path: Path, block_id: str) -> bool:
    if not path.exists():
        return False
    start = f"<!-- {block_id}:start -->"
    end = f"<!-- {block_id}:end -->"
    body = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"\n?{re.escape(start)}.*?{re.escape(end)}\n?", flags=re.DOTALL)
    body, count = pattern.subn("\n", body)
    if not count:
        return False
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return True


def _ledger_artifact_root() -> Path:
    return Path(settings.WKAP_LEDGER_REPO_PATH) if settings.WKAP_LEDGER_REPO_PATH else settings.BASE_DIR / "ledger_artifacts"


def _safe_remove_path(path: Path, *, allowed_roots: list[Path]) -> Path | None:
    resolved = path.resolve()
    allowed = [root.resolve() for root in allowed_roots]
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise RuntimeError(f"Refusing to remove path outside allowed roots: {resolved}")
    if not resolved.exists():
        return None
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    return resolved


def _trackable_summary_lines(cases: list[SimulationCase]) -> list[str]:
    lines = []
    for case in cases:
        for option in case.state.get("wow_options", []):
            if option.get("wow_type") == "trackable_wow" and option.get("trackable_status") == "active_trackable":
                lines.append(f"- `{option['wow_id']}`: {option.get('claim', option.get('plain_english_title', 'trackable'))}. Public: {case.published_url}")
            if option.get("wow_type") == "status_update" and option.get("target_wow_type") == "trackable_wow":
                lines.append(
                    f"- `{option['target_wow_id']}`: status {option['previous_status']} to {option['new_status']}. Public: {case.published_url}"
                )
    return lines or ["- No active trackable updates generated by this simulation run."]


def _scoreable_summary_lines(cases: list[SimulationCase]) -> list[str]:
    lines = []
    for case in cases:
        for option in case.state.get("wow_options", []):
            if option.get("wow_type") == "scoreable_signal" and option.get("signal_status") == "pending_scoreable":
                lines.append(
                    f"- `{option['wow_id']}`: resolve_by={option.get('resolve_by')}; resolution_source={option.get('resolution_source')}; public={case.published_url}"
                )
            if option.get("wow_type") == "status_update" and option.get("target_wow_type") == "scoreable_signal":
                lines.append(
                    f"- `{option['target_wow_id']}`: status {option['previous_status']} to {option['new_status']}. Public: {case.published_url}"
                )
    return lines or ["- No pending scoreable updates generated by this simulation run."]


def _thesis_summary_lines(cases: list[SimulationCase]) -> list[str]:
    lines = []
    for case in cases:
        for option in case.state.get("wow_options", []):
            if option.get("wow_type") == "thesis_wow":
                lines.append(f"- `{option['wow_id']}`: {option.get('thesis_claim', '')}. Public: {case.published_url}")
            if option.get("wow_type") == "status_update" and option.get("target_wow_type") == "thesis_wow":
                lines.append(
                    f"- `{option['target_wow_id']}`: thesis status {option['previous_status']} to {option['new_status']}. Public: {case.published_url}"
                )
    return lines or ["- No thesis updates generated by this simulation run."]


def write_simulation_report(report: dict[str, Any], journal_path: Path) -> Path:
    path = journal_path / "simulation" / "daily-wow-pressure-test-report.md"
    lines = [
        "# Daily WoW Conversation Pressure Test",
        "",
        f"Run ID: `{report['run_id']}`",
        f"Cases: {report['case_count']}",
        f"Completed packets: {report['completed_case_count']}",
        f"Published packets: {report['published_case_count']}",
        f"Lifecycle transitions covered: {report['lifecycle_transition_count']}",
        "",
        "## Findings",
        "",
    ]
    for finding in report["findings"]:
        lines.append(f"- {finding['severity']} {finding['title']}: {finding['status']}. {finding['fix_plan']}")
    public_verification = report.get("public_verification") or {}
    if public_verification:
        lines.extend(
            [
                "",
                "## Public Verification",
                "",
                f"- Pages checked: {public_verification.get('pages_checked', 0)}",
                f"- Status update pages: {public_verification.get('status_update_pages', 0)}",
                f"- Status update events: {public_verification.get('status_update_events', 0)}",
                f"- Errors: {len(public_verification.get('errors', []))}",
            ]
        )
        for error in public_verification.get("errors", []):
            lines.append(f"  - {error}")
    lines.extend(["", "## Cases", ""])
    for case in report["cases"]:
        status = "ok" if not case["errors"] else "needs_fix"
        lines.append(f"- {case['name']}: {status}; state={case['state']}; published={case['published_url'] or 'no'}")
        for error in case["errors"]:
            lines.append(f"  - {error}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def judgment_profile(cases: list[SimulationCase]) -> dict[str, Any]:
    selected_types: dict[str, int] = {}
    pass_reasons: list[str] = []
    missing_evidence: list[str] = []
    selected_reasons: list[str] = []
    for case in cases:
        selection = case.state.get("selection", {})
        selected = selection.get("selected_wow_id", "")
        if selected == "none":
            if selection.get("reason_for_pass"):
                pass_reasons.append(selection["reason_for_pass"])
            if selection.get("missing_evidence"):
                missing_evidence.append(selection["missing_evidence"])
            continue
        selected_option = next((option for option in case.state.get("wow_options", []) if option.get("wow_id") == selected), None)
        if selected_option:
            selected_types[selected_option["wow_type"]] = selected_types.get(selected_option["wow_type"], 0) + 1
        if selection.get("reason_for_selection"):
            selected_reasons.append(selection["reason_for_selection"])
    return {
        "selected_type_counts": selected_types,
        "selection_reasons": selected_reasons,
        "pass_reasons": pass_reasons,
        "missing_evidence_requests": missing_evidence,
        "agent_training_notes": [
            "Prefer scoreable options when the user explicitly values calibration practice and clean evidence.",
            "Keep pass days public-ready only after closest_rejected_wow, reason_for_pass, and missing_evidence are all present.",
            "Do not substitute agent confidence for user judgment; ask for the missing field only.",
        ],
    }


def simulation_findings(cases: list[SimulationCase]) -> list[dict[str, str]]:
    findings = [
        {
            "severity": "P1",
            "title": "Synthetic reading fixtures made the user judgment flow hard to evaluate",
            "status": "fixed_by_real_source_basket",
            "fix_plan": "Daily readings now use public source samples from CoreWeave, TSMC, Circle, CME, Tesla, Amazon, and Constellation, and options resolve their source_refs against the day's reading log.",
        },
        {
            "severity": "P1",
            "title": "Old local simulation data could pollute reruns",
            "status": "fixed_by_reset_command",
            "fix_plan": "The simulator command now supports --reset and --reset-only to remove w0998 packets, raw emails, simulator ledger events, generated journal files, public pages, manifests, and raw email artifacts before rerunning.",
        },
        {
            "severity": "P1",
            "title": "No dedicated Daily WoW conversation simulator existed",
            "status": "fixed_by_simulator",
            "fix_plan": "The simulator now normalizes user replies into Daily WoW State, writes private journal records, and can publish local packets.",
        },
        {
            "severity": "P1",
            "title": "Daily WoW State needed pre-submission validation",
            "status": "fixed_by_validator",
            "fix_plan": "The simulator validates the exact 3-option display contract, selection/pass rules, and CRM transition rules before packet generation.",
        },
        {
            "severity": "P2",
            "title": "User-level bundled packet template is stale at v0.1",
            "status": "fixed_installed_template",
            "fix_plan": "The installed local skill template was updated to v0.2 and the missing v0.2 reference snapshot was added.",
        },
    ]
    broken = [case for case in cases if case.validation_errors or case.parse_error or case.ledger_errors]
    if broken:
        findings.append(
            {
                "severity": "P0",
                "title": "One or more simulated cases failed validation",
                "status": "needs_fix",
                "fix_plan": f"Fix {len(broken)} case(s) listed in the report before treating the flow as production-ready.",
            }
        )
    return findings


def case_summary(case: SimulationCase) -> dict[str, Any]:
    return {
        "name": case.name,
        "market_date": case.market_date.isoformat(),
        "state": case.state.get("state"),
        "selected_wow_id": case.state.get("selection", {}).get("selected_wow_id", ""),
        "published_url": case.published_url,
        "errors": [error for error in [*case.validation_errors, case.parse_error, *case.ledger_errors] if error],
    }


def wow_id(market_date: date, number: int) -> str:
    return f"WOW-{market_date.isoformat()}-{number:03d}"


def _validate_option(index: int, option: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field_name in ("wow_id", "wow_type", "visible_type_label", "plain_english_title", "why_worth_watching"):
        if not _has_value(option.get(field_name)):
            errors.append(f"wow_option {index} missing {field_name}")
    wow_type = option.get("wow_type")
    expected_label = VISIBLE_TYPE_LABELS.get(str(wow_type))
    if expected_label and option.get("visible_type_label") != expected_label:
        errors.append(f"wow_option {index} visible_type_label must be {expected_label}")
    if wow_type == "scoreable_signal":
        for field_name in ("invalidate_test", "resolve_by", "resolution_source"):
            if not _has_value(option.get(field_name)):
                errors.append(f"scoreable option {index} missing visible {field_name}")
    if wow_type == "status_update":
        for field_name in ("target_summary", "previous_status", "new_status", "evidence_summary"):
            if not _has_value(option.get(field_name)):
                errors.append(f"status_update option {index} missing visible {field_name}")
        for field_name in STATUS_UPDATE_REQUIRED_FIELDS:
            if not _has_value(option.get(field_name)):
                errors.append(f"status_update option {index} missing {field_name}")
        transition_error = validate_status_transition(
            target_wow_type=str(option.get("target_wow_type") or ""),
            previous_status=str(option.get("previous_status") or ""),
            new_status=str(option.get("new_status") or ""),
            update_type=str(option.get("update_type") or ""),
        )
        if transition_error:
            errors.append(f"status_update option {index} invalid transition: {transition_error}")
    elif wow_type in NORMAL_WOW_REQUIRED_FIELDS:
        for field_name in NORMAL_WOW_REQUIRED_FIELDS[wow_type]:
            if field_name == "parent_wow_id" and field_name in option:
                continue
            if not _has_value(option.get(field_name)):
                errors.append(f"{wow_type} option {index} missing {field_name}")
    else:
        errors.append(f"wow_option {index} invalid wow_type: {wow_type}")
    return errors


def _validate_completed_selection(state: dict[str, Any], option_ids: set[str]) -> list[str]:
    errors: list[str] = []
    selection = state["selection"]
    selected = selection.get("selected_wow_id", "")
    if selected == "none":
        for field_name in ("reason_for_pass", "closest_rejected_wow", "missing_evidence"):
            if not selection.get(field_name):
                errors.append(f"pass selection missing {field_name}")
        if selection.get("closest_rejected_wow") and selection["closest_rejected_wow"] not in option_ids:
            errors.append("closest_rejected_wow must be one of today's 3 wow_options")
        if selection.get("reason_for_selection"):
            errors.append("reason_for_selection must be blank on pass")
    elif selected:
        if not selection.get("reason_for_selection"):
            errors.append("selected WoW missing reason_for_selection")
        for field_name in ("reason_for_pass", "closest_rejected_wow", "missing_evidence"):
            if selection.get(field_name):
                errors.append(f"{field_name} must be blank when a WoW is selected")
    else:
        errors.append("completed daily state requires selected_wow_id or none")
    return errors


def _packet_item(option: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(option)
    for field_name in ("option_number", "visible_type_label", "plain_english_title", "target_summary"):
        item.pop(field_name, None)
    return item


def _wow_type_counts(options: list[dict[str, Any]]) -> dict[str, int]:
    values = [str(option.get("wow_type") or "") for option in options]
    return {
        "wow_count": len(values),
        "scoreable_count": values.count("scoreable_signal"),
        "trackable_count": values.count("trackable_wow"),
        "thesis_count": values.count("thesis_wow"),
        "candidate_count": values.count("candidate_wow"),
        "status_update_count": values.count("status_update"),
    }


def _packet_title(state: dict[str, Any]) -> str:
    selected = state["selection"].get("selected_wow_id")
    option = next((item for item in state["wow_options"] if item.get("wow_id") == selected), None)
    if option:
        return option["plain_english_title"]
    return "Daily WoW pass"


def _choice_from_reply(user_reply: str, options: list[dict[str, Any]]) -> int | str | None:
    text = user_reply.strip().lower()
    if not text:
        return None
    if re.search(r"\bpass\b", text):
        return "pass"
    match = re.search(r"\b([123])\b", text)
    if match:
        return int(match.group(1))
    for option in options:
        label = str(option.get("visible_type_label") or "").lower()
        if label and label in text:
            matches = [item for item in options if str(item.get("visible_type_label") or "").lower() == label]
            if len(matches) == 1:
                return int(matches[0]["option_number"])
    word_map = {"first": 1, "second": 2, "third": 3}
    for word, number in word_map.items():
        if re.search(rf"\b{word}\b", text):
            return number
    return None


def _reason_from_reply(user_reply: str) -> str:
    text = user_reply.strip()
    for pattern in (r"\bbecause\b\s*(.+)$", r"\breason\s*[:=-]\s*(.+)$", r"\bsince\b\s*(.+)$"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")
    return ""


def _merge_pass_fields(state: dict[str, Any], user_reply: str) -> None:
    selection = state["selection"]
    closest = _closest_from_reply(user_reply, state["wow_options"])
    if closest:
        selection["closest_rejected_wow"] = closest
    reason = _field_from_reply(user_reply, "reason") or _field_from_reply(user_reply, "reason_for_pass") or _field_from_reply(user_reply, "why_pass")
    if not reason and "because" in user_reply.lower():
        reason = _reason_from_reply(user_reply)
    if reason:
        selection["reason_for_pass"] = reason
    missing = _field_from_reply(user_reply, "missing") or _field_from_reply(user_reply, "missing_evidence")
    if missing:
        selection["missing_evidence"] = missing


def _closest_from_reply(user_reply: str, options: list[dict[str, Any]]) -> str:
    text = user_reply.strip()
    match = re.search(r"\bclosest(?:_rejected_wow)?\s*[:=-]\s*([^\n;,.]+)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    value = match.group(1).strip()
    if re.fullmatch(r"[123]", value):
        return options[int(value) - 1]["wow_id"]
    ids = {option["wow_id"] for option in options}
    return value if value in ids else value


def _field_from_reply(user_reply: str, field_name: str) -> str:
    match = re.search(rf"\b{re.escape(field_name)}\s*[:=-]\s*([^;\n]+)", user_reply, flags=re.IGNORECASE)
    return match.group(1).strip(" .") if match else ""


def _missing_pass_fields(state: dict[str, Any]) -> list[str]:
    missing = []
    selection = state["selection"]
    option_ids = {option["wow_id"] for option in state["wow_options"]}
    if not selection.get("closest_rejected_wow"):
        missing.append("closest_rejected_wow")
    elif selection["closest_rejected_wow"] not in option_ids:
        missing.append("closest_rejected_wow")
    if not selection.get("reason_for_pass"):
        missing.append("reason_for_pass")
    if not selection.get("missing_evidence"):
        missing.append("missing_evidence")
    return missing


def _pass_prompt(missing: list[str]) -> str:
    prompts = {
        "closest_rejected_wow": "Which of today's 3 WoWs came closest?",
        "reason_for_pass": "Why pass today?",
        "missing_evidence": "What evidence is missing?",
    }
    if len(missing) == 1:
        return prompts[missing[0]]
    return " ".join(prompts[field_name] for field_name in missing)


def _has_value(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    if value is None:
        return False
    return bool(str(value).strip())


def _parse_packet_error(markdown: str, market_date: date) -> str:
    raw = RawEmail(
        gmail_message_id=f"sim-parse-{market_date.isoformat()}",
        sender_email=SIM_EMAIL,
        subject=f"Daily WoW Packet - {market_date.isoformat()} - {SIM_DISPLAY_NAME}",
        raw_body=markdown,
        received_at=timezone.make_aware(datetime.combine(market_date, time(21, 0))),
    )
    try:
        parse_wow(raw)
    except ParseError as exc:
        return str(exc)
    return ""


def _publish_case(case: SimulationCase, *, run_id: uuid.UUID) -> None:
    raw, _ = RawEmail.objects.update_or_create(
        gmail_message_id=f"local-daily-wow-sim-{case.market_date.isoformat()}-{case.name}",
        defaults={
            "sender_email": SIM_EMAIL,
            "subject": f"Daily WoW Packet - {case.market_date.isoformat()} - {SIM_DISPLAY_NAME}",
            "raw_body": case.packet_markdown,
            "received_at": timezone.make_aware(datetime.combine(case.market_date, time(21, 0))),
            "classification": RawEmail.Classification.WOW,
            "processing_status": RawEmail.ProcessingStatus.SAVED,
            "error_message": "",
        },
    )
    packet = create_wow_submission(raw, run_id=run_id)
    publish_artifact("wow", packet.id, run_id=run_id)
    packet.refresh_from_db()
    case.published_url = packet.canonical_url
    case.published_packet_id = packet.id
    case.ledger_errors = validate_ledger("wow", packet.id)
    case.state["public_url"] = packet.canonical_url
    case.state["receipt_status"] = "skipped_local" if not packet.receipt_email_message_id else "sent"
    case.state["state"] = "verified" if not case.ledger_errors else "submitted"
