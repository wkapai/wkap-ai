from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from hmac import compare_digest

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.cli import CommandResult
from core.events import log_event
from ingestion.services import ingest_cloudflare_email_payload, process_raw_email_for_publish
from ledger.models import LedgerEvent


@csrf_exempt
@require_POST
def cloudflare_email_ingest(request: HttpRequest) -> JsonResponse:
    run_id = uuid.uuid4()
    if not _valid_worker_secret(request):
        log_event(
            "cloudflare_email_auth_failed",
            run_id=run_id,
            status=LedgerEvent.Status.REJECTED,
            error_code="invalid_worker_secret",
            error_message="Cloudflare Email Worker shared secret was missing or invalid.",
            details={"remote_addr": request.META.get("REMOTE_ADDR", "")},
        )
        return JsonResponse(
            {
                "command": "cloudflare-email-ingest",
                "run_id": str(run_id),
                "status": "failed",
                "errors": ["invalid_worker_secret"],
                "next_action": "check WKAP_CLOUDFLARE_INGEST_SECRET",
            },
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
        raw_email = ingest_cloudflare_email_payload(payload, run_id=run_id)
        artifact = process_raw_email_for_publish(raw_email, run_id=run_id)
    except Exception as exc:
        log_event(
            "cloudflare_email_ingest_failed",
            run_id=run_id,
            status=LedgerEvent.Status.FAILED,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        return JsonResponse(
            {
                "command": "cloudflare-email-ingest",
                "run_id": str(run_id),
                "status": "failed",
                "errors": [str(exc)],
                "next_action": "inspect LedgerEvent logs and fallback Gmail copy",
            },
            status=500,
        )

    result = CommandResult.from_entity(
        command="cloudflare-email-ingest",
        run_id=str(run_id),
        status="succeeded",
        entity_type=_entity_type(artifact),
        entity=artifact,
        next_action="done",
    )
    return JsonResponse(asdict(result), status=200)


def _valid_worker_secret(request: HttpRequest) -> bool:
    expected = settings.WKAP_CLOUDFLARE_INGEST_SECRET
    provided = request.headers.get("X-WKAP-Worker-Secret", "")
    return bool(expected and provided and compare_digest(provided, expected))


def _entity_type(artifact) -> str:
    model_name = getattr(getattr(artifact, "_meta", None), "model_name", "")
    return {
        "radarissue": "radar",
        "dailywowpacket": "wow",
        "rawemail": "raw_email",
    }.get(model_name, model_name or "raw_email")
