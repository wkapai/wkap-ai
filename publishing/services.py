from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import Max
from django.template.loader import render_to_string

from core.events import log_event
from ingestion.models import RawEmail
from ledger.models import LedgerEvent, RadarIssue, DailyWoWPacket
from publishing.receipts import send_radar_receipt, send_wow_receipt
from publishing.urls import (
    investor_home_path,
    investor_wows_path,
    manifest_path,
    radar_issue_path,
    radar_issue_url,
    wow_path,
    wow_url,
)


WOW_DISCLAIMER = (
    "This is a ledgered Daily WoW Packet: reading log, agent-suggested WoWs, and investor selection/pass details. "
    "It is not WKAP editorial endorsement or investment advice."
)


def generate_radar_html(issue: RadarIssue, *, run_id: uuid.UUID) -> RadarIssue:
    issue.canonical_url = radar_issue_url(issue.market_date)
    issue.content_sha256 = _radar_content_hash(issue)
    issue.save(update_fields=["canonical_url", "content_sha256", "updated_at"])
    html = _render_radar(issue)
    _write_public(radar_issue_path(issue.market_date), html)
    issue.body_html = html
    issue.save(update_fields=["body_html", "updated_at"])
    log_event("html_generated", run_id=run_id, entity_type="radar", entity_id=issue.id, raw_email=issue.source_email, artifact=issue)
    return issue


def generate_wow_html(submission: DailyWoWPacket, *, run_id: uuid.UUID) -> DailyWoWPacket:
    submission.canonical_url = wow_url(submission.investor.investor_id, submission.market_date)
    submission.raw_email_sha256 = _sha256(submission.source_email.raw_body)
    submission.content_sha256 = _wow_content_hash(submission)
    submission.save(update_fields=["canonical_url", "raw_email_sha256", "content_sha256", "updated_at"])
    html = _render_wow(submission)
    _write_public(wow_path(submission.investor.investor_id, submission.market_date), html)
    log_event(
        "html_generated",
        run_id=run_id,
        entity_type="wow",
        entity_id=submission.id,
        raw_email=submission.source_email,
        investor=submission.investor,
        artifact=submission,
    )
    rebuild_indexes(run_id=run_id)
    return submission


def rebuild_indexes(*, run_id: uuid.UUID) -> None:
    radar_issues = RadarIssue.objects.order_by("-market_date")
    _write_public("radar/index.html", render_to_string("publishing/radar/archive.html", {"issues": radar_issues}))
    investors = _investors_with_wows()
    _write_public(
        "investors/index.html",
        render_to_string(
            "publishing/investors/archive.html",
            {
                "investors": investors,
                "submissions": DailyWoWPacket.objects.select_related("investor").order_by("-created_at", "-id"),
            },
        ),
    )

    for investor in investors:
        submissions = investor.wows.order_by("-created_at", "-id")
        _write_public(
            investor_home_path(investor.investor_id),
            render_to_string("publishing/investors/home.html", {"investor": investor, "submissions": submissions}),
        )
        _write_public(
            investor_wows_path(investor.investor_id),
            render_to_string("publishing/investors/wows.html", {"investor": investor, "submissions": submissions}),
        )
    log_event("index_rebuilt", run_id=run_id, status=LedgerEvent.Status.SUCCEEDED)


def generate_manifest(entity_type: str, entity_id: int, *, run_id: uuid.UUID) -> dict[str, Any]:
    artifact = _artifact(entity_type, entity_id)
    path = _manifest_storage_path(entity_type, entity_id)
    artifact.manifest_url = _github_url(path) or str(path)
    artifact.save(update_fields=["manifest_url", "updated_at"])
    payload = _manifest_payload(entity_type, artifact)
    _write_manifest(entity_type, entity_id, payload)
    log_event(
        "manifest_created",
        run_id=run_id,
        entity_type=entity_type,
        entity_id=artifact.id,
        raw_email=artifact.source_email,
        artifact=artifact,
    )
    return payload


def commit_ledger(entity_type: str, entity_id: int, *, run_id: uuid.UUID) -> Any:
    artifact = _artifact(entity_type, entity_id)
    repo = settings.WKAP_LEDGER_REPO_PATH
    if not repo:
        artifact.github_file_url = _github_url(_artifact_public_path(entity_type, artifact)) or artifact.canonical_url
        if entity_type == "wow":
            raw_path = _write_raw_email_artifact(artifact)
            artifact.raw_email_github_url = _github_url(raw_path) or str(raw_path)
            artifact.raw_email_commit_sha = "not_configured"
        artifact.github_commit_sha = "not_configured"
        artifact.save(update_fields=_commit_update_fields(entity_type))
        _refresh_artifact_files(entity_type, artifact)
        log_event(
            "github_commit_failed",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type=entity_type,
            entity_id=artifact.id,
            raw_email=artifact.source_email,
            artifact=artifact,
            error_code="ledger_repo_not_configured",
            error_message="WKAP_LEDGER_REPO_PATH is not configured.",
        )
        return artifact

    _sync_artifact_to_ledger_repo(entity_type, artifact)
    log_event(
        "github_commit_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type=entity_type,
        entity_id=artifact.id,
        artifact=artifact,
    )
    try:
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"Ledger {entity_type} {entity_id}")
        commit_sha = _git(repo, "rev-parse", "HEAD").strip()
        if _git_remote_exists(repo, "origin"):
            _git(repo, "push", "origin", settings.WKAP_LEDGER_BRANCH)
    except subprocess.CalledProcessError as exc:
        log_event(
            "github_commit_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            entity_type=entity_type,
            entity_id=artifact.id,
            artifact=artifact,
            error_code="git_commit_failed",
            error_message=str(exc),
        )
        raise

    artifact.github_commit_sha = commit_sha
    artifact.github_file_url = _github_url(_artifact_public_path(entity_type, artifact))
    if entity_type == "wow":
        artifact.raw_email_commit_sha = commit_sha
        artifact.raw_email_github_url = _github_url(_raw_email_public_path(artifact))
    artifact.save(update_fields=_commit_update_fields(entity_type))
    _refresh_artifact_files(entity_type, artifact)
    log_event("github_commit_succeeded", run_id=run_id, entity_type=entity_type, entity_id=artifact.id, artifact=artifact)
    return artifact


def timestamp_artifact(entity_type: str, entity_id: int, *, run_id: uuid.UUID):
    artifact = _artifact(entity_type, entity_id)
    log_event(
        "opentimestamp_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type=entity_type,
        entity_id=artifact.id,
        artifact=artifact,
    )
    if not settings.WKAP_OPENTIMESTAMP_ENABLED:
        artifact.ots_status = "queued"
        artifact.save(update_fields=["ots_status", "updated_at"])
        _refresh_artifact_files(entity_type, artifact)
        log_event(
            "opentimestamp_succeeded",
            run_id=run_id,
            entity_type=entity_type,
            entity_id=artifact.id,
            artifact=artifact,
            details={"mode": "queued_without_runtime"},
        )
        return artifact

    artifact.ots_status = "queued"
    artifact.save(update_fields=["ots_status", "updated_at"])
    _refresh_artifact_files(entity_type, artifact)
    log_event("opentimestamp_succeeded", run_id=run_id, entity_type=entity_type, entity_id=artifact.id, artifact=artifact)
    return artifact


def publish_artifact(entity_type: str, entity_id: int, *, run_id: uuid.UUID):
    artifact = _artifact(entity_type, entity_id)
    log_event(
        "publish_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type=entity_type,
        entity_id=artifact.id,
        raw_email=artifact.source_email,
        artifact=artifact,
    )
    if entity_type == "radar":
        generate_radar_html(artifact, run_id=run_id)
    else:
        generate_wow_html(artifact, run_id=run_id)
    generate_manifest(entity_type, entity_id, run_id=run_id)
    commit_ledger(entity_type, entity_id, run_id=run_id)
    timestamp_artifact(entity_type, entity_id, run_id=run_id)
    artifact.refresh_from_db()
    artifact.source_email.processing_status = RawEmail.ProcessingStatus.PUBLISHED
    artifact.source_email.save(update_fields=["processing_status", "updated_at"])
    log_event("page_published", run_id=run_id, entity_type=entity_type, entity_id=artifact.id, raw_email=artifact.source_email, artifact=artifact)
    if entity_type == "radar":
        send_radar_receipt(artifact, run_id=run_id)
    if entity_type == "wow":
        send_wow_receipt(artifact, run_id=run_id)
    artifact.refresh_from_db()
    log_event(
        "publish_succeeded",
        run_id=run_id,
        entity_type=entity_type,
        entity_id=artifact.id,
        raw_email=artifact.source_email,
        artifact=artifact,
    )
    return artifact


def validate_ledger(entity_type: str, entity_id: int) -> list[str]:
    artifact = _artifact(entity_type, entity_id)
    errors = []
    for field in ("canonical_url", "content_sha256", "github_file_url", "github_commit_sha", "manifest_url", "ots_status"):
        if not getattr(artifact, field):
            errors.append(f"{field} is missing")
    if entity_type == "wow":
        for field in ("raw_email_sha256", "raw_email_github_url", "raw_email_commit_sha"):
            if not getattr(artifact, field):
                errors.append(f"{field} is missing")
    if entity_type == "wow" and WOW_DISCLAIMER not in _public_file(wow_path(artifact.investor.investor_id, artifact.market_date)).read_text(
        encoding="utf-8"
    ):
        errors.append("WoW disclaimer is missing from public HTML")
    return errors


def validate_all() -> list[str]:
    errors: list[str] = []
    for issue in RadarIssue.objects.all():
        errors.extend([f"radar:{issue.id}: {error}" for error in validate_ledger("radar", issue.id)])
    for submission in DailyWoWPacket.objects.all():
        errors.extend([f"wow:{submission.id}: {error}" for error in validate_ledger("wow", submission.id)])
    return errors


def _artifact(entity_type: str, entity_id: int):
    if entity_type == "radar":
        return RadarIssue.objects.get(id=entity_id)
    if entity_type == "wow":
        return DailyWoWPacket.objects.select_related("investor").get(id=entity_id)
    raise ValueError("entity_type must be radar or wow")


def _artifact_public_path(entity_type: str, artifact) -> str:
    if entity_type == "radar":
        return radar_issue_path(artifact.market_date)
    return wow_path(artifact.investor.investor_id, artifact.market_date)


def _sync_artifact_to_ledger_repo(entity_type: str, artifact) -> None:
    repo = Path(settings.WKAP_LEDGER_REPO_PATH)
    relative_path = _artifact_public_path(entity_type, artifact)
    source = _public_file(relative_path)
    destination = repo / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if entity_type == "wow":
        raw_relative_path = _raw_email_public_path(artifact)
        raw_source = _write_raw_email_artifact(artifact)
        raw_destination = repo / raw_relative_path
        raw_destination.parent.mkdir(parents=True, exist_ok=True)
        if raw_source.resolve() != raw_destination.resolve():
            shutil.copyfile(raw_source, raw_destination)


def _manifest_payload(entity_type: str, artifact) -> dict[str, Any]:
    payload = {
        "entity_type": entity_type,
        "entity_id": artifact.id,
        "canonical_url": artifact.canonical_url,
        "content_sha256": artifact.content_sha256,
        "github_file_url": artifact.github_file_url,
        "github_commit_sha": artifact.github_commit_sha,
        "manifest_url": artifact.manifest_url,
        "ots_status": artifact.ots_status,
        "ots_proof_url": artifact.ots_proof_url,
        "market_date": str(artifact.market_date),
    }
    if entity_type == "wow":
        payload.update(
            {
                "format_version": artifact.format_version,
                "investor_id": artifact.investor.investor_id,
                "raw_email_sha256": artifact.raw_email_sha256,
                "raw_email_github_url": artifact.raw_email_github_url,
                "raw_email_commit_sha": artifact.raw_email_commit_sha,
                "raw_email_ledger_path": _raw_email_public_path(artifact),
                "selected_wow_id": artifact.selected_wow_id,
            }
        )
    return payload


def _write_public(relative_path: str, content: str) -> Path:
    path = _public_file(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _public_file(relative_path: str) -> Path:
    return settings.WKAP_PUBLIC_SITE_ROOT / relative_path


def _write_manifest(entity_type: str, entity_id: int, payload: dict[str, Any]) -> Path:
    path = _manifest_storage_path(entity_type, entity_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _manifest_storage_path(entity_type: str, entity_id: int) -> Path:
    return _ledger_artifact_root() / manifest_path(entity_type, entity_id)


def _refresh_artifact_files(entity_type: str, artifact) -> None:
    if entity_type == "radar":
        html = _render_radar(artifact)
        _write_public(radar_issue_path(artifact.market_date), html)
        artifact.body_html = html
        artifact.save(update_fields=["body_html", "updated_at"])
    else:
        _write_public(wow_path(artifact.investor.investor_id, artifact.market_date), _render_wow(artifact))
        _write_raw_email_artifact(artifact)

    if artifact.manifest_url:
        _write_manifest(entity_type, artifact.id, _manifest_payload(entity_type, artifact))


def _render_radar(issue: RadarIssue) -> str:
    return render_to_string("publishing/radar/issue.html", {"issue": issue})


def _render_wow(submission: DailyWoWPacket) -> str:
    selected_wow = submission.suggested_wows.filter(wow_id=submission.selected_wow_id).first() or submission.suggested_wows.first()
    selection_status = _wow_selection_status(submission)
    return render_to_string(
        "publishing/investors/wow.html",
        {
            "submission": submission,
            "selected_wow": selected_wow,
            "selection_status": selection_status,
            "disclaimer": WOW_DISCLAIMER,
            "page_type": "wow_submission",
            "agent_spec_version": submission.format_version,
            "agent_facts": _wow_agent_facts(submission, selected_wow, selection_status),
            "crawl_links": [
                {"rel": "up", "href": f"/investors/{submission.investor.investor_id}/wows/", "label": "investor-wow-archive"},
                {"rel": "archives", "href": "/investors/", "label": "wow-ledger"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
        },
    )


def _github_url(relative_or_absolute_path) -> str:
    base = settings.WKAP_LEDGER_GITHUB_BASE_URL.rstrip("/")
    if not base:
        return ""
    path = Path(relative_or_absolute_path)
    if path.is_absolute() and settings.WKAP_LEDGER_REPO_PATH:
        try:
            path = path.relative_to(settings.WKAP_LEDGER_REPO_PATH)
        except ValueError:
            pass
    return f"{base}/{str(path).replace(chr(92), '/')}"


def _raw_email_public_path(artifact: DailyWoWPacket) -> str:
    return f"raw-emails/wow-packets/wow-packet-{artifact.investor.investor_id}-{artifact.market_date}.txt"


def _write_raw_email_artifact(artifact: DailyWoWPacket) -> Path:
    path = _ledger_artifact_root() / _raw_email_public_path(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.source_email.raw_body, encoding="utf-8")
    return path


def _ledger_artifact_root() -> Path:
    return Path(settings.WKAP_LEDGER_REPO_PATH) if settings.WKAP_LEDGER_REPO_PATH else settings.BASE_DIR / "ledger_artifacts"


def _commit_update_fields(entity_type: str) -> list[str]:
    fields = ["github_file_url", "github_commit_sha", "updated_at"]
    if entity_type == "wow":
        fields.extend(["raw_email_github_url", "raw_email_commit_sha"])
    return fields


def _investors_with_wows():
    from ledger.models import Investor

    return (
        Investor.objects.filter(wows__isnull=False)
        .annotate(latest_wow_created_at=Max("wows__created_at"))
        .order_by("-latest_wow_created_at", "-id")
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _join_unique(values) -> str:
    seen = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.append(value)
    return "; ".join(seen)


def _wow_selection_status(submission: DailyWoWPacket) -> str:
    return "pass" if submission.selected_wow_id.lower() == "none" else "selected"


def _wow_agent_facts(submission: DailyWoWPacket, selected_wow, selection_status: str) -> list[dict[str, str]]:
    reading_items = list(submission.reading_items.all())
    suggested_wows = list(submission.suggested_wows.all())
    themes = _join_unique([wow.ticker_or_theme for wow in suggested_wows] + [item.tickers_or_themes for item in reading_items])
    source_urls = _join_unique(item.source_url for item in reading_items)
    source_types = _join_unique(item.source_type for item in reading_items)
    reading_origins = _join_unique(item.reading_origin for item in reading_items)
    evidence_to_watch = (
        selected_wow.evidence_to_watch_for
        if selected_wow and selection_status == "selected"
        else submission.missing_evidence
    )
    return [
        {"name": "artifact_type", "value": "wow"},
        {"name": "market_date", "value": str(submission.market_date)},
        {"name": "canonical_url", "value": submission.canonical_url or ""},
        {"name": "content_sha256", "value": submission.content_sha256 or ""},
        {"name": "github_file_url", "value": submission.github_file_url or ""},
        {"name": "github_commit_sha", "value": submission.github_commit_sha or ""},
        {"name": "manifest_url", "value": submission.manifest_url or ""},
        {"name": "opentimestamp_status", "value": submission.ots_status or ""},
        {"name": "investor_id", "value": submission.investor.investor_id},
        {"name": "investor_label", "value": submission.investor.public_label},
        {"name": "format_version", "value": submission.format_version},
        {"name": "selection_status", "value": selection_status},
        {"name": "selected_wow_id", "value": submission.selected_wow_id},
        {"name": "selected_theme", "value": selected_wow.ticker_or_theme if selected_wow else ""},
        {"name": "themes", "value": themes},
        {"name": "source_urls", "value": source_urls},
        {"name": "source_types", "value": source_types},
        {"name": "reading_origins", "value": reading_origins},
        {"name": "evidence_to_watch", "value": evidence_to_watch},
        {"name": "all_evidence_to_watch", "value": _join_unique(wow.evidence_to_watch_for for wow in suggested_wows)},
        {"name": "closest_rejected_idea", "value": submission.closest_rejected_idea},
        {"name": "missing_evidence", "value": submission.missing_evidence},
        {"name": "raw_email_sha256", "value": submission.raw_email_sha256},
        {"name": "raw_email_github_url", "value": submission.raw_email_github_url},
        {"name": "disclaimer", "value": WOW_DISCLAIMER},
    ]


def _radar_content_hash(issue: RadarIssue) -> str:
    return _sha256(f"radar\n{issue.market_date}\n{issue.title}\n{issue.body_text}")


def _wow_content_hash(submission: DailyWoWPacket) -> str:
    suggested = "\n".join(
        f"{wow.wow_id}\n{wow.ticker_or_theme}\n{wow.whats_worth_watching}\n{wow.why_now}\n{wow.evidence_to_watch_for}"
        for wow in submission.suggested_wows.all()
    )
    reading = "\n".join(
        f"{item.item_number}\n{item.source_title}\n{item.source_url}\n{item.reading_origin}\n{item.agent_summary}"
        for item in submission.reading_items.all()
    )
    return _sha256(
        "\n".join(
            [
                "wow_packet",
                submission.format_version,
                str(submission.market_date),
                submission.investor.investor_id,
                submission.selected_wow_id,
                submission.user_note,
                submission.closest_rejected_idea,
                submission.why_pass,
                submission.missing_evidence,
                reading,
                suggested,
            ]
        )
    )


def _git(repo: str | Path, *args: str) -> str:
    result = subprocess.run([settings.WKAP_GIT_EXECUTABLE, *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout


def _git_remote_exists(repo: str | Path, remote: str) -> bool:
    try:
        _git(repo, "remote", "get-url", remote)
    except subprocess.CalledProcessError:
        return False
    return True
