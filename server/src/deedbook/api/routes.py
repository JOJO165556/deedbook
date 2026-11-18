"""Routes FastAPI pour l'ingestion et la consultation d'événements d'audit."""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from deedbook.api.db import (
    authenticate_app_token,
    connect_ingest,
    connect_read,
    get_event,
    insert_batch,
    search_events,
)
from deedbook.api.errors import extract_validation_errors
from deedbook.api.schemas import AuditBatch, AuditEvent, BatchResponse
from deedbook.config import get_settings, load_policy
from deedbook.masking import mask_dict

router = APIRouter(prefix="/v1", tags=["audit"])

MAX_BATCH_EVENTS = 100
MAX_BATCH_BYTES = 262144  # 256 Ko


def require_app_token(authorization: str | None = Header(None, alias="Authorization")) -> str:
    """Extrait et valide la présence d'un jeton d'ingestion Bearer."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "detail": "Jeton d'ingestion manquant ou invalide"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "detail": "Jeton d'ingestion vide"},
        )
    return token


def require_admin_token(authorization: str | None = Header(None, alias="Authorization")) -> None:
    """Vérifie le jeton d'administration en temps constant."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "detail": "Jeton d'administration manquant ou invalide",
            },
        )
    token = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    expected = settings.admin_token.get_secret_value()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "detail": "Jeton d'administration invalide"},
        )


def _prepare_events_data(
    events: list[AuditEvent],
    masking_rules: list[dict[str, Any]],
    hmac_key: bytes | None,
) -> list[dict[str, Any]]:
    """Transforme les événements Pydantic en dictionnaires en appliquant le masquage."""
    prepared: list[dict[str, Any]] = []
    for ev in events:
        res_name = ev.resource.name if ev.resource else None
        salt = str(ev.event_id)

        before = ev.change.before if ev.change else None
        after = ev.change.after if ev.change else None

        if before and masking_rules:
            before = mask_dict(
                before,
                masking_rules,
                resource_name=res_name,
                hmac_key=hmac_key,
                salt=salt,
            )
        if after and masking_rules:
            after = mask_dict(
                after,
                masking_rules,
                resource_name=res_name,
                hmac_key=hmac_key,
                salt=salt,
            )

        prepared.append(
            {
                "event_id": str(ev.event_id),
                "schema_version": ev.schema_version,
                "idempotency_key": ev.idempotency_key,
                "occurred_at": ev.occurred_at,
                "actor_end_user": ev.actor.end_user,
                "actor_type": ev.actor.type,
                "actor_role": ev.actor.role,
                "service_account": ev.service_account,
                "component": ev.origin.component,
                "ip": ev.origin.ip,
                "session_id": ev.origin.session_id,
                "request_id": ev.origin.request_id,
                "correlation_id": ev.correlation_id,
                "action": ev.action,
                "resource_type": ev.resource.type if ev.resource else None,
                "resource_name": ev.resource.name if ev.resource else None,
                "resource_id": ev.resource.id if ev.resource else None,
                "result_status": ev.result.status,
                "result_code": ev.result.code,
                "result_message": ev.result.message,
                "change_before": before,
                "change_after": after,
                "integrity_seq": ev.integrity.seq if ev.integrity else None,
                "event_hash": ev.integrity.event_hash if ev.integrity else None,
                "prev_hash": ev.integrity.prev_hash if ev.integrity else None,
            }
        )
    return prepared


async def _parse_and_validate_batch(request: Request) -> AuditBatch:
    """Lit le corps brut de la requête, vérifie les limites de taille et valide le lot."""
    body_bytes = await request.body()
    if len(body_bytes) > MAX_BATCH_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "batch_too_large",
                "detail": (
                    f"Le lot dépasse la taille maximale autorisée de {MAX_BATCH_BYTES} octets"
                ),
            },
        )

    try:
        raw_json = json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": [{"index": None, "field": "body", "reason": f"JSON invalide: {exc}"}],
            },
        ) from exc

    if not isinstance(raw_json, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": [
                    {"index": None, "field": "body", "reason": "Le lot doit être un objet JSON"}
                ],
            },
        )

    events_raw = raw_json.get("events")
    if isinstance(events_raw, list) and len(events_raw) > MAX_BATCH_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "batch_too_large",
                "detail": (
                    f"Le lot contient {len(events_raw)} événements (max {MAX_BATCH_EVENTS})"
                ),
            },
        )

    try:
        batch = AuditBatch.model_validate(raw_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": extract_validation_errors(exc),
            },
        ) from exc

    if not batch.events:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": [
                    {"index": None, "field": "events", "reason": "Le lot ne peut pas être vide"}
                ],
            },
        )

    return batch


@router.post(
    "/events",
    response_model=BatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingestion d'un lot d'événements d'audit",
)
@router.post(
    "/batches",
    response_model=BatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def ingest_events(
    request: Request,
    token: str = Depends(require_app_token),
) -> BatchResponse:
    batch = await _parse_and_validate_batch(request)
    settings = get_settings()

    try:
        with connect_ingest() as conn:
            try:
                untrusted = authenticate_app_token(conn, token, batch.app)
            except PermissionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "unauthorized", "detail": str(exc)},
                ) from exc

            policy = load_policy()
            masking_rules = policy.get("masking", {}).get("fields", [])
            hmac_key_bytes = (
                base64.b64decode(settings.hmac_key.get_secret_value())
                if settings.hmac_key
                else None
            )

            events_data = _prepare_events_data(batch.events, masking_rules, hmac_key_bytes)
            batch_data = {
                "batch_id": str(batch.batch_id),
                "app": batch.app,
                "schema_version": batch.schema_version,
                "sent_at": batch.sent_at,
                "signature": None,
            }

            signing_key_b64 = (
                settings.signing_key.get_secret_value() if settings.signing_key else None
            )

            insert_batch(
                conn,
                batch_data,
                events_data,
                untrusted_app=untrusted,
                signing_key_b64=signing_key_b64,
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "detail": f"Erreur lors de l'insertion du lot: {exc}",
            },
        ) from exc

    # Notification des modules activés (ex. webhooks sur événements critiques)
    policy_data = load_policy()
    modules_cfg = policy_data.get("modules", {})
    webhook_url = settings.webhook_url or modules_cfg.get("webhooks", {}).get("url")
    if "webhooks" in modules_cfg.get("enabled", []) and webhook_url:
        from deedbook.modules.webhooks.notifier import dispatch_webhook, is_critical_event

        for ev in events_data:
            if is_critical_event(ev):
                dispatch_webhook(webhook_url, ev, signing_key_b64)

    return BatchResponse(
        batch_id=batch.batch_id,
        received_count=len(batch.events),
        untrusted_app=untrusted,
    )


@router.get(
    "/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="Consultation d'un événement d'audit par ID",
    dependencies=[Depends(require_admin_token)],
)
async def get_event_by_id(event_id: str) -> dict[str, Any]:
    with connect_read() as conn:
        ev = get_event(conn, event_id)
        if ev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "detail": "Événement introuvable"},
            )
        return ev


@router.get(
    "/events",
    status_code=status.HTTP_200_OK,
    summary="Recherche d'événements d'audit avec filtres et pagination",
    dependencies=[Depends(require_admin_token)],
)
async def list_events(
    app: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    resource: str | None = None,
    correlation_id: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": [
                    {"index": None, "field": "limit", "reason": "limit doit être entre 1 et 100"}
                ],
            },
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "detail": [{"index": None, "field": "offset", "reason": "offset doit être >= 0"}],
            },
        )

    with connect_read() as conn:
        total, events = search_events(
            conn,
            app=app,
            action=action,
            actor=actor,
            resource=resource,
            correlation_id=correlation_id,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            offset=offset,
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": events,
        }
