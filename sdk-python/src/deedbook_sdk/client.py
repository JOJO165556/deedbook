"""Client d'ingestion deedbook côté application (Python)."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger("deedbook_sdk")

_GLOBAL_DISABLED = False


def disable() -> None:
    """Désactive le SDK globalement (ex. feature flag / kill-switch)."""
    global _GLOBAL_DISABLED
    _GLOBAL_DISABLED = True


def enable() -> None:
    """Réactive le SDK globalement."""
    global _GLOBAL_DISABLED
    _GLOBAL_DISABLED = False


class AuditClient:
    """Client d'envoi d'événements vers le moteur deedbook.

    Contrat : zéro plantage hôte - aucune exception ne remonte vers l'application hôte.
    """

    def __init__(
        self,
        engine_url: str,
        api_token: str,
        *,
        app_name: str = "app",
        http_client: httpx.Client | None = None,
        batch_max_events: int = 100,
        send_timeout: float = 2.0,
    ) -> None:
        self.engine_url = engine_url.rstrip("/")
        self.api_token = api_token
        self.app_name = app_name
        self.batch_max_events = batch_max_events
        self._disabled = False
        self._buffer: list[dict[str, Any]] = []
        self._http = http_client or httpx.Client(timeout=send_timeout)

    @property
    def is_disabled(self) -> bool:
        """Indique si le client ou le module global est désactivé."""
        return self._disabled or _GLOBAL_DISABLED

    @property
    def pending_count(self) -> int:
        """Nombre d'événements actuellement en attente dans la file locale."""
        return len(self._buffer)

    def disable(self) -> None:
        """Désactive cette instance de client."""
        self._disabled = True

    def enable(self) -> None:
        """Réactive cette instance de client."""
        self._disabled = False

    def emit(self, event: dict[str, Any] | Any) -> None:
        """Enfile un événement d'audit.

        Garantie : ne lève JAMAIS d'exception vers l'application hôte.
        """
        try:
            if self.is_disabled:
                return

            if not isinstance(event, dict):
                logger.warning("deedbook_sdk: événement ignoré (doit être un dictionnaire)")
                return

            # Complétion transparente des champs d'identification s'ils manquent
            ev = dict(event)
            if "schema_version" not in ev:
                ev["schema_version"] = "1.0"
            if "event_id" not in ev:
                ev["event_id"] = str(uuid.uuid4())
            if "idempotency_key" not in ev:
                ev["idempotency_key"] = f"idemp_{uuid.uuid4().hex[:16]}"
            if "occurred_at" not in ev:
                ev["occurred_at"] = dt.datetime.now(dt.UTC).isoformat()

            origin = dict(ev.get("origin") or {})
            if "app" not in origin:
                origin["app"] = self.app_name
            ev["origin"] = origin

            self._buffer.append(ev)

            if len(self._buffer) >= self.batch_max_events:
                self.flush()

        except Exception as exc:
            logger.error("deedbook_sdk.emit a intercepté une erreur : %s", exc)

    def flush(self) -> None:
        """Envoie immédiatement tous les événements en attente vers le moteur.

        Garantie : ne lève JAMAIS d'exception vers l'application hôte.
        """
        try:
            if self.is_disabled or not self._buffer:
                return

            events_to_send = list(self._buffer)
            batch = {
                "schema_version": "1.0",
                "batch_id": str(uuid.uuid4()),
                "app": self.app_name,
                "sent_at": dt.datetime.now(dt.UTC).isoformat(),
                "events": events_to_send,
            }

            url = f"{self.engine_url}/v1/events"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }

            response = self._http.post(url, json=batch, headers=headers)
            if response.status_code == 202:
                # Lot accepté par le moteur deedbook
                self._buffer = self._buffer[len(events_to_send) :]
            else:
                logger.warning(
                    "deedbook_sdk: rejet du lot par le moteur HTTP %d: %s",
                    response.status_code,
                    response.text,
                )
        except Exception as exc:
            logger.warning("deedbook_sdk: échec d'envoi du lot : %s", exc)
