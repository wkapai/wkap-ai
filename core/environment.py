from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings


def environment_errors() -> list[str]:
    errors: list[str] = []
    env = settings.WKAP_ENVIRONMENT
    if env not in {"local", "production", "staging"}:
        errors.append("WKAP_ENVIRONMENT must be local, staging, or production.")

    if env == "production":
        if settings.DEBUG:
            errors.append("DEBUG must be false in production.")
        if settings.SECRET_KEY == "dev-only-change-me":
            errors.append("SECRET_KEY must be set in production.")
        if not os.getenv("DATABASE_URL"):
            errors.append("DATABASE_URL must be set in production.")
        if not settings.WKAP_BASE_URL.startswith("https://"):
            errors.append("WKAP_BASE_URL must use https in production.")
        if not settings.WKAP_LEDGER_REPO_PATH:
            errors.append("WKAP_LEDGER_REPO_PATH must be set in production.")
        if not settings.WKAP_LEDGER_REPO_URL:
            errors.append("WKAP_LEDGER_REPO_URL must be set in production.")
        if not settings.WKAP_LEDGER_GITHUB_BASE_URL:
            errors.append("WKAP_LEDGER_GITHUB_BASE_URL must be set in production.")
        if not settings.WKAP_GMAIL_CREDENTIALS_FILE:
            errors.append("WKAP_GMAIL_CREDENTIALS_FILE must be set in production.")
        if not settings.WKAP_GMAIL_TOKEN_FILE:
            errors.append("WKAP_GMAIL_TOKEN_FILE must be set in production.")
        if not settings.WKAP_CLOUDFLARE_INGEST_SECRET:
            errors.append("WKAP_CLOUDFLARE_INGEST_SECRET must be set in production.")

    for path_setting in ("WKAP_PUBLIC_SITE_ROOT",):
        path = Path(getattr(settings, path_setting))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(f"{path_setting} is not writable: {exc}")

    return errors
