from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CommandResult:
    command: str
    run_id: str
    status: str
    entity_type: str = ""
    entity_id: str = ""
    investor_id: str = ""
    market_date: str = ""
    canonical_url: str = ""
    content_sha256: str = ""
    raw_email_sha256: str = ""
    raw_email_github_url: str = ""
    raw_email_commit_sha: str = ""
    receipt_email_sent_at: str = ""
    receipt_email_message_id: str = ""
    receipt_email_error: str = ""
    github_file_url: str = ""
    github_commit_sha: str = ""
    manifest_url: str = ""
    ots_status: str = ""
    errors: list[str] = field(default_factory=list)
    next_action: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_entity(
        cls,
        *,
        command: str,
        run_id: str,
        status: str,
        entity_type: str = "",
        entity=None,
        errors: list[str] | None = None,
        next_action: str = "",
    ) -> "CommandResult":
        investor = getattr(entity, "investor", None)
        return cls(
            command=command,
            run_id=run_id,
            status=status,
            entity_type=entity_type,
            entity_id=str(getattr(entity, "id", "") or ""),
            investor_id=getattr(investor, "investor_id", "") or getattr(entity, "investor_id", ""),
            market_date=str(getattr(entity, "market_date", "") or ""),
            canonical_url=getattr(entity, "canonical_url", "") or "",
            content_sha256=getattr(entity, "content_sha256", "") or "",
            raw_email_sha256=getattr(entity, "raw_email_sha256", "") or "",
            raw_email_github_url=getattr(entity, "raw_email_github_url", "") or "",
            raw_email_commit_sha=getattr(entity, "raw_email_commit_sha", "") or "",
            receipt_email_sent_at=str(getattr(entity, "receipt_email_sent_at", "") or ""),
            receipt_email_message_id=getattr(entity, "receipt_email_message_id", "") or "",
            receipt_email_error=getattr(entity, "receipt_email_error", "") or "",
            github_file_url=getattr(entity, "github_file_url", "") or "",
            github_commit_sha=getattr(entity, "github_commit_sha", "") or "",
            manifest_url=getattr(entity, "manifest_url", "") or "",
            ots_status=getattr(entity, "ots_status", "") or "",
            errors=errors or [],
            next_action=next_action,
        )

    def emit(self, *, as_json: bool = False) -> None:
        payload = asdict(self)
        if as_json:
            print(json.dumps(payload, sort_keys=True))
            return

        for key, value in payload.items():
            print(f"{key}: {value}")

    def exit(self) -> None:
        sys.exit(0 if self.status in {"succeeded", "skipped"} else 1)


def error_result(command: str, run_id: str, message: str) -> CommandResult:
    return CommandResult(command=command, run_id=run_id, status="failed", errors=[message])
