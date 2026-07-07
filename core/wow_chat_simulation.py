from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

from ingestion.models import RawEmail
from ledger.models import Investor
from ledger.services import create_wow_submission
from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS
from publishing.services import publish_artifact, validate_ledger

from core.wow_daily_simulation import (
    SIM_DISPLAY_NAME,
    SIM_EMAIL,
    SIM_INVESTOR_ID,
    ConversationTurn,
    SimulationCase,
    base_daily_options,
    default_journal_path,
    ensure_private_journal,
    initial_daily_state,
    lifecycle_transition_options,
    normalize_user_reply,
    packet_from_state,
    packet_markdown,
    reading_log_for_day,
    render_daily_options_prompt,
    validate_daily_state,
    write_case_journal,
)


CHAT_MARKET_DATE = date(2026, 7, 6)
CHAT_CASE_NAME = "agent_chat_browser_simulation"
CHAT_SESSIONS: dict[str, dict[str, Any]] = {}
CHAT_LOCK = threading.Lock()


@dataclass(frozen=True)
class ChatCaseSpec:
    name: str
    market_date: date
    state: dict[str, Any]
    replies: list[str]


def monthly_chat_case_specs(
    *,
    start_date: date = CHAT_MARKET_DATE,
    investor_id: str = SIM_INVESTOR_ID,
) -> list[ChatCaseSpec]:
    journal_path = default_journal_path()
    specs: list[ChatCaseSpec] = []
    normal_cases = [
        (
            "day_01_select_missing_reason_then_train",
            [
                "1",
                "Because the AI infrastructure bottleneck gives the agent a recurring evidence stream across contracts, packaging, and power.",
            ],
        ),
        (
            "day_02_pass_complete",
            [
                "pass; closest: 2; reason: Circle is interesting but I want a fresher company disclosure before publishing a public judgment; missing: updated issuer metrics or transcript detail."
            ],
        ),
        (
            "day_03_natural_language_scoreable_choice",
            [
                "The scoreable one, because Circle reserve income has a public quarterly source and a clean invalidate test."
            ],
        ),
    ]
    for index, (name, replies) in enumerate(normal_cases):
        market_date = start_date + timedelta(days=index)
        reading_log = reading_log_for_day(market_date, offset=index)
        state = initial_daily_state(
            investor_id=investor_id,
            market_date=market_date,
            journal_path=journal_path,
            reading_log=reading_log,
            wow_options=base_daily_options(market_date, investor_id=investor_id, reading_log=reading_log),
        )
        specs.append(ChatCaseSpec(name=name, market_date=market_date, state=state, replies=replies))

    transition_index = 1
    lifecycle_start = start_date + timedelta(days=len(normal_cases))
    for target_wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items():
        for previous_status, new_statuses in previous_map.items():
            for new_status in sorted(new_statuses):
                market_date = lifecycle_start + timedelta(days=transition_index - 1)
                reading_log = reading_log_for_day(market_date, offset=transition_index, count=1)
                state = initial_daily_state(
                    investor_id=investor_id,
                    market_date=market_date,
                    journal_path=journal_path,
                    reading_log=reading_log,
                    wow_options=lifecycle_transition_options(
                        market_date,
                        investor_id=investor_id,
                        transition_number=transition_index,
                        target_wow_type=target_wow_type,
                        previous_status=previous_status,
                        new_status=new_status,
                        reading_log=reading_log,
                    ),
                )
                name = f"day_{len(specs) + 1:02d}_status_{target_wow_type}_{previous_status}_to_{new_status}"
                reason = (
                    f"1 because the {target_wow_type} state change from {previous_status} to {new_status} "
                    "is the cleanest public CRM maintenance action for today's evidence."
                )
                specs.append(ChatCaseSpec(name=name, market_date=market_date, state=state, replies=[reason]))
                transition_index += 1
    return specs[:30]


def monthly_chat_case_by_name(
    case_name: str,
    *,
    start_date: date = CHAT_MARKET_DATE,
    investor_id: str = SIM_INVESTOR_ID,
) -> ChatCaseSpec:
    for spec in monthly_chat_case_specs(start_date=start_date, investor_id=investor_id):
        if spec.name == case_name:
            return spec
    available = ", ".join(spec.name for spec in monthly_chat_case_specs(start_date=start_date, investor_id=investor_id))
    raise ValueError(f"unknown monthly chat case {case_name!r}; available cases: {available}")


def monthly_chat_case_index(
    *,
    start_date: date = CHAT_MARKET_DATE,
    investor_id: str = SIM_INVESTOR_ID,
) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "market_date": spec.market_date.isoformat(),
            "replies": list(spec.replies),
            "option_types": [option.get("wow_type", "") for option in spec.state.get("wow_options", [])],
            "option_titles": [option.get("plain_english_title", "") for option in spec.state.get("wow_options", [])],
        }
        for spec in monthly_chat_case_specs(start_date=start_date, investor_id=investor_id)
    ]


def start_chat_session(
    *,
    investor_id: str = SIM_INVESTOR_ID,
    market_date: date = CHAT_MARKET_DATE,
    case_name: str | None = None,
    start_date: date = CHAT_MARKET_DATE,
) -> dict[str, Any]:
    started_at = datetime.utcnow()
    if case_name:
        spec = monthly_chat_case_by_name(case_name, start_date=start_date, investor_id=investor_id)
        state = deepcopy(spec.state)
        market_date = spec.market_date
    else:
        reading_log = reading_log_for_day(market_date)
        state = initial_daily_state(
            investor_id=investor_id,
            market_date=market_date,
            journal_path=default_journal_path(),
            reading_log=reading_log,
            wow_options=base_daily_options(market_date, investor_id=investor_id, reading_log=reading_log),
        )
        case_name = CHAT_CASE_NAME
    elapsed_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "case_name": case_name,
        "market_date": market_date.isoformat(),
        "investor_id": investor_id,
        "state": state,
        "messages": [
            {
                "actor": "agent",
                "message": render_daily_options_prompt(state["wow_options"]),
                "state": state["state"],
                "elapsed_ms": elapsed_ms,
            }
        ],
        "submission_status": "not_started",
        "public_url": "",
        "errors": [],
        "created_at": started_at.isoformat() + "Z",
    }
    with CHAT_LOCK:
        CHAT_SESSIONS[session_id] = session
    return chat_session_snapshot(session_id)


def handle_chat_message(*, session_id: str, message: str) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")
    with CHAT_LOCK:
        session = CHAT_SESSIONS.get(session_id)
        if not session:
            raise ValueError("unknown chat simulation session")
        current_state = deepcopy(session["state"])
        session["messages"].append({"actor": "user", "message": text, "state": current_state["state"]})

    next_state, prompt, normalized = normalize_user_reply(current_state, text)
    with CHAT_LOCK:
        session = CHAT_SESSIONS[session_id]
        session["state"] = next_state
        session["messages"].append(
            {
                "actor": "agent",
                "message": prompt,
                "state": next_state["state"],
                "normalized": normalized,
            }
        )
        should_submit = next_state["state"] == "submission_in_progress" and session["submission_status"] == "not_started"
        if should_submit:
            session["submission_status"] = "queued"

    if should_submit:
        threading.Thread(target=_submit_session_in_background, args=(session_id,), daemon=True).start()
    return chat_session_snapshot(session_id)


def chat_session_snapshot(session_id: str) -> dict[str, Any]:
    with CHAT_LOCK:
        session = CHAT_SESSIONS.get(session_id)
        if not session:
            raise ValueError("unknown chat simulation session")
        return {
            "session_id": session["session_id"],
            "case_name": session["case_name"],
            "market_date": session["market_date"],
            "investor_id": session["investor_id"],
            "state": session["state"]["state"],
            "messages": deepcopy(session["messages"]),
            "submission_status": session["submission_status"],
            "public_url": session["public_url"],
            "errors": list(session["errors"]),
            "option_types": [option.get("wow_type", "") for option in session["state"].get("wow_options", [])],
            "selected_wow_id": session["state"].get("selection", {}).get("selected_wow_id", ""),
        }


def _submit_session_in_background(session_id: str) -> None:
    run_id = uuid.uuid4()
    try:
        close_old_connections()
        with CHAT_LOCK:
            session = CHAT_SESSIONS[session_id]
            session["submission_status"] = "running"
            state = deepcopy(session["state"])
            messages = deepcopy(session["messages"])

        errors = validate_daily_state(state)
        if errors:
            _mark_failed(session_id, errors)
            return

        Investor.objects.update_or_create(
            investor_id=state["investor_id"],
            defaults={
                "email_private": SIM_EMAIL,
                "display_name": SIM_DISPLAY_NAME,
                "status": Investor.Status.ACTIVE,
            },
        )
        packet = packet_from_state(state)
        markdown = packet_markdown(packet)
        market_date = date.fromisoformat(state["market_date"])
        raw, _ = RawEmail.objects.update_or_create(
            gmail_message_id=f"local-daily-wow-chat-sim-{session_id}",
            defaults={
                "sender_email": SIM_EMAIL,
                "subject": f"Daily WoW Packet - {market_date.isoformat()} - {SIM_DISPLAY_NAME}",
                "raw_body": markdown,
                "received_at": timezone.make_aware(datetime.combine(market_date, time(21, 0))),
                "classification": RawEmail.Classification.WOW,
                "processing_status": RawEmail.ProcessingStatus.SAVED,
                "error_message": "",
            },
        )
        published_packet = create_wow_submission(raw, run_id=run_id)
        publish_artifact("wow", published_packet.id, run_id=run_id)
        published_packet.refresh_from_db()
        ledger_errors = validate_ledger("wow", published_packet.id)

        journal_path = default_journal_path()
        ensure_private_journal(journal_path)
        turns = [
            ConversationTurn(
                actor=item["actor"],
                message=item["message"],
                state=item.get("state", ""),
                normalized=item.get("normalized", {}),
            )
            for item in messages
        ]
        case = SimulationCase(
            session.get("case_name") or CHAT_CASE_NAME,
            market_date,
            state,
            turns,
            packet=packet,
            packet_markdown=markdown,
            published_url=published_packet.canonical_url,
            published_packet_id=published_packet.id,
            ledger_errors=ledger_errors,
        )
        write_case_journal(case, journal_path)

        with CHAT_LOCK:
            session = CHAT_SESSIONS[session_id]
            session["public_url"] = published_packet.canonical_url
            session["errors"] = ledger_errors
            session["state"]["public_url"] = published_packet.canonical_url
            session["state"]["receipt_status"] = "skipped_local" if not published_packet.receipt_email_message_id else "sent"
            session["state"]["state"] = "verified" if not ledger_errors else "submitted"
            session["submission_status"] = "verified" if not ledger_errors else "submitted_with_errors"
            status_message = (
                f"Background submit verified: {published_packet.canonical_url}"
                if not ledger_errors
                else f"Background submit completed with ledger errors: {'; '.join(ledger_errors)}"
            )
            session["messages"].append({"actor": "agent", "message": status_message, "state": session["state"]["state"]})
    except Exception as exc:  # pragma: no cover - surfaced in the chat harness for local debugging.
        _mark_failed(session_id, [str(exc)])
    finally:
        close_old_connections()


def _mark_failed(session_id: str, errors: list[str]) -> None:
    with CHAT_LOCK:
        session = CHAT_SESSIONS.get(session_id)
        if not session:
            return
        session["submission_status"] = "failed"
        session["errors"] = errors
        session["state"]["state"] = "not_submitted_format_error"
        session["messages"].append(
            {
                "actor": "agent",
                "message": "Background submit failed: " + "; ".join(errors),
                "state": session["state"]["state"],
            }
        )
