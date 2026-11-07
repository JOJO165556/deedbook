"""Kit d'intégration deedbook.

Contrat fondateur : **zéro plantage hôte**. Le SDK ne lève jamais
d'exception vers l'application auditée ; en cas de panne du moteur, les
événements sont mis en file locale durable et rejoués sans doublon.

Implémentation : phase V0. Voir la charte §6.3.
"""

from __future__ import annotations


class AuditClient:
    """Client d'envoi d'événements (squelette V0)."""

    def __init__(self, engine_url: str, api_token: str, *, app_name: str = "app") -> None:
        self.engine_url = engine_url.rstrip("/")
        self.api_token = api_token
        self.app_name = app_name
        self._disabled = False

    def emit(self, event: dict) -> None:
        """Enfile un événement. Ne lève jamais d'exception."""
        if self._disabled:
            return
        raise NotImplementedError("V0 — file locale + envoi par lots à implémenter")


def disable() -> None:
    """Désactive le SDK côté appelant (ex. feature flag)."""
    raise NotImplementedError("V0")


__all__ = ["AuditClient"]
