from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max
from django.template.loader import render_to_string

from core.events import log_event
from ingestion.models import RawEmail
from ledger.lifecycle_events import ensure_wow_lifecycle_events
from ledger.models import LedgerEvent, RadarIssue, DailyWoWPacket
from ledger.wow_contract import RADAR_CONTENT_SHA256_COVERS, WOW_CONTENT_SHA256_COVERS, clean_packet_text, json_array, local_wow_id, market_terms
from ledger.wow_lifecycle import ITEM_EVENT, STATUS_UPDATE_EVENT, lifecycle_records, lifecycle_records_json, status_update_records
from publishing.receipts import send_radar_receipt, send_wow_receipt
from publishing.urls import (
    investor_home_path,
    investor_wows_path,
    manifest_path,
    radar_archive_url,
    radar_issue_path,
    radar_issue_url,
    wow_path,
    wow_url,
)


WOW_DISCLAIMER = (
    "This is a ledgered Daily WoW Packet: reading log, agent-suggested WoWs, and investor selection/pass details. "
    "It is not WKAP editorial endorsement or investment advice."
)
ET_ZONE = ZoneInfo("America/New_York")


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
    ensure_wow_lifecycle_events(submission, run_id=run_id)
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
    for issue in radar_issues:
        _refresh_artifact_files("radar", issue)

    wow_submissions = DailyWoWPacket.objects.select_related("investor", "source_email").order_by("-created_at", "-id")
    for submission in wow_submissions:
        _refresh_artifact_files("wow", submission)

    _write_public("radar/index.html", render_to_string("publishing/radar/archive.html", {"issues": radar_issues}))
    investors = _investors_with_wows()
    _write_public(
        "investors/index.html",
        render_to_string(
            "publishing/investors/archive.html",
            {
                "investors": investors,
                "submissions": wow_submissions,
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
    target_path = _write_timestamp_target(entity_type, artifact)
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
        artifact.ots_proof_url = ""
        artifact.save(update_fields=["ots_status", "ots_proof_url", "updated_at"])
        _refresh_artifact_files(entity_type, artifact)
        commit_sha = _sync_and_commit_ledger_metadata(entity_type, artifact, f"Queue OpenTimestamp {entity_type} {entity_id}")
        log_event(
            "opentimestamp_succeeded",
            run_id=run_id,
            entity_type=entity_type,
            entity_id=artifact.id,
            artifact=artifact,
            details={"mode": "queued_without_runtime", "target_path": str(target_path), "commit_sha": commit_sha},
        )
        return artifact

    try:
        proof_path = _ots_proof_storage_path(entity_type, artifact.id)
        if not proof_path.exists():
            _run_ots("stamp", str(target_path))
        artifact.ots_status = "stamped"
        artifact.ots_proof_url = _github_url(proof_path) or str(proof_path)
        artifact.save(update_fields=["ots_status", "ots_proof_url", "updated_at"])
        _refresh_artifact_files(entity_type, artifact)
        commit_sha = _sync_and_commit_ledger_metadata(entity_type, artifact, f"OpenTimestamp {entity_type} {entity_id}")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        artifact.ots_status = "failed"
        artifact.save(update_fields=["ots_status", "updated_at"])
        _refresh_artifact_files(entity_type, artifact)
        log_event(
            "opentimestamp_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            entity_type=entity_type,
            entity_id=artifact.id,
            artifact=artifact,
            error_code=exc.__class__.__name__,
            error_message=_subprocess_error_message(exc),
        )
        raise

    log_event(
        "opentimestamp_succeeded",
        run_id=run_id,
        entity_type=entity_type,
        entity_id=artifact.id,
        artifact=artifact,
        details={"target_path": str(target_path), "proof_path": str(proof_path), "commit_sha": commit_sha},
    )
    return artifact


def timestamp_pending_artifacts(
    *,
    run_id: uuid.UUID,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int | None = None,
) -> list[Any]:
    candidates = _timestamp_pending_candidates(entity_type, entity_id)
    if limit is not None:
        candidates = candidates[:limit]
    stamped = []
    for current_entity_type, artifact in candidates:
        stamped.append(timestamp_artifact(current_entity_type, artifact.id, run_id=run_id))
    return stamped


def upgrade_opentimestamps(*, run_id: uuid.UUID, entity_type: str | None = None, entity_id: int | None = None) -> list[Any]:
    artifacts = _timestamp_upgrade_candidates(entity_type, entity_id)
    upgraded = []
    for current_entity_type, artifact in artifacts:
        proof_path = _ots_proof_storage_path(current_entity_type, artifact.id)
        if not proof_path.exists():
            log_event(
                "opentimestamp_upgrade_skipped",
                run_id=run_id,
                status=LedgerEvent.Status.SKIPPED,
                entity_type=current_entity_type,
                entity_id=artifact.id,
                artifact=artifact,
                error_code="proof_missing",
                error_message=f"OpenTimestamp proof file is missing: {proof_path}",
            )
            continue
        log_event(
            "opentimestamp_upgrade_started",
            run_id=run_id,
            status=LedgerEvent.Status.STARTED,
            entity_type=current_entity_type,
            entity_id=artifact.id,
            artifact=artifact,
        )
        try:
            _run_ots("upgrade", str(proof_path))
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            log_event(
                "opentimestamp_upgrade_failed",
                run_id=run_id,
                status=LedgerEvent.Status.FAILED,
                entity_type=current_entity_type,
                entity_id=artifact.id,
                artifact=artifact,
                error_code=exc.__class__.__name__,
                error_message=_subprocess_error_message(exc),
            )
            continue
        artifact.ots_status = "upgraded"
        artifact.save(update_fields=["ots_status", "updated_at"])
        _refresh_artifact_files(current_entity_type, artifact)
        commit_sha = (
            _commit_ledger_changes(settings.WKAP_LEDGER_REPO_PATH, f"Upgrade OpenTimestamp {current_entity_type} {artifact.id}")
            if settings.WKAP_LEDGER_REPO_PATH
            else ""
        )
        log_event(
            "opentimestamp_upgrade_succeeded",
            run_id=run_id,
            entity_type=current_entity_type,
            entity_id=artifact.id,
            artifact=artifact,
            details={"proof_path": str(proof_path), "commit_sha": commit_sha},
        )
        upgraded.append(artifact)
    return upgraded


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
    if entity_type == "radar":
        if settings.WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED:
            try:
                purge_radar_cache(artifact.market_date, run_id=run_id)
            except Exception as exc:
                log_event(
                    "radar_cache_purge_failed",
                    run_id=run_id,
                    status=LedgerEvent.Status.FAILED,
                    entity_type="radar",
                    entity_id=artifact.id,
                    raw_email=artifact.source_email,
                    artifact=artifact,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
        if settings.WKAP_CACHE_WARMUP_ENABLED:
            try:
                warm_radar_cache(artifact.market_date, run_id=run_id)
            except Exception as exc:
                log_event(
                    "radar_cache_warmup_failed",
                    run_id=run_id,
                    status=LedgerEvent.Status.FAILED,
                    entity_type="radar",
                    entity_id=artifact.id,
                    raw_email=artifact.source_email,
                    artifact=artifact,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
    log_event(
        "publish_succeeded",
        run_id=run_id,
        entity_type=entity_type,
        entity_id=artifact.id,
        raw_email=artifact.source_email,
        artifact=artifact,
    )
    return artifact


def radar_cache_urls(market_date) -> list[str]:
    return [radar_archive_url(), radar_issue_url(market_date)]


def purge_radar_cache(market_date, *, run_id: uuid.UUID) -> list[dict[str, Any]]:
    urls = radar_cache_urls(market_date)
    log_event(
        "radar_cache_purge_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type="radar",
        details={"market_date": str(market_date), "urls": urls},
    )
    if not settings.WKAP_CLOUDFLARE_ZONE_ID or not settings.WKAP_CLOUDFLARE_API_TOKEN:
        results = [{"url": url, "method": "PURGE", "skipped": True, "reason": "cloudflare_credentials_missing"} for url in urls]
        log_event(
            "radar_cache_purge_skipped",
            run_id=run_id,
            status=LedgerEvent.Status.SKIPPED,
            entity_type="radar",
            details={"market_date": str(market_date), "results": results},
            error_code="cloudflare_credentials_missing",
            error_message="WKAP_CLOUDFLARE_ZONE_ID and WKAP_CLOUDFLARE_API_TOKEN are required to purge Radar cache.",
        )
        return results

    result = _purge_cloudflare_files(urls)
    results = [{**result, "url": url, "method": "PURGE"} for url in urls]
    errors = [item for item in results if item.get("error")]
    log_event(
        "radar_cache_purge_failed" if errors else "radar_cache_purge_succeeded",
        run_id=run_id,
        status=LedgerEvent.Status.FAILED if errors else LedgerEvent.Status.SUCCEEDED,
        entity_type="radar",
        details={"market_date": str(market_date), "results": results},
        error_code="cloudflare_purge_failed" if errors else "",
        error_message="; ".join(f"{item['url']}: {item['error']}" for item in errors),
    )
    return results


def _purge_cloudflare_files(urls: list[str]) -> dict[str, Any]:
    payload = json.dumps({"files": urls}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones/{settings.WKAP_CLOUDFLARE_ZONE_ID}/purge_cache",
        data=payload,
        headers={
            "authorization": f"Bearer {settings.WKAP_CLOUDFLARE_API_TOKEN}",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "WKAP cache purge/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.WKAP_CACHE_WARMUP_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            if not parsed.get("success", False):
                return {
                    "status_code": response.getcode(),
                    "error": json.dumps(parsed.get("errors") or parsed, ensure_ascii=False),
                }
            return {"status_code": response.getcode(), "success": True}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status_code": exc.code, "error": body or str(exc)}
    except urllib.error.URLError as exc:
        return {"error": str(exc.reason)}
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def warm_radar_cache(market_date, *, run_id: uuid.UUID) -> list[dict[str, Any]]:
    urls = radar_cache_urls(market_date)
    log_event(
        "radar_cache_warmup_started",
        run_id=run_id,
        status=LedgerEvent.Status.STARTED,
        entity_type="radar",
        details={"market_date": str(market_date), "urls": urls},
    )
    results = [_warm_cache_url(url) for url in urls]
    errors = [result for result in results if result.get("error")]
    log_event(
        "radar_cache_warmup_failed" if errors else "radar_cache_warmup_succeeded",
        run_id=run_id,
        status=LedgerEvent.Status.FAILED if errors else LedgerEvent.Status.SUCCEEDED,
        entity_type="radar",
        details={"market_date": str(market_date), "results": results},
        error_code="cache_warmup_request_failed" if errors else "",
        error_message="; ".join(f"{item['url']}: {item['error']}" for item in errors),
    )
    return results


def _warm_cache_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "text/html,*/*;q=0.8",
            "user-agent": "WKAP cache warmup/1.0",
        },
        method="GET",
    )
    result: dict[str, Any] = {"url": url, "method": "GET"}
    try:
        with urllib.request.urlopen(request, timeout=settings.WKAP_CACHE_WARMUP_TIMEOUT_SECONDS) as response:
            response.read()
            headers = response.headers
            result.update(
                {
                    "status_code": response.getcode(),
                    "cf_cache_status": headers.get("cf-cache-status", ""),
                    "cache_control": headers.get("cache-control", ""),
                    "content_length": headers.get("content-length", ""),
                }
            )
    except urllib.error.HTTPError as exc:
        result.update({"status_code": exc.code, "error": str(exc)})
    except urllib.error.URLError as exc:
        result.update({"error": str(exc.reason)})
    except OSError as exc:
        result.update({"error": str(exc)})
    return result


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
        errors.extend(_wow_lifecycle_validation_errors(artifact))
    if entity_type == "wow" and WOW_DISCLAIMER not in _public_file(wow_path(artifact.investor.investor_id, artifact.market_date)).read_text(
        encoding="utf-8"
    ):
        errors.append("WoW disclaimer is missing from public HTML")
    return errors


def _wow_lifecycle_validation_errors(submission: DailyWoWPacket) -> list[str]:
    records = lifecycle_records(
        submission.wow_items_json,
        investor_id=submission.investor.investor_id,
        packet_id=submission.packet_id,
    )
    if not records:
        return ["wow lifecycle records are missing"]

    errors: list[str] = []
    for record in records:
        wow_id = str(record.get("wow_id") or "")
        if not wow_id:
            errors.append(f"wow lifecycle record {record.get('item_number')} missing wow_id")
            continue
        if record.get("wow_type") == "status_update":
            for field in ("target_wow_id", "target_root_wow_id", "update_type", "new_status"):
                if not record.get(field):
                    errors.append(f"status_update {wow_id} missing {field}")
        event_name = STATUS_UPDATE_EVENT if record.get("wow_type") == "status_update" else ITEM_EVENT
        if not LedgerEvent.objects.filter(
            entity_type="wow",
            entity_id=str(submission.id),
            event_name=event_name,
            details__wow_id=wow_id,
        ).exists():
            errors.append(f"lifecycle LedgerEvent missing for {wow_id}")
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


def _sync_and_commit_ledger_metadata(entity_type: str, artifact, message: str) -> str:
    if not settings.WKAP_LEDGER_REPO_PATH:
        return ""
    _sync_artifact_to_ledger_repo(entity_type, artifact)
    return _commit_ledger_changes(settings.WKAP_LEDGER_REPO_PATH, message)


def _manifest_payload(entity_type: str, artifact) -> dict[str, Any]:
    payload = {
        "entity_type": entity_type,
        "entity_id": artifact.id,
        "canonical_url": artifact.canonical_url,
        "content_sha256": artifact.content_sha256,
        "content_sha256_covers": _content_sha256_covers(entity_type),
        "github_file_url": artifact.github_file_url,
        "github_commit_sha": artifact.github_commit_sha,
        "manifest_url": artifact.manifest_url,
        "ots_status": artifact.ots_status,
        "ots_proof_url": artifact.ots_proof_url,
        "opentimestamp_target_url": _github_url(_timestamp_target_storage_path(entity_type, artifact.id))
        or str(_timestamp_target_storage_path(entity_type, artifact.id)),
        "market_date": str(artifact.market_date),
    }
    if entity_type == "wow":
        wow_terms = _wow_market_terms(artifact)
        selected_wow = artifact.suggested_wows.filter(wow_id=artifact.selected_wow_id).first()
        payload.update(
            {
                "format_version": artifact.format_version,
                "packet_id": artifact.packet_id,
                "packet_spec_version": artifact.packet_spec_version,
                "packet_spec_url": artifact.packet_spec_url,
                "skill_version": artifact.skill_version,
                "skill_url": artifact.skill_url,
                "investor_id": artifact.investor.investor_id,
                "public_status": artifact.public_status,
                "wow_count": artifact.wow_count,
                "scoreable_count": artifact.scoreable_count,
                "trackable_count": artifact.trackable_count,
                "thesis_count": artifact.thesis_count,
                "candidate_count": artifact.candidate_count,
                "status_update_count": artifact.status_update_count,
                "raw_packet_json": artifact.raw_packet_json,
                "agent_facts_json": artifact.agent_facts_json,
                "validation_results_json": artifact.validation_results_json,
                "wow_items_json": artifact.wow_items_json,
                "raw_email_sha256": artifact.raw_email_sha256,
                "raw_email_github_url": artifact.raw_email_github_url,
                "raw_email_commit_sha": artifact.raw_email_commit_sha,
                "raw_email_ledger_path": _raw_email_public_path(artifact),
                "selected_wow_id": artifact.selected_wow_id,
                "public_selected_wow_id": artifact.public_selected_wow_id,
                "tickers": wow_terms["tickers"],
                "themes": wow_terms["themes"],
                "source_urls": _unique_values(item.source_url for item in artifact.reading_items.all()),
                "source_types": _unique_values(item.source_type for item in artifact.reading_items.all()),
                "reading_origins": _unique_values(item.reading_origin for item in artifact.reading_items.all()),
                "evidence_to_watch": _wow_evidence_to_watch(artifact, selected_wow),
                "all_evidence_to_watch": _unique_values(clean_packet_text(wow.evidence_to_watch_for) for wow in artifact.suggested_wows.all()),
                "suggested_wows": [
                    {
                        "public_wow_id": wow.public_wow_id,
                        "packet_wow_id": wow.wow_id,
                        "ticker_or_theme": wow.ticker_or_theme,
                        "selected": wow.selected,
                    }
                    for wow in artifact.suggested_wows.all()
                ],
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


def _timestamp_target_storage_path(entity_type: str, entity_id: int) -> Path:
    return _ledger_artifact_root() / "timestamps" / f"{entity_type}-{entity_id}.json"


def _ots_proof_storage_path(entity_type: str, entity_id: int) -> Path:
    return Path(f"{_timestamp_target_storage_path(entity_type, entity_id)}.ots")


def _write_timestamp_target(entity_type: str, artifact) -> Path:
    path = _timestamp_target_storage_path(entity_type, artifact.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_timestamp_target_payload(entity_type, artifact), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _timestamp_target_payload(entity_type: str, artifact) -> dict[str, Any]:
    payload = {
        "timestamp_target_version": "wkap-opentimestamp-target-v1",
        "entity_type": entity_type,
        "entity_id": artifact.id,
        "canonical_url": artifact.canonical_url,
        "content_sha256": artifact.content_sha256,
        "content_sha256_covers": _content_sha256_covers(entity_type),
        "github_file_url": artifact.github_file_url,
        "github_commit_sha": artifact.github_commit_sha,
        "manifest_url": artifact.manifest_url,
        "market_date": str(artifact.market_date),
    }
    if entity_type == "wow":
        payload.update(
            {
                "format_version": artifact.format_version,
                "packet_id": artifact.packet_id,
                "packet_spec_version": artifact.packet_spec_version,
                "investor_id": artifact.investor.investor_id,
                "raw_email_sha256": artifact.raw_email_sha256,
                "raw_email_github_url": artifact.raw_email_github_url,
                "raw_email_commit_sha": artifact.raw_email_commit_sha,
            }
        )
    return payload


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
    subject_display_name = submission.investor.display_name or "unknown subject name"
    received_at_et = submission.source_email.received_at.astimezone(ET_ZONE)
    received_at_et_display = received_at_et.strftime("%Y-%m-%d %H:%M ET")
    return render_to_string(
        "publishing/investors/wow.html",
        {
            "submission": submission,
            "selected_wow": selected_wow,
            "selection_status": selection_status,
            "subject_display_name": subject_display_name,
            "received_at_et_display": received_at_et_display,
            "disclaimer": WOW_DISCLAIMER,
            "page_type": "wow_submission",
            "agent_spec_version": submission.format_version,
            "agent_facts": _wow_agent_facts(submission, selected_wow, selection_status),
            "wow_signal_records": _wow_signal_records(submission),
            "status_update_records": status_update_records(
                submission.wow_items_json,
                investor_id=submission.investor.investor_id,
                packet_id=submission.packet_id,
            ),
            "crawl_links": [
                {"rel": "up", "href": f"/investors/{submission.investor.investor_id}/wows/", "label": "investor-wow-archive"},
                {"rel": "archives", "href": "/investors/", "label": "wow-ledger"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
        },
    )


def _wow_signal_records(submission: DailyWoWPacket) -> list[dict[str, object]]:
    lifecycle_by_id = {}
    for record in lifecycle_records(
        submission.wow_items_json,
        investor_id=submission.investor.investor_id,
        packet_id=submission.packet_id,
    ):
        for key in (str(record.get("wow_id") or ""), str(record.get("public_wow_id") or "")):
            if key:
                lifecycle_by_id[key] = record
                lifecycle_by_id[local_wow_id(key)] = record

    raw_by_id = {}
    for item in submission.wow_items_json or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("wow_id") or "")
        if key:
            raw_by_id[key] = item
            raw_by_id[local_wow_id(key)] = item

    records = []
    for wow in submission.suggested_wows.all():
        lifecycle = lifecycle_by_id.get(wow.wow_id, {})
        raw = raw_by_id.get(wow.wow_id, {})
        wow_type = str(lifecycle.get("wow_type") or raw.get("wow_type") or "candidate_wow")
        records.append(
            {
                "wow": wow,
                "wow_type": wow_type,
                "type_rows": _wow_type_rows(wow_type, raw, lifecycle),
            }
        )
    return records


def _wow_type_rows(wow_type: str, raw: dict, lifecycle: dict) -> list[dict[str, str]]:
    rows = [
        {"label": "WoW type", "field": "wow_type", "value": wow_type},
        {"label": "Parent WoW ID", "field": "parent_wow_id", "value": _row_value(lifecycle, raw, "parent_wow_id")},
        {"label": "Root WoW ID", "field": "root_wow_id", "value": _row_value(lifecycle, raw, "root_wow_id")},
        {"label": "Scoreable", "field": "scoreable", "value": _bool_row_value(lifecycle.get("scoreable", raw.get("scoreable")))},
        {
            "label": "Accuracy endpoint eligible",
            "field": "accuracy_endpoint_eligible",
            "value": _bool_row_value(lifecycle.get("accuracy_endpoint_eligible", raw.get("accuracy_endpoint_eligible"))),
        },
    ]
    if wow_type == "status_update":
        rows.extend(
            [
                {"label": "Target WoW type", "field": "target_wow_type", "value": _row_value(lifecycle, raw, "target_wow_type")},
                {"label": "Target WoW ID", "field": "target_wow_id", "value": _row_value(lifecycle, raw, "target_wow_id")},
                {"label": "Target root WoW ID", "field": "target_root_wow_id", "value": _row_value(lifecycle, raw, "target_root_wow_id")},
                {"label": "Update type", "field": "update_type", "value": _row_value(lifecycle, raw, "update_type")},
                {"label": "Previous status", "field": "previous_status", "value": _row_value(lifecycle, raw, "previous_status")},
                {"label": "New status", "field": "new_status", "value": _row_value(lifecycle, raw, "new_status")},
                {"label": "Update summary", "field": "update_summary", "value": _row_value(lifecycle, raw, "update_summary")},
                {"label": "Evidence summary", "field": "evidence_summary", "value": _row_value(lifecycle, raw, "evidence_summary")},
                {"label": "Resolution source used", "field": "resolution_source_used", "value": _row_value(lifecycle, raw, "resolution_source_used")},
                {"label": "Lineage node", "field": "lineage_node", "value": "false"},
            ]
        )
    elif wow_type == "scoreable_signal":
        rows.extend(
            [
                {"label": "Claim", "field": "claim", "value": _row_value(lifecycle, raw, "claim")},
                {"label": "Invalidate test", "field": "invalidate_test", "value": _row_value(lifecycle, raw, "invalidate_test")},
                {"label": "Resolve by", "field": "resolve_by", "value": _row_value(lifecycle, raw, "resolve_by")},
                {"label": "Resolution source", "field": "resolution_source", "value": _row_value(lifecycle, raw, "resolution_source")},
                {"label": "Signal status", "field": "signal_status", "value": _row_value(lifecycle, raw, "signal_status")},
            ]
        )
    elif wow_type == "trackable_wow":
        rows.extend(
            [
                {"label": "Claim", "field": "claim", "value": _row_value(lifecycle, raw, "claim")},
                {"label": "Evidence to watch", "field": "evidence_to_watch", "value": _list_row_value(raw.get("evidence_to_watch"))},
                {"label": "Review cadence", "field": "review_cadence", "value": _row_value(lifecycle, raw, "review_cadence")},
                {"label": "Next review", "field": "next_review_at", "value": _row_value(lifecycle, raw, "next_review_at")},
                {"label": "Trackable status", "field": "trackable_status", "value": _row_value(lifecycle, raw, "trackable_status")},
            ]
        )
    elif wow_type == "thesis_wow":
        rows.extend(
            [
                {"label": "Thesis claim", "field": "thesis_claim", "value": _row_value(lifecycle, raw, "thesis_claim", "claim")},
                {"label": "Thesis status", "field": "thesis_status", "value": _row_value(lifecycle, raw, "thesis_status")},
            ]
        )
    else:
        rows.extend(
            [
                {"label": "Observation", "field": "observation", "value": _row_value(lifecycle, raw, "observation", "claim")},
                {"label": "Why worth watching", "field": "why_worth_watching", "value": _row_value(lifecycle, raw, "why_worth_watching")},
            ]
        )
    rows.append({"label": "Source refs", "field": "source_refs", "value": _list_row_value(lifecycle.get("source_refs") or raw.get("source_refs"))})
    return [row for row in rows if row["value"] not in ("", None)]


def _row_value(primary: dict, fallback: dict, *keys: str) -> str:
    for source in (primary, fallback):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return _list_row_value(value)
    return ""


def _list_row_value(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item not in (None, ""))
    return str(value or "")


def _bool_row_value(value) -> str:
    return "true" if bool(value) else "false"


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


def _unique_values(values) -> list[str]:
    seen = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _content_sha256_covers(entity_type: str) -> str:
    return RADAR_CONTENT_SHA256_COVERS if entity_type == "radar" else WOW_CONTENT_SHA256_COVERS


def _wow_selection_status(submission: DailyWoWPacket) -> str:
    return "pass" if submission.selected_wow_id.lower() == "none" else "selected"


def _wow_pass_fact_value(submission: DailyWoWPacket, selection_status: str, value: str) -> str:
    if selection_status == "selected":
        return "N/A - Not Applicable"
    return value


def _timestamp_upgrade_candidates(entity_type: str | None, entity_id: int | None) -> list[tuple[str, Any]]:
    if entity_type and entity_id:
        return [(entity_type, _artifact(entity_type, entity_id))]
    if entity_type == "radar":
        return [("radar", issue) for issue in RadarIssue.objects.exclude(ots_proof_url="").order_by("id")]
    if entity_type == "wow":
        return [("wow", packet) for packet in DailyWoWPacket.objects.select_related("investor").exclude(ots_proof_url="").order_by("id")]
    return [
        *[("radar", issue) for issue in RadarIssue.objects.exclude(ots_proof_url="").order_by("id")],
        *[("wow", packet) for packet in DailyWoWPacket.objects.select_related("investor").exclude(ots_proof_url="").order_by("id")],
    ]


def _timestamp_pending_candidates(entity_type: str | None, entity_id: int | None) -> list[tuple[str, Any]]:
    statuses = ["", "not_started"]

    if entity_type and entity_id:
        artifact = _artifact(entity_type, entity_id)
        return [(entity_type, artifact)] if artifact.ots_status in statuses and _artifact_ready_for_timestamp(artifact) else []
    if entity_type == "radar":
        return [("radar", issue) for issue in _timestamp_ready(RadarIssue.objects.filter(ots_status__in=statuses)).order_by("market_date", "id")]
    if entity_type == "wow":
        return [
            ("wow", packet)
            for packet in _timestamp_ready(DailyWoWPacket.objects.select_related("investor").filter(ots_status__in=statuses)).order_by(
                "market_date", "id"
            )
        ]
    return [
        *[("radar", issue) for issue in _timestamp_ready(RadarIssue.objects.filter(ots_status__in=statuses)).order_by("market_date", "id")],
        *[
            ("wow", packet)
            for packet in _timestamp_ready(DailyWoWPacket.objects.select_related("investor").filter(ots_status__in=statuses)).order_by(
                "market_date", "id"
            )
        ],
    ]


def _timestamp_ready(queryset):
    for field in ("canonical_url", "content_sha256", "github_file_url", "github_commit_sha", "manifest_url"):
        queryset = queryset.exclude(**{field: ""})
    return queryset


def _artifact_ready_for_timestamp(artifact) -> bool:
    return all(getattr(artifact, field, "") for field in ("canonical_url", "content_sha256", "github_file_url", "github_commit_sha", "manifest_url"))


def _wow_agent_facts(submission: DailyWoWPacket, selected_wow, selection_status: str) -> list[dict[str, str]]:
    reading_items = list(submission.reading_items.all())
    suggested_wows = list(submission.suggested_wows.all())
    terms = _wow_market_terms(submission, reading_items=reading_items, suggested_wows=suggested_wows)
    themes = _join_unique([wow.ticker_or_theme for wow in suggested_wows] + [item.tickers_or_themes for item in reading_items])
    source_urls = _unique_values(item.source_url for item in reading_items)
    source_types = _unique_values(item.source_type for item in reading_items)
    reading_origins = _unique_values(item.reading_origin for item in reading_items)
    evidence_to_watch = _wow_evidence_to_watch(submission, selected_wow, selection_status=selection_status)
    subject_display_name = submission.investor.display_name or "unknown subject name"
    received_at_et = submission.source_email.received_at.astimezone(ET_ZONE)
    facts = [
        {"name": "artifact_type", "value": "wow"},
        {"name": "market_date", "value": str(submission.market_date)},
        {"name": "canonical_url", "value": submission.canonical_url or ""},
        {"name": "content_sha256", "value": submission.content_sha256 or ""},
        {"name": "content_sha256_covers", "value": WOW_CONTENT_SHA256_COVERS},
        {"name": "github_file_url", "value": submission.github_file_url or ""},
        {"name": "github_commit_sha", "value": submission.github_commit_sha or ""},
        {"name": "manifest_url", "value": submission.manifest_url or ""},
        {"name": "opentimestamp_status", "value": submission.ots_status or ""},
        {"name": "investor_id", "value": submission.investor.investor_id},
        {"name": "investor_label", "value": submission.investor.public_label},
        {"name": "subject_line_display_name", "value": subject_display_name},
        {"name": "submission_channel", "value": "email"},
        {"name": "received_at_et", "value": received_at_et.strftime("%Y-%m-%d %H:%M ET")},
        {"name": "format_version", "value": submission.format_version},
        {"name": "packet_id", "value": submission.packet_id},
        {"name": "packet_spec_version", "value": submission.packet_spec_version},
        {"name": "packet_spec_url", "value": submission.packet_spec_url},
        {"name": "skill_version", "value": submission.skill_version},
        {"name": "skill_url", "value": submission.skill_url},
        {"name": "public_status", "value": submission.public_status},
        {"name": "wow_count", "value": str(submission.wow_count)},
        {"name": "scoreable_count", "value": str(submission.scoreable_count)},
        {"name": "trackable_count", "value": str(submission.trackable_count)},
        {"name": "thesis_count", "value": str(submission.thesis_count)},
        {"name": "candidate_count", "value": str(submission.candidate_count)},
        {"name": "status_update_count", "value": str(submission.status_update_count)},
        {"name": "selection_status", "value": selection_status},
        {"name": "selected_wow_id", "value": submission.public_selected_wow_id},
        {"name": "packet_selected_wow_id", "value": submission.selected_wow_id},
        {"name": "selected_theme", "value": selected_wow.ticker_or_theme if selected_wow else ""},
        {"name": "themes", "value": themes},
        {"name": "tickers_json", "value": json_array(terms["tickers"])},
        {"name": "themes_json", "value": json_array(terms["themes"])},
        {"name": "source_urls", "value": _join_unique(source_urls)},
        {"name": "source_urls_json", "value": json_array(source_urls)},
        {"name": "source_types", "value": _join_unique(source_types)},
        {"name": "source_types_json", "value": json_array(source_types)},
        {"name": "reading_origins", "value": _join_unique(reading_origins)},
        {"name": "reading_origins_json", "value": json_array(reading_origins)},
        {"name": "evidence_to_watch", "value": evidence_to_watch},
        {"name": "evidence_to_watch_json", "value": json_array([evidence_to_watch])},
        {"name": "all_evidence_to_watch", "value": _join_unique(clean_packet_text(wow.evidence_to_watch_for) for wow in suggested_wows)},
        {"name": "all_evidence_to_watch_json", "value": json_array(clean_packet_text(wow.evidence_to_watch_for) for wow in suggested_wows)},
        {
            "name": "lifecycle_events_json",
            "value": lifecycle_records_json(
                submission.wow_items_json,
                investor_id=submission.investor.investor_id,
                packet_id=submission.packet_id,
            ),
        },
        {
            "name": "current_wow_state_json",
            "value": lifecycle_records_json(
                submission.wow_items_json,
                investor_id=submission.investor.investor_id,
                packet_id=submission.packet_id,
            ),
        },
        {
            "name": "status_updates_json",
            "value": json.dumps(
                status_update_records(
                    submission.wow_items_json,
                    investor_id=submission.investor.investor_id,
                    packet_id=submission.packet_id,
                ),
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        {"name": "raw_email_sha256", "value": submission.raw_email_sha256},
        {"name": "raw_email_github_url", "value": submission.raw_email_github_url},
        {"name": "raw_packet_json", "value": json.dumps(submission.raw_packet_json, ensure_ascii=False, sort_keys=True)},
        {"name": "wow_items_json", "value": json.dumps(submission.wow_items_json, ensure_ascii=False, sort_keys=True)},
        {"name": "disclaimer", "value": WOW_DISCLAIMER},
    ]
    facts.append({"name": "reason_for_pass", "value": _wow_pass_fact_value(submission, selection_status, submission.why_pass)})
    facts.append({"name": "closest_rejected_wow", "value": _wow_pass_fact_value(submission, selection_status, submission.closest_rejected_idea)})
    facts.append({"name": "missing_evidence", "value": _wow_pass_fact_value(submission, selection_status, submission.missing_evidence)})
    return facts


def _wow_market_terms(submission: DailyWoWPacket, *, reading_items=None, suggested_wows=None) -> dict[str, list[str]]:
    reading_items = list(reading_items) if reading_items is not None else list(submission.reading_items.all())
    suggested_wows = list(suggested_wows) if suggested_wows is not None else list(submission.suggested_wows.all())
    return market_terms([wow.ticker_or_theme for wow in suggested_wows] + [item.tickers_or_themes for item in reading_items])


def _wow_evidence_to_watch(submission: DailyWoWPacket, selected_wow, *, selection_status: str | None = None) -> str:
    status = selection_status or _wow_selection_status(submission)
    if selected_wow and status == "selected":
        return clean_packet_text(selected_wow.evidence_to_watch_for)
    return clean_packet_text(submission.missing_evidence)


def _radar_content_hash(issue: RadarIssue) -> str:
    return _sha256(f"radar\n{issue.market_date}\n{issue.title}\n{issue.body_text}")


def _wow_content_hash(submission: DailyWoWPacket) -> str:
    if submission.raw_packet_json:
        return _sha256(json.dumps(submission.raw_packet_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
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
                submission.reason_for_selection,
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


def _commit_ledger_changes(repo: str | Path, message: str) -> str:
    _git(repo, "add", ".")
    if not _git(repo, "status", "--porcelain").strip():
        return ""
    _git(repo, "commit", "-m", message)
    commit_sha = _git(repo, "rev-parse", "HEAD").strip()
    if _git_remote_exists(repo, "origin"):
        _git(repo, "push", "origin", settings.WKAP_LEDGER_BRANCH)
    return commit_sha


def _run_ots(*args: str) -> str:
    result = subprocess.run(
        [settings.WKAP_OPENTIMESTAMP_COMMAND, *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _subprocess_error_message(exc: FileNotFoundError | subprocess.CalledProcessError) -> str:
    if isinstance(exc, FileNotFoundError):
        return str(exc)
    return "\n".join(part for part in [exc.stdout, exc.stderr, str(exc)] if part)
