from __future__ import annotations

from django.conf import settings


def radar_archive_url() -> str:
    return f"{settings.WKAP_BASE_URL}/radar/"


def radar_issue_path(market_date) -> str:
    return f"radar/wkap-radar-feed-{market_date}.html"


def radar_issue_url(market_date) -> str:
    return f"{settings.WKAP_BASE_URL}/{radar_issue_path(market_date)}"


def creative_archive_url() -> str:
    return f"{settings.WKAP_BASE_URL}/creative/"


def edition_archive_url() -> str:
    return f"{settings.WKAP_BASE_URL}/editions/"


def creative_issue_path(market_date, edition_version: int) -> str:
    return f"creative/wkap-creative-edition-{market_date}-v{edition_version}.html"


def creative_issue_url(market_date, edition_version: int) -> str:
    return f"{settings.WKAP_BASE_URL}/{creative_issue_path(market_date, edition_version)}"


def edition_issue_path(market_date, edition_version: int) -> str:
    return f"editions/wkap-edition-{market_date}-v{edition_version}.html"


def edition_issue_url(market_date, edition_version: int) -> str:
    return f"{settings.WKAP_BASE_URL}/{edition_issue_path(market_date, edition_version)}"


def edition_json_path(market_date, edition_version: int) -> str:
    return f"editions/data/wkap-edition-{market_date}-v{edition_version}.json"


def edition_json_url(market_date, edition_version: int) -> str:
    return f"{settings.WKAP_BASE_URL}/{edition_json_path(market_date, edition_version)}"


def creative_image_path(market_date, edition_version: int, extension: str) -> str:
    safe_extension = extension.lower().lstrip(".")
    return f"creative/assets/wkap-cover-{market_date}-v{edition_version}.{safe_extension}"


def creative_image_url(market_date, edition_version: int, extension: str) -> str:
    return f"{settings.WKAP_BASE_URL}/{creative_image_path(market_date, edition_version, extension)}"


def radar_cover_image_path(market_date, extension: str) -> str:
    safe_extension = extension.lower().lstrip(".")
    return f"radar/assets/wkap-cover-{market_date}.{safe_extension}"


def radar_cover_image_url(market_date, extension: str) -> str:
    return f"{settings.WKAP_BASE_URL}/{radar_cover_image_path(market_date, extension)}"


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
