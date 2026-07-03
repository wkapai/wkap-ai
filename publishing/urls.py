from __future__ import annotations

from django.conf import settings


def radar_archive_url() -> str:
    return f"{settings.WKAP_BASE_URL}/radar/"


def radar_issue_path(market_date) -> str:
    return f"radar/wkap-radar-feed-{market_date}.html"


def radar_issue_url(market_date) -> str:
    return f"{settings.WKAP_BASE_URL}/{radar_issue_path(market_date)}"


def investor_home_path(investor_id: str) -> str:
    return f"investors/{investor_id}/index.html"


def investor_home_url(investor_id: str) -> str:
    return f"{settings.WKAP_BASE_URL}/investors/{investor_id}/"


def investor_wows_path(investor_id: str) -> str:
    return f"investors/{investor_id}/wows/index.html"


def investor_wows_url(investor_id: str) -> str:
    return f"{settings.WKAP_BASE_URL}/investors/{investor_id}/wows/"


def wow_path(investor_id: str, market_date) -> str:
    return f"investors/{investor_id}/wows/wow-{investor_id}-{market_date}.html"


def wow_url(investor_id: str, market_date) -> str:
    return f"{settings.WKAP_BASE_URL}/{wow_path(investor_id, market_date)}"


def manifest_path(entity_type: str, entity_id: int) -> str:
    return f"manifests/{entity_type}-{entity_id}.json"
