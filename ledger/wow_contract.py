from __future__ import annotations

import json
import re
from collections.abc import Iterable


RADAR_CONTENT_SHA256_COVERS = (
    "sha256 over UTF-8 text: radar\\n{market_date}\\n{title}\\n{body_text}. "
    "It does not cover rendered HTML, proof panels, manifests, or OpenTimestamp status."
)
WOW_CONTENT_SHA256_COVERS = (
    "sha256 over UTF-8 text: wow_packet\\n{format_version}\\n{market_date}\\n{investor_id}\\n"
    "{selected_wow_id}\\n{reason_for_selection}\\n{closest_rejected_idea}\\n{why_pass}\\n"
    "{missing_evidence}\\nreading_items(item_number,source_title,source_url,reading_origin,agent_summary)\\n"
    "suggested_wows(wow_id,ticker_or_theme,whats_worth_watching,why_now,evidence_to_watch_for). "
    "It does not cover rendered HTML, proof panels, manifests, raw email text, or OpenTimestamp status."
)

_LOCAL_WOW_ID_RE = re.compile(r"^WOW-(\d{4}-\d{2}-\d{2})-(\d{3})$", re.IGNORECASE)
_PUBLIC_WOW_ID_RE = re.compile(r"^WOW-(w\d{4})-(\d{4}-\d{2}-\d{2})-(\d{3})$", re.IGNORECASE)
_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z][A-Z0-9.\-]{0,9})\b")
_BARE_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")
_TICKER_STOPWORDS = {
    "AI",
    "API",
    "AR",
    "BOM",
    "CEO",
    "CFO",
    "COPPER",
    "COWOS",
    "EV",
    "EVS",
    "GDP",
    "GPU",
    "HBM",
    "IPO",
    "LLM",
    "NAND",
    "OEM",
    "RWA",
    "SAAS",
    "US",
    "USD",
    "USDC",
}


def public_wow_id(investor_id: str, wow_id: str) -> str:
    value = (wow_id or "").strip()
    if not value or value.lower() == "none":
        return value or "none"
    if _PUBLIC_WOW_ID_RE.match(value):
        return value.upper().replace("-W", "-w")
    match = _LOCAL_WOW_ID_RE.match(value)
    if not match:
        return value
    return f"WOW-{investor_id}-{match.group(1)}-{match.group(2)}"


def local_wow_id(wow_id: str) -> str:
    value = (wow_id or "").strip()
    match = _PUBLIC_WOW_ID_RE.match(value)
    if not match:
        return value
    return f"WOW-{match.group(2)}-{match.group(3)}"


def json_array(values: Iterable[str]) -> str:
    return json.dumps(_unique(values), ensure_ascii=False, separators=(",", ":"))


def clean_packet_text(value: str) -> str:
    return "\n".join(line for line in (value or "").splitlines() if line.strip() != "---").strip()


def market_terms(values: Iterable[str]) -> dict[str, list[str]]:
    tickers: list[str] = []
    themes: list[str] = []
    for value in values:
        for token in _market_tokens(value):
            dollar_tickers = _DOLLAR_TICKER_RE.findall(token)
            for ticker in dollar_tickers:
                _append_unique(tickers, ticker.upper())
            cleaned = _DOLLAR_TICKER_RE.sub("", token).strip(" -/")
            if not cleaned:
                continue
            bare = cleaned.strip("$").upper()
            if _BARE_TICKER_RE.match(bare) and bare not in _TICKER_STOPWORDS:
                _append_unique(tickers, bare)
            else:
                _append_unique(themes, cleaned)
    return {"tickers": tickers, "themes": themes}


def _market_tokens(value: str) -> list[str]:
    return [
        token.strip()
        for token in re.split(r"[,;·\n]+", value or "")
        if token.strip()
    ]


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        _append_unique(seen, value)
    return seen


def _append_unique(values: list[str], value: str) -> None:
    clean = (value or "").strip()
    if clean and clean not in values:
        values.append(clean)
