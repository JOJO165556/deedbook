"""Schémas Pydantic pour les événements et lots d'audit"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Limites techniques spécifiées dans docs/specification-evenement-audit.md
MAX_PAYLOAD_BYTES = 8192  # 8 Ko max pour change.before / change.after
MAX_PAYLOAD_DEPTH = 4  # Profondeur JSON max pour change.before / change.after
MAX_MESSAGE_CHARS = 500  # Troncature de result.message
MAX_CLOCK_SKEW_SECONDS = 300  # Tolérance d'horloge 5 min dans le futur


class StrictBase(BaseModel):
    """Modèle de base interdisant strictement tout champ inconnu."""

    model_config = ConfigDict(extra="forbid")


class Actor(StrictBase):
    """Acteur ayant initié l'événement (spec §2.3)."""

    type: Literal["human", "service", "agent", "system"]
    end_user: str | None = None
    role: str | None = None


class Origin(StrictBase):
    """Contexte d'origine de l'événement applicatif (spec §2.3)."""

    app: str = Field(min_length=1, max_length=64)
    component: str | None = None
    ip: str | None = None
    session_id: str | None = None
    request_id: str | None = None


class Resource(StrictBase):
    """Ressource ciblée par l'action (spec §2.5)."""

    type: Literal["table", "record", "view", "function", "other"] | None = None
    name: str | None = None
    id: str | None = None


class Result(StrictBase):
    """Résultat de l'action exécutée (spec §2.6)."""

    status: Literal["success", "denied", "error"]
    code: str | None = None
    message: str | None = None

    @field_validator("message", mode="after")
    @classmethod
    def truncate_message(cls, v: str | None) -> str | None:
        if v and len(v) > MAX_MESSAGE_CHARS:
            return v[:MAX_MESSAGE_CHARS]
        return v


def _calculate_depth(val: Any, current_depth: int = 1) -> int:
    """Calcule récursivement la profondeur maximale d'un objet JSON imbriqué."""
    if not isinstance(val, (dict, list)):
        return current_depth
    if current_depth > MAX_PAYLOAD_DEPTH:
        return current_depth
    max_d = current_depth
    items = val.values() if isinstance(val, dict) else val
    for item in items:
        if isinstance(item, (dict, list)):
            d = _calculate_depth(item, current_depth + 1)
            if d > max_d:
                max_d = d
    return max_d


class Change(StrictBase):
    """Données avant / après modification (spec §2.7)."""

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    @field_validator("before", "after", mode="after")
    @classmethod
    def validate_change_payload(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        if _calculate_depth(v) > MAX_PAYLOAD_DEPTH:
            raise ValueError(f"profondeur maximale de {MAX_PAYLOAD_DEPTH} dépassée")
        serialized = json.dumps(v)
        if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"taille maximale de {MAX_PAYLOAD_BYTES} octets dépassée")
        return v


class Integrity(StrictBase):
    """Champs d'intégrité et chaînage cryptographique (spec V1, réservé en V0)."""

    seq: int | None = None
    event_hash: str | None = None
    prev_hash: str | None = None


class AuditEvent(StrictBase):
    """Événement unitaire d'audit (spec §2)."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=128)
    occurred_at: dt.datetime

    actor: Actor
    service_account: str | None = None
    origin: Origin

    correlation_id: str | None = None

    action: Literal[
        "read",
        "create",
        "update",
        "delete",
        "export",
        "login",
        "logout",
        "authz_change",
        "config_change",
    ]
    resource: Resource | None = None
    result: Result

    change: Change | None = None
    integrity: Integrity | None = None

    @field_validator("occurred_at", mode="after")
    @classmethod
    def validate_clock_skew(cls, v: dt.datetime) -> dt.datetime:
        now = dt.datetime.now(dt.UTC)
        target = v if v.tzinfo is not None else v.replace(tzinfo=dt.UTC)
        if target > now + dt.timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            raise ValueError("horodatage dans le futur (> 5 min)")
        return v

    @model_validator(mode="after")
    def validate_business_rules(self) -> AuditEvent:
        # Règle acteur / compte technique
        if self.actor.type != "human" and not self.service_account:
            raise ValueError("service_account requis lorsque actor.type n'est pas human")

        # Règle action / changement selon le type de ressource
        res_type = self.resource.type if self.resource else None
        is_data_res = res_type in ("record", "table")
        ch = self.change

        if self.action in ("read", "export", "login"):
            if ch is not None and (ch.before is not None or ch.after is not None):
                raise ValueError(f"change interdit pour l'action {self.action}")

        elif self.action == "create" and is_data_res:
            if not ch or ch.after is None:
                raise ValueError("change.after est obligatoire pour action create sur record/table")
            if ch.before is not None:
                raise ValueError("change.before est interdit pour action create")

        elif self.action == "update" and is_data_res:
            if not ch or ch.before is None or ch.after is None:
                raise ValueError(
                    "change.before et change.after sont obligatoires "
                    "pour action update sur record/table"
                )

        elif self.action == "delete" and is_data_res:
            if not ch or ch.before is None:
                raise ValueError(
                    "change.before est obligatoire pour action delete sur record/table"
                )
            if ch.after is not None:
                raise ValueError("change.after est interdit pour action delete")

        return self


class AuditBatch(StrictBase):
    """Lot d'événements d'audit envoyé au moteur (spec §4)."""

    schema_version: Literal["1.0"] = "1.0"
    batch_id: UUID
    app: str = Field(min_length=1, max_length=64)
    sent_at: dt.datetime | None = None
    events: list[AuditEvent]


class BatchResponse(StrictBase):
    """Réponse d'ingestion retournée par le moteur (spec §4)."""

    batch_id: UUID
    received_count: int
    untrusted_app: bool = False
