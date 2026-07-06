"""Django settings for WKAP V0."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,wkap.ai,www.wkap.ai").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "ingestion",
    "ledger",
    "publishing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wkap_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wkap_project.wsgi.application"


def database_config() -> dict[str, object]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use postgres:// or postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or "",
        "OPTIONS": {"sslmode": os.getenv("DATABASE_SSLMODE", "prefer")},
    }


DATABASES = {"default": database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

WKAP_BASE_URL = os.getenv("WKAP_BASE_URL", "https://wkap.ai").rstrip("/")
WKAP_PUBLIC_SITE_ROOT = Path(os.getenv("WKAP_PUBLIC_SITE_ROOT", BASE_DIR / "public_site"))
WKAP_LEDGER_REPO_PATH = os.getenv("WKAP_LEDGER_REPO_PATH", "")
WKAP_LEDGER_REPO_URL = os.getenv("WKAP_LEDGER_REPO_URL", "")
WKAP_LEDGER_GITHUB_BASE_URL = os.getenv("WKAP_LEDGER_GITHUB_BASE_URL", "")
WKAP_LEDGER_BRANCH = os.getenv("WKAP_LEDGER_BRANCH", "main")
WKAP_GIT_EXECUTABLE = os.getenv("WKAP_GIT_EXECUTABLE", "git")
WKAP_ENVIRONMENT = os.getenv("WKAP_ENVIRONMENT", "local")
WKAP_RADAR_AUTHORIZED_SENDERS = {
    email.strip().lower()
    for email in os.getenv(
        "WKAP_RADAR_AUTHORIZED_SENDERS",
        "playinc@gmail.com,minxixi0103@gmail.com",
    ).split(",")
    if email.strip()
}
WKAP_INBOUND_EMAIL = os.getenv("WKAP_INBOUND_EMAIL", "ledger@wkap.ai")
WKAP_LOCAL_INBOUND_EMAIL = os.getenv("WKAP_LOCAL_INBOUND_EMAIL", "playinc@gmail.com")
WKAP_GMAIL_ACCOUNT = os.getenv(
    "WKAP_GMAIL_ACCOUNT",
    WKAP_LOCAL_INBOUND_EMAIL if WKAP_ENVIRONMENT == "local" else WKAP_INBOUND_EMAIL,
)
WKAP_RECEIPT_FROM_EMAIL = os.getenv("WKAP_RECEIPT_FROM_EMAIL", WKAP_GMAIL_ACCOUNT)
WKAP_SEND_RECEIPTS = os.getenv("WKAP_SEND_RECEIPTS", "false").lower() in {"1", "true", "yes", "on"}
WKAP_GMAIL_TOKEN_FILE = os.getenv("WKAP_GMAIL_TOKEN_FILE", "")
WKAP_GMAIL_CREDENTIALS_FILE = os.getenv("WKAP_GMAIL_CREDENTIALS_FILE", "")
WKAP_GMAIL_TOKEN_JSON_BASE64 = os.getenv("WKAP_GMAIL_TOKEN_JSON_BASE64", "")
WKAP_CLOUDFLARE_INGEST_SECRET = os.getenv("WKAP_CLOUDFLARE_INGEST_SECRET", "")
WKAP_CLOUDFLARE_ZONE_ID = os.getenv("WKAP_CLOUDFLARE_ZONE_ID", "")
WKAP_CLOUDFLARE_API_TOKEN = os.getenv("WKAP_CLOUDFLARE_API_TOKEN", "")
WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED = os.getenv(
    "WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED",
    "true" if WKAP_ENVIRONMENT == "production" else "false",
).lower() in {"1", "true", "yes", "on"}
WKAP_CACHE_WARMUP_ENABLED = os.getenv(
    "WKAP_CACHE_WARMUP_ENABLED",
    "true" if WKAP_ENVIRONMENT == "production" else "false",
).lower() in {"1", "true", "yes", "on"}
WKAP_CACHE_WARMUP_TIMEOUT_SECONDS = int(os.getenv("WKAP_CACHE_WARMUP_TIMEOUT_SECONDS", "15"))
WKAP_OPENTIMESTAMP_ENABLED = os.getenv("WKAP_OPENTIMESTAMP_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WKAP_OPENTIMESTAMP_COMMAND = os.getenv("WKAP_OPENTIMESTAMP_COMMAND", "ots")
