from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

from ingestion.models import RawEmail
from ingestion.services import classify_email
from ledger.models import DailyWoWPacket, RadarIssue
from ledger.services import create_radar_issue, create_wow_submission
from publishing.services import publish_artifact, rebuild_indexes, validate_all, validate_ledger
from publishing.urls import radar_issue_path, wow_path


REGRESSION_DATE = "2026-07-03"


def run_local_regression(*, run_id) -> dict[str, Any]:
    errors: list[str] = []
    radar_raw = _upsert_raw_email(
        gmail_message_id=f"regression-radar-{REGRESSION_DATE}",
        sender_email="playinc@gmail.com",
        subject=f"WKAP Radar Feed - {REGRESSION_DATE} - Regression",
        raw_body="\n".join(
            [
                "Market_date: 2026-07-03",
                "Title: Regression Radar Feed",
                "Body: Local regression verifies Radar email classification, parsing, HTML generation, manifest creation, ledger commit metadata, and proof status.",
            ]
        ),
    )
    radar_classification = classify_email(radar_raw, run_id=run_id)
    if radar_classification != RawEmail.Classification.RADAR:
        errors.append(f"Radar classification failed: {radar_classification}")
    radar = publish_artifact("radar", create_radar_issue(radar_raw, run_id=run_id).id, run_id=run_id)
    errors.extend(f"radar: {error}" for error in validate_ledger("radar", radar.id))
    _expect_public_file(radar_issue_path(radar.market_date), errors)

    wow_raw = _upsert_raw_email(
        gmail_message_id=f"regression-wow-{REGRESSION_DATE}",
        sender_email="regression-investor@example.com",
        subject=f"Daily WoW Packet - {REGRESSION_DATE} - Regression Agent",
        raw_body=_wow_packet_body(),
    )
    wow_classification = classify_email(wow_raw, run_id=run_id)
    if wow_classification != RawEmail.Classification.WOW:
        errors.append(f"WoW classification failed: {wow_classification}")
    wow = publish_artifact("wow", create_wow_submission(wow_raw, run_id=run_id).id, run_id=run_id)
    errors.extend(f"wow: {error}" for error in validate_ledger("wow", wow.id))
    wow_html = _expect_public_file(wow_path(wow.investor.investor_id, wow.market_date), errors)
    if wow_html:
        _expect_html_tokens(
            wow_html,
            errors,
            [
                'data-selection-status="selected"',
                'data-field="selection_status"',
                'data-field="source_url"',
                'data-field="evidence_to_watch"',
                "Regression Agent",
            ],
        )
    if not str(wow.raw_email_github_url).startswith(("http://", "https://")) and not Path(wow.raw_email_github_url).exists():
        errors.append("wow raw email artifact is missing")

    rebuild_indexes(run_id=run_id)
    errors.extend(validate_all())
    return {
        "radar_id": radar.id,
        "wow_id": wow.id,
        "investor_id": wow.investor.investor_id,
        "market_date": str(wow.market_date),
        "radar_url": radar.canonical_url,
        "wow_url": wow.canonical_url,
        "errors": errors,
    }


def _upsert_raw_email(*, gmail_message_id: str, sender_email: str, subject: str, raw_body: str) -> RawEmail:
    raw_email, _ = RawEmail.objects.update_or_create(
        gmail_message_id=gmail_message_id,
        defaults={
            "sender_email": sender_email,
            "subject": subject,
            "raw_body": raw_body.strip() + "\n",
            "received_at": datetime.fromisoformat(f"{REGRESSION_DATE}T20:00:00+00:00").astimezone(timezone.utc),
            "classification": RawEmail.Classification.UNCLASSIFIED,
            "processing_status": RawEmail.ProcessingStatus.SAVED,
            "error_message": "",
        },
    )
    return raw_email


def _expect_public_file(relative_path: str, errors: list[str]) -> str:
    path = settings.WKAP_PUBLIC_SITE_ROOT / relative_path
    if not path.exists():
        errors.append(f"public file missing: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def _expect_html_tokens(html: str, errors: list[str], tokens: list[str]) -> None:
    for token in tokens:
        if token not in html:
            errors.append(f"HTML token missing: {token}")


def _wow_packet_body() -> str:
    return "\n".join(
        [
            "# Daily WoW Packet",
            "",
            "## 1. Reading Log",
            "",
            "### Reading Item 1",
            "source_title: Regression AI infra supply chain note",
            "source_url: https://example.com/regression-ai-infra",
            "source_type: article",
            "published_time: 2026-07-03T13:00:00Z",
            "tickers / themes: AI infrastructure, power bottlenecks",
            "reading_origin: agent_suggested",
            "agent_summary: Regression item checks that source fields become durable crawlable HTML facts.",
            "",
            "---",
            "",
            "## 2. Agent Suggested 3 WoWs",
            "",
            "### Suggested WoW 1",
            "wow_id: WOW-2026-07-03-001",
            "source_refs: Reading Item 1",
            "ticker / theme: AI infrastructure power bottlenecks",
            "what's_worth_watching: Power availability may become the gating factor for AI infrastructure growth.",
            "why_now: Data center demand is colliding with grid interconnection timelines.",
            "what_evidence_should_AI_watch_for: Watch utility interconnection filings, signed power agreements, transformer lead times, and management commentary on constrained deployments.",
            "",
            "### Suggested WoW 2",
            "wow_id: WOW-2026-07-03-002",
            "source_refs: Reading Item 1",
            "ticker / theme: Grid equipment backlog",
            "what's_worth_watching: Grid equipment backlogs may validate infrastructure bottleneck spending.",
            "why_now: AI campus announcements require real electrical equipment before revenue can scale.",
            "what_evidence_should_AI_watch_for: Track book-to-bill, backlog quality, delivery lead times, and utility procurement commentary.",
            "",
            "### Suggested WoW 3",
            "wow_id: WOW-2026-07-03-003",
            "source_refs: Reading Item 1",
            "ticker / theme: AI capex digestion",
            "what's_worth_watching: AI capex may shift from GPU scarcity to site readiness scarcity.",
            "why_now: Investors are looking for the next constraint after accelerator supply.",
            "what_evidence_should_AI_watch_for: Watch capex timing changes, deployment delays, and cloud provider commentary on power and real estate.",
            "",
            "## 3. User Selection / Pass",
            "",
            "selected_wow_id: WOW-2026-07-03-001",
            "user_note: Select the power bottleneck angle because it is concrete, monitorable, and cross-checkable across utilities and data center operators.",
        ]
    )
