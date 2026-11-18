"""Routes d'API du module webhooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/v1/modules/webhooks", tags=["modules:webhooks"])


@router.get("/status")
def webhook_status() -> dict[str, Any]:
    """Retourne l'état de fonctionnement du module webhooks."""
    return {
        "module": "webhooks",
        "status": "active",
        "description": "Notifications HTTP POST sur événements d'audit critiques",
    }
