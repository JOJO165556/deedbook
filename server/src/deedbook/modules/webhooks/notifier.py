"""Logique de détection des événements critiques et émission de webhooks."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from httpx import HTTPError

logger = logging.getLogger(__name__)

CRITICAL_ACTIONS = frozenset(
    {"authz_change", "role_change", "permission_grant", "security_violation"}
)


def is_critical_event(event: dict[str, Any]) -> bool:
    """Détermine si un événement d'audit est critique et requiert une alerte."""
    status = event.get("result_status")
    if status is None and isinstance(event.get("result"), dict):
        status = event["result"].get("status")

    if status in ("denied", "failure", "violation"):
        return True

    action = event.get("action")
    if action in CRITICAL_ACTIONS:
        return True

    return False


def dispatch_webhook(
    url: str,
    event: dict[str, Any],
    signing_key_b64: str | None = None,
) -> bool:
    """Émet un webhook POST vers l'URL spécifiée.

    Silencieux sur toute erreur réseau : une panne du récepteur de webhook ne doit
    jamais interrompre l'ingestion du journal d'audit.
    """
    res = event.get("result")
    res_status = res.get("status") if isinstance(res, dict) else None
    origin = event.get("origin")
    app_name = origin.get("app") if isinstance(origin, dict) else None

    payload = {
        "event_id": event.get("event_id"),
        "action": event.get("action"),
        "result_status": event.get("result_status") or res_status,
        "app": event.get("app") or app_name,
        "data": event,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}

    if signing_key_b64:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        seed = base64.b64decode(signing_key_b64)
        priv_key = Ed25519PrivateKey.from_private_bytes(seed)
        signature = base64.b64encode(priv_key.sign(message)).decode()
        headers["X-Deedbook-Signature"] = signature

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=3)
        response.raise_for_status()
        logger.info("webhook émis avec succès vers %s (event_id=%s)", url, event.get("event_id"))
        return True
    except (OSError, HTTPError) as exc:
        logger.warning("échec émission webhook vers %s (ignoré) : %s", url, exc)
        return False
