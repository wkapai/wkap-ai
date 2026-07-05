from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape

from ledger.models import Investor, RadarIssue, DailyWoWPacket
from ledger.wow_contract import RADAR_CONTENT_SHA256_COVERS, WOW_CONTENT_SHA256_COVERS, clean_packet_text, json_array, market_terms
from ledger.wow_packet_spec import current_spec
from publishing.services import WOW_DISCLAIMER
from publishing.urls import investor_home_url, investor_wows_url, radar_archive_url, radar_issue_url, wow_url


ET_ZONE = ZoneInfo("America/New_York")

MARKDOWN_RESOURCES = {
    "wow_packet_v0_1": "specs/public/wow-packet-v0.1.md",
    "wkap_wow_skill_v0_1": "specs/public/wkap-wow-skill-v0.1.md",
    "wkap_wow_codex_skill": "agent_skills/wkap-wow/SKILL.md",
}


def _json_ld(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _page_context(
    *,
    title: str,
    description: str,
    canonical_url: str,
    page_type: str,
    agent_facts: list[dict[str, str]] | None = None,
    json_ld: dict | None = None,
    **extra,
):
    context = {
        "meta_title": title,
        "meta_description": description,
        "canonical_url": canonical_url,
        "page_type": page_type,
        "agent_spec_version": "wow_packet_v1",
        "crawl_links": extra.pop("crawl_links", []),
        "agent_facts": agent_facts or [],
        "json_ld": _json_ld(json_ld or _website_json_ld(canonical_url)),
    }
    context.update(extra)
    return context


def _website_json_ld(canonical_url: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "WKAP.ai",
        "url": settings.WKAP_BASE_URL,
        "mainEntityOfPage": canonical_url,
        "description": "WKAP.ai publishes ledgered Radar Feed and WoW market intelligence pages for agent validation.",
    }


def _artifact_facts(artifact, artifact_type: str) -> list[dict[str, str]]:
    return [
        {"name": "artifact_type", "value": artifact_type},
        {"name": "market_date", "value": str(artifact.market_date)},
        {"name": "canonical_url", "value": artifact.canonical_url or ""},
        {"name": "content_sha256", "value": artifact.content_sha256 or ""},
        {"name": "content_sha256_covers", "value": _content_sha256_covers(artifact_type)},
        {"name": "github_file_url", "value": artifact.github_file_url or ""},
        {"name": "github_commit_sha", "value": artifact.github_commit_sha or ""},
        {"name": "manifest_url", "value": artifact.manifest_url or ""},
        {"name": "opentimestamp_status", "value": artifact.ots_status or ""},
        {"name": "opentimestamp_proof_url", "value": artifact.ots_proof_url or ""},
    ]


def _optional_facts(items: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in items if value]


def _wow_pass_fact_value(submission: DailyWoWPacket, value: str) -> str:
    if _wow_selection_status(submission) == "selected":
        return "N/A - Not Applicable"
    return value


def _artifact_json_ld(artifact, artifact_type: str, title: str, body: str, extra: dict | None = None) -> dict:
    payload = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "name": title,
        "url": artifact.canonical_url,
        "datePublished": str(artifact.market_date),
        "dateModified": artifact.updated_at.isoformat() if artifact.updated_at else "",
        "articleSection": artifact_type,
        "description": body[:240],
        "encoding": {
            "@type": "MediaObject",
            "encodingFormat": "text/html",
            "sha256": artifact.content_sha256,
            "contentSha256Covers": _content_sha256_covers(artifact_type.lower().replace("wkap radar feed", "radar").replace("daily wow packet", "wow")),
        },
        "isPartOf": _website_json_ld(artifact.canonical_url),
        "identifier": [
            {"@type": "PropertyValue", "propertyID": "content_sha256", "value": artifact.content_sha256},
            {"@type": "PropertyValue", "propertyID": "github_commit_sha", "value": artifact.github_commit_sha},
            {"@type": "PropertyValue", "propertyID": "manifest_url", "value": artifact.manifest_url},
            {"@type": "PropertyValue", "propertyID": "opentimestamp_status", "value": artifact.ots_status},
        ],
    }
    if extra:
        payload.update(extra)
    return payload


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


def _content_sha256_covers(artifact_type: str) -> str:
    return RADAR_CONTENT_SHA256_COVERS if artifact_type == "radar" else WOW_CONTENT_SHA256_COVERS


def _wow_selection_status(submission: DailyWoWPacket) -> str:
    return "pass" if submission.selected_wow_id.lower() == "none" else "selected"


def _wow_agent_summary(submission: DailyWoWPacket, selected_wow) -> dict[str, str]:
    reading_items = list(submission.reading_items.all())
    suggested_wows = list(submission.suggested_wows.all())
    terms = market_terms([wow.ticker_or_theme for wow in suggested_wows] + [item.tickers_or_themes for item in reading_items])
    source_urls = _unique_values(item.source_url for item in reading_items)
    source_types = _unique_values(item.source_type for item in reading_items)
    reading_origins = _unique_values(item.reading_origin for item in reading_items)
    evidence_to_watch = (
        clean_packet_text(selected_wow.evidence_to_watch_for)
        if selected_wow and _wow_selection_status(submission) == "selected"
        else clean_packet_text(submission.missing_evidence)
    )
    return {
        "selection_status": _wow_selection_status(submission),
        "selected_theme": selected_wow.ticker_or_theme if selected_wow else "",
        "themes": _join_unique(
            [wow.ticker_or_theme for wow in suggested_wows]
            + [item.tickers_or_themes for item in reading_items]
        ),
        "tickers_json": json_array(terms["tickers"]),
        "themes_json": json_array(terms["themes"]),
        "tickers": terms["tickers"],
        "themes_array": terms["themes"],
        "source_urls": _join_unique(source_urls),
        "source_urls_json": json_array(source_urls),
        "source_types": _join_unique(source_types),
        "source_types_json": json_array(source_types),
        "reading_origins": _join_unique(reading_origins),
        "reading_origins_json": json_array(reading_origins),
        "evidence_to_watch": evidence_to_watch,
        "evidence_to_watch_json": json_array([evidence_to_watch]),
        "all_evidence_to_watch": _join_unique(clean_packet_text(wow.evidence_to_watch_for) for wow in suggested_wows),
        "all_evidence_to_watch_json": json_array(clean_packet_text(wow.evidence_to_watch_for) for wow in suggested_wows),
    }


def home(request):
    latest_radar = RadarIssue.objects.order_by("-market_date").first()
    latest_wow = DailyWoWPacket.objects.select_related("investor").order_by("-created_at", "-id").first()
    return render(
        request,
        "publishing/home.html",
        _page_context(
            title="WKAP.ai - Build Your AI-Native Investor Loop",
            description="WKAP turns daily investment research into a feedback loop for investors and their agents, with public Daily WoW Packet ledger records.",
            canonical_url=f"{settings.WKAP_BASE_URL}/",
            page_type="home",
            agent_facts=[
                {"name": "site_name", "value": "WKAP.ai"},
                {"name": "purpose", "value": "Build Your AI-Native Investor Loop"},
                {"name": "public_artifact_families", "value": "WKAP Radar Feed; WoW - Worth Watching Workout"},
                {"name": "radar_archive_url", "value": radar_archive_url()},
                {"name": "wow_ledger_url", "value": f"{settings.WKAP_BASE_URL}/investors/"},
            ],
            radar_count=RadarIssue.objects.count(),
            wow_count=DailyWoWPacket.objects.count(),
            latest_radar=latest_radar,
            latest_wow=latest_wow,
        ),
    )


def submit_to_ledger(request):
    canonical_url = f"{settings.WKAP_BASE_URL}/submit-to-wkap-ledger.html"
    spec = current_spec()
    packet_spec_url = "https://wkap.ai/specs/wow-packet-latest.md"
    wow_skill_url = "https://wkap.ai/skills/wkap-wow-skill-latest.md"
    codex_skill_url = "https://wkap.ai/skills/wkap-wow-codex/SKILL.md"
    return render(
        request,
        "publishing/submit_to_ledger.html",
        _page_context(
            title="Start Daily WoW Training - WKAP.ai",
            description="Set up a Daily WoW Training feedback loop for you and your agent, with private WoW memory and public ledgered packets.",
            canonical_url=canonical_url,
            page_type="investor_log_setup",
            agent_facts=[
                {"name": "page_purpose", "value": "Set up Daily WoW Training for an investor and agent feedback loop."},
                {"name": "submission_email", "value": settings.WKAP_INBOUND_EMAIL},
                {"name": "recommended_cadence", "value": "once per market day"},
                {"name": "packet_type", "value": "Daily WoW Packet"},
                {"name": "max_reading_items", "value": str(spec.get("schema_data", {}).get("reading_log_rules", {}).get("max_items", 10))},
                {"name": "wow_packet_spec_latest_url", "value": packet_spec_url},
                {"name": "wkap_wow_skill_latest_url", "value": wow_skill_url},
                {"name": "wkap_wow_codex_skill_url", "value": codex_skill_url},
                {"name": "private_journal_required", "value": "true"},
                {"name": "public_submission_requires_user_approval", "value": "true"},
                {"name": "user_decision_is_submission_approval", "value": "true"},
                {"name": "required_wow_options", "value": str(spec.get("schema_data", {}).get("suggested_wow_rules", {}).get("required_count", 3))},
                {"name": "current_submission_format", "value": spec["format_version"]},
                {"name": "protocol_reference_version", "value": "v0.1"},
                {"name": "canonical_url", "value": canonical_url},
            ],
            crawl_links=[
                {"rel": "protocol", "href": "/specs/wow-packet-latest.md", "label": "wow-packet-spec"},
                {"rel": "help", "href": "/skills/wkap-wow-skill-latest.md", "label": "wkap-wow-skill"},
                {"rel": "alternate", "href": "/skills/wkap-wow-codex/SKILL.md", "label": "wkap-wow-codex-skill"},
            ],
            json_ld={
                "@context": "https://schema.org",
                "@type": "HowTo",
                "name": "Start Daily WoW Training",
                "url": canonical_url,
                "description": "Set up the feedback loop for Daily WoW Training and public WKAP Ledger submission.",
                "step": [
                    {"@type": "HowToStep", "name": "Copy the WKAP WoW setup message"},
                    {"@type": "HowToStep", "name": "Paste it into your agent"},
                    {"@type": "HowToStep", "name": "Let the agent install or adapt the WKAP WoW Skill"},
                    {"@type": "HowToStep", "name": "Select WoW 1, 2, 3, or pass with the required reason"},
                ],
            },
        ),
    )


def markdown_resource(request, resource_key: str):
    relative_path = MARKDOWN_RESOURCES.get(resource_key)
    if not relative_path:
        raise Http404("Unknown Markdown resource.")
    path = settings.BASE_DIR / relative_path
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/markdown; charset=utf-8")


def markdown_latest_redirect(request, target_path: str):
    return HttpResponseRedirect(target_path)


def radar_archive(request):
    issues = RadarIssue.objects.order_by("-market_date")
    return render(
        request,
        "publishing/radar/archive.html",
        _page_context(
            title="WKAP Radar Feed Archive",
            description="Archive of WKAP Radar Feed pages, each published as canonical HTML with ledger proof fields for agent search and validation.",
            canonical_url=radar_archive_url(),
            page_type="radar_archive",
            agent_facts=[
                {"name": "artifact_family", "value": "WKAP Radar Feed"},
                {"name": "archive_url", "value": radar_archive_url()},
                {"name": "public_format", "value": "text/html"},
                {"name": "feed_count", "value": str(issues.count())},
            ],
            json_ld={
                "@context": "https://schema.org",
                "@type": "CollectionPage",
                "name": "WKAP Radar Feed Archive",
                "url": radar_archive_url(),
                "hasPart": [
                    {"@type": "Article", "name": f"WKAP Radar Feed {issue.market_date}", "url": radar_issue_url(issue.market_date)}
                    for issue in issues
                ],
            },
            issues=issues,
        ),
    )


def radar_issue(request, market_date):
    issue = get_object_or_404(RadarIssue, market_date=market_date)
    return render(
        request,
        "publishing/radar/issue.html",
        _page_context(
            title=f"WKAP Radar Feed {issue.market_date} - {issue.title}",
            description=f"WKAP Radar Feed for {issue.market_date}: {issue.title}. Includes canonical URL, content SHA256, GitHub ledger URL, manifest, and OpenTimestamp status.",
            canonical_url=issue.canonical_url or radar_issue_url(issue.market_date),
            page_type="radar_issue",
            agent_facts=_artifact_facts(issue, "radar") + [{"name": "title", "value": issue.title}],
            json_ld=_artifact_json_ld(issue, "WKAP Radar Feed", issue.title, issue.body_text),
            issue=issue,
        ),
    )


def investor_archive(request):
    investors = (
        Investor.objects.filter(wows__isnull=False)
        .annotate(latest_wow_created_at=Max("wows__created_at"))
        .order_by("-latest_wow_created_at", "-id")
    )
    submissions = DailyWoWPacket.objects.select_related("investor").order_by("-created_at", "-id")
    return render(
        request,
        "publishing/investors/archive.html",
        _page_context(
            title="WKAP WoW Ledger",
            description="Archive of investor-submitted Daily WoW Packet pages. Investor emails are private; public pages expose investor ID, market date, reading log, suggested WoWs, selected/pass details, and proof fields.",
            canonical_url=f"{settings.WKAP_BASE_URL}/investors/",
            page_type="wow_ledger",
            crawl_links=[
                {"rel": "archives", "href": "/investors/", "label": "wow-ledger"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
            agent_facts=[
                {"name": "artifact_family", "value": "WoW - Worth Watching Workout"},
                {"name": "archive_url", "value": f"{settings.WKAP_BASE_URL}/investors/"},
                {"name": "investor_count", "value": str(investors.count())},
                {"name": "submission_count", "value": str(submissions.count())},
                {"name": "privacy_rule", "value": "Investor email addresses are never published."},
            ],
            json_ld={
                "@context": "https://schema.org",
                "@type": "CollectionPage",
                "name": "WKAP WoW Ledger",
                "url": f"{settings.WKAP_BASE_URL}/investors/",
                "hasPart": [
                    {
                        "@type": "Article",
                        "name": f"WKAP WoW {submission.investor.public_label} {submission.market_date}",
                        "url": wow_url(submission.investor.investor_id, submission.market_date),
                    }
                    for submission in submissions
                ],
            },
            investors=investors,
            submissions=submissions,
        ),
    )


def investor_home(request, investor_id):
    investor = get_object_or_404(Investor, investor_id=investor_id)
    submissions = investor.wows.order_by("-created_at", "-id")
    return render(
        request,
        "publishing/investors/home.html",
        _page_context(
            title=f"WKAP Investor {investor.public_label}",
            description=f"Public WKAP investor page for {investor.public_label}. Lists WoW submissions without exposing private email.",
            canonical_url=investor_home_url(investor.investor_id),
            page_type="investor_home",
            crawl_links=[
                {"rel": "archives", "href": investor_wows_url(investor.investor_id), "label": "investor-wow-archive"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
            agent_facts=[
                {"name": "investor_id", "value": investor.investor_id},
                {"name": "investor_display_name", "value": investor.display_name},
                {"name": "investor_status", "value": investor.status},
                {"name": "private_email_published", "value": "false"},
                {"name": "wow_archive_url", "value": investor_wows_url(investor.investor_id)},
                {"name": "submission_count", "value": str(submissions.count())},
            ],
            investor=investor,
            submissions=submissions,
        ),
    )


def investor_wows(request, investor_id):
    investor = get_object_or_404(Investor, investor_id=investor_id)
    submissions = investor.wows.order_by("-created_at", "-id")
    return render(
        request,
        "publishing/investors/wows.html",
        _page_context(
            title=f"WKAP Investor {investor.public_label} WoW Archive",
            description=f"WoW - Worth Watching Workout archive for WKAP investor {investor.public_label}.",
            canonical_url=investor_wows_url(investor.investor_id),
            page_type="investor_wows",
            crawl_links=[
                {"rel": "up", "href": investor_home_url(investor.investor_id), "label": "investor-home"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
            agent_facts=[
                {"name": "artifact_family", "value": "WoW - Worth Watching Workout"},
                {"name": "investor_id", "value": investor.investor_id},
                {"name": "investor_display_name", "value": investor.display_name},
                {"name": "archive_url", "value": investor_wows_url(investor.investor_id)},
                {"name": "submission_count", "value": str(submissions.count())},
            ],
            investor=investor,
            submissions=submissions,
        ),
    )


def wow_submission(request, investor_id, market_date):
    submission = get_object_or_404(
        DailyWoWPacket.objects.select_related("investor", "source_email"),
        investor__investor_id=investor_id,
        market_date=market_date,
    )
    selected_wow = submission.suggested_wows.filter(wow_id=submission.selected_wow_id).first() or submission.suggested_wows.first()
    agent_summary = _wow_agent_summary(submission, selected_wow)
    title_context = selected_wow.ticker_or_theme if selected_wow else "Daily WoW Packet"
    description_context = selected_wow.whats_worth_watching if selected_wow else "Daily WoW Packet"
    subject_display_name = submission.investor.display_name or "unknown subject name"
    received_at_et = submission.source_email.received_at.astimezone(ET_ZONE)
    received_at_et_display = received_at_et.strftime("%Y-%m-%d %H:%M ET")
    return render(
        request,
        "publishing/investors/wow.html",
        _page_context(
            title=f"WKAP WoW {submission.investor.public_label} {submission.market_date} - {title_context}",
            description=f"Investor Daily WoW Packet for {submission.market_date}. Includes reading log, agent-suggested WoWs, selected/pass details, raw email hash, and ledger proof fields.",
            canonical_url=submission.canonical_url or wow_url(submission.investor.investor_id, submission.market_date),
            page_type="wow_submission",
            crawl_links=[
                {"rel": "up", "href": investor_wows_url(submission.investor.investor_id), "label": "investor-wow-archive"},
                {"rel": "archives", "href": f"{settings.WKAP_BASE_URL}/investors/", "label": "wow-ledger"},
                {"rel": "alternate", "href": "/sitemap.xml", "label": "sitemap"},
            ],
            agent_facts=_artifact_facts(submission, "wow")
            + [
                {"name": "investor_id", "value": submission.investor.investor_id},
                {"name": "investor_label", "value": submission.investor.public_label},
                {"name": "investor_display_name", "value": submission.investor.display_name},
                {"name": "subject_line_display_name", "value": subject_display_name},
                {"name": "submission_channel", "value": "email"},
                {"name": "received_at_et", "value": received_at_et_display},
                {"name": "format_version", "value": submission.format_version},
                {"name": "packet_id", "value": submission.packet_id},
                {"name": "author_id", "value": submission.author_id},
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
                {"name": "selection_status", "value": agent_summary["selection_status"]},
                {"name": "selected_wow_id", "value": submission.public_selected_wow_id},
                {"name": "packet_selected_wow_id", "value": submission.selected_wow_id},
                {"name": "selected_theme", "value": agent_summary["selected_theme"]},
                {"name": "themes", "value": agent_summary["themes"]},
                {"name": "tickers_json", "value": agent_summary["tickers_json"]},
                {"name": "themes_json", "value": agent_summary["themes_json"]},
                {"name": "source_urls", "value": agent_summary["source_urls"]},
                {"name": "source_urls_json", "value": agent_summary["source_urls_json"]},
                {"name": "source_types", "value": agent_summary["source_types"]},
                {"name": "source_types_json", "value": agent_summary["source_types_json"]},
                {"name": "reading_origins", "value": agent_summary["reading_origins"]},
                {"name": "reading_origins_json", "value": agent_summary["reading_origins_json"]},
                {"name": "evidence_to_watch", "value": agent_summary["evidence_to_watch"]},
                {"name": "evidence_to_watch_json", "value": agent_summary["evidence_to_watch_json"]},
                {"name": "all_evidence_to_watch", "value": agent_summary["all_evidence_to_watch"]},
                {"name": "all_evidence_to_watch_json", "value": agent_summary["all_evidence_to_watch_json"]},
            ]
            + _optional_facts(
                [
                    ("reason_for_pass", _wow_pass_fact_value(submission, submission.why_pass)),
                    ("closest_rejected_idea", _wow_pass_fact_value(submission, submission.closest_rejected_idea)),
                    ("missing_evidence", _wow_pass_fact_value(submission, submission.missing_evidence)),
                ]
            )
            + [
                {"name": "raw_email_sha256", "value": submission.raw_email_sha256},
                {"name": "raw_email_github_url", "value": submission.raw_email_github_url},
                {"name": "raw_packet_json", "value": json.dumps(submission.raw_packet_json, ensure_ascii=False, sort_keys=True)},
                {"name": "wow_items_json", "value": json.dumps(submission.wow_items_json, ensure_ascii=False, sort_keys=True)},
                {"name": "disclaimer", "value": WOW_DISCLAIMER},
            ],
            json_ld=_artifact_json_ld(
                submission,
                "Daily WoW Packet",
                f"WKAP WoW {submission.investor.public_label} {submission.market_date}: {title_context}",
                description_context,
                extra={
                    "author": {
                        "@type": "Person",
                        "identifier": submission.investor.investor_id,
                        "name": submission.investor.public_label,
                    },
                    "about": title_context,
                    "keywords": [*agent_summary["tickers"], *agent_summary["themes_array"]],
                    "additionalType": agent_summary["selection_status"],
                },
            ),
            submission=submission,
            selected_wow=selected_wow,
            selection_status=agent_summary["selection_status"],
            subject_display_name=subject_display_name,
            received_at_et_display=received_at_et_display,
            disclaimer=WOW_DISCLAIMER,
        ),
    )


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        f"Sitemap: {settings.WKAP_BASE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    urls = [
        (f"{settings.WKAP_BASE_URL}/", "daily"),
        (f"{settings.WKAP_BASE_URL}/submit-to-wkap-ledger.html", "weekly"),
        (radar_archive_url(), "daily"),
        (f"{settings.WKAP_BASE_URL}/investors/", "daily"),
    ]
    urls.extend((radar_issue_url(issue.market_date), "weekly") for issue in RadarIssue.objects.order_by("-market_date"))
    investors = (
        Investor.objects.filter(wows__isnull=False)
        .annotate(latest_wow_created_at=Max("wows__created_at"))
        .order_by("-latest_wow_created_at", "-id")
    )
    for investor in investors:
        urls.append((investor_home_url(investor.investor_id), "weekly"))
        urls.append((investor_wows_url(investor.investor_id), "weekly"))
    urls.extend(
        (wow_url(submission.investor.investor_id, submission.market_date), "weekly")
        for submission in DailyWoWPacket.objects.select_related("investor").order_by("-created_at", "-id")
    )
    body = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            *[
                f"  <url><loc>{escape(url)}</loc><changefreq>{changefreq}</changefreq></url>"
                for url, changefreq in urls
            ],
            "</urlset>",
            "",
        ]
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")
