"""Formatage des erreurs d'API"""

from __future__ import annotations

from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError


def extract_validation_errors(
    exc: ValidationError | RequestValidationError,
) -> list[dict[str, Any]]:
    """Transforme les erreurs Pydantic au format spec §5 (index, field, reason)."""
    details: list[dict[str, Any]] = []

    for err in exc.errors():
        loc = err.get("loc", ())
        index: int | None = None
        field_parts: list[str] = []

        # Cas 1 : erreur sur un événement d'un lot (loc = ('events', 3, 'field_name'))
        # ou dans le corps de requête (loc = ('body', 'events', 3, 'field_name'))
        loc_list = list(loc)
        if loc_list and loc_list[0] == "body":
            loc_list = loc_list[1:]

        if len(loc_list) >= 2 and loc_list[0] == "events" and isinstance(loc_list[1], int):
            index = loc_list[1]
            field_parts = [str(x) for x in loc_list[2:]]
        else:
            field_parts = [str(x) for x in loc_list]

        field_name = ".".join(field_parts) if field_parts else "batch"
        msg = err.get("msg", "erreur de validation")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]

        details.append(
            {
                "index": index,
                "field": field_name,
                "reason": msg,
            }
        )

    return details
