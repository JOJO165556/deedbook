"""Archivage scellé des événements expirés selon la politique de rétention."""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)

_SELECT_EVENTS = """
    SELECT
        event_id, schema_version, idempotency_key,
        occurred_at, received_at, batch_id,
        app, untrusted_app,
        actor_end_user, actor_type, actor_role, service_account,
        component, ip, session_id, request_id, correlation_id,
        action, resource_type, resource_name, resource_id,
        result_status, result_code, result_message,
        change_before, change_after,
        integrity_seq, event_hash, prev_hash
    FROM deedbook.audit_events
    WHERE occurred_at < %s
    ORDER BY integrity_seq
"""

_INSERT_CHECKPOINT = """
    INSERT INTO deedbook.archive_checkpoints
        (archived_before, event_count, last_seq, last_hash, archive_path)
    VALUES (%s, %s, %s, %s, %s)
"""

_SELECT_CHECKPOINT = """
    SELECT id FROM deedbook.archive_checkpoints
    WHERE archived_before = %s
    LIMIT 1
"""

_DELETE_EVENTS = """
    DELETE FROM deedbook.audit_events
    WHERE occurred_at < %s
"""


def _serialize(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def archive_before(
    conn: psycopg.Connection,
    before: date,
    signing_key_b64: str,
    output_path: Path,
) -> int:
    """Exporte les événements antérieurs à `before` dans une archive JSON signée.

    Retourne le nombre d'événements archivés (0 si aucun, sans créer de fichier).
    Ne supprime aucune donnée : la purge est une opération distincte.
    """
    cutoff = datetime(before.year, before.month, before.day, tzinfo=UTC)
    cursor = conn.execute(_SELECT_EVENTS, (cutoff,))
    rows = cursor.fetchall()

    if not rows:
        return 0

    col_names = [desc[0] for desc in cursor.description]
    events = [
        {col: _serialize(val) for col, val in zip(col_names, row, strict=True)} for row in rows
    ]

    payload = {
        "archived_at": datetime.now(UTC).isoformat(),
        "before": before.isoformat(),
        "event_count": len(events),
        "events": events,
    }

    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    seed = base64.b64decode(signing_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = base64.b64encode(private_key.sign(message)).decode()

    archive = {**payload, "signature_ed25519": signature}
    output_path.write_text(json.dumps(archive, indent=2, ensure_ascii=False))

    logger.info("archivage : %d evenements -> %s", len(events), output_path)
    return len(events)


def save_checkpoint(
    conn: psycopg.Connection,
    archived_before: date,
    event_count: int,
    last_seq: int,
    last_hash: str,
    archive_path: str,
) -> None:
    """Enregistre un checkpoint d'archivage dans archive_checkpoints."""
    conn.execute(
        _INSERT_CHECKPOINT,
        (archived_before, event_count, last_seq, last_hash, archive_path),
    )
    logger.info("checkpoint : archived_before=%s count=%d", archived_before, event_count)


def purge_archived(conn: psycopg.Connection, before: date) -> int:
    """Supprime les événements antérieurs à `before` si un checkpoint existe.

    Lève ValueError si aucun checkpoint n'est enregistré pour cette date.
    Retourne le nombre d'événements supprimés.
    """
    row = conn.execute(_SELECT_CHECKPOINT, (before,)).fetchone()
    if row is None:
        raise ValueError(f"aucun checkpoint d'archivage pour la date {before}")

    cutoff = datetime(before.year, before.month, before.day, tzinfo=UTC)
    cursor = conn.execute(_DELETE_EVENTS, (cutoff,))
    count: int = cursor.rowcount
    logger.info("purge : %d evenements supprimes (before=%s)", count, before)
    return count
