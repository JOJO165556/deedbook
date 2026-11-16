"""Accès base de données pour l'ingestion d'événements deedbook."""

from __future__ import annotations

import hashlib
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from deedbook.chain import GENESIS_HASH, compute_event_hash, sign_batch
from deedbook.config import get_settings


def get_ingest_dsn() -> str:
    settings = get_settings()
    if settings.ingest_url:
        return settings.ingest_url.get_secret_value()
    return settings.database_url.get_secret_value()


def connect_ingest(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or get_ingest_dsn())


def get_read_dsn() -> str:
    settings = get_settings()
    if settings.read_url:
        return settings.read_url.get_secret_value()
    return settings.database_url.get_secret_value()


def connect_read(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or get_read_dsn())


def _row_to_event(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "schema_version": row[1],
        "event_id": str(row[0]),
        "idempotency_key": row[2],
        "occurred_at": row[3].isoformat() if row[3] else None,
        "received_at": row[4].isoformat() if row[4] else None,
        "batch_id": str(row[5]),
        "actor": {
            "type": row[9],
            "end_user": row[8],
            "role": row[10],
        },
        "service_account": row[11],
        "origin": {
            "app": row[6],
            "component": row[12],
            "ip": row[13],
            "session_id": row[14],
            "request_id": row[15],
        },
        "correlation_id": row[16],
        "action": row[17],
        "resource": {
            "type": row[18],
            "name": row[19],
            "id": row[20],
        }
        if any((row[18], row[19], row[20]))
        else None,
        "result": {
            "status": row[21],
            "code": row[22],
            "message": row[23],
        },
        "change": {
            "before": row[24],
            "after": row[25],
        }
        if row[24] is not None or row[25] is not None
        else None,
        "integrity": {
            "seq": row[26],
            "event_hash": row[27],
            "prev_hash": row[28],
        },
        "untrusted_app": row[7],
    }


def get_event(conn: psycopg.Connection, event_id: str) -> dict[str, Any] | None:
    """Récupère un événement d'audit par son identifiant unique."""
    row = conn.execute(
        """
        SELECT
            event_id, schema_version, idempotency_key, occurred_at, received_at,
            batch_id, app, untrusted_app,
            actor_end_user, actor_type, actor_role, service_account,
            component, ip, session_id, request_id,
            correlation_id, action,
            resource_type, resource_name, resource_id,
            result_status, result_code, result_message,
            change_before, change_after,
            integrity_seq, event_hash, prev_hash
        FROM deedbook.audit_events
        WHERE event_id = %s
        """,
        (event_id,),
    ).fetchone()

    if row is None:
        return None
    return _row_to_event(row)


def search_events(
    conn: psycopg.Connection,
    *,
    app: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    resource: str | None = None,
    correlation_id: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Recherche des événements d'audit avec filtres et pagination."""
    conditions: list[sql.Composed] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if app:
        conditions.append(sql.SQL("app = %(app)s"))
        params["app"] = app
    if action:
        conditions.append(sql.SQL("action = %(action)s"))
        params["action"] = action
    if actor:
        conditions.append(sql.SQL("actor_end_user = %(actor)s"))
        params["actor"] = actor
    if resource:
        conditions.append(sql.SQL("resource_name = %(resource)s"))
        params["resource"] = resource
    if correlation_id:
        conditions.append(sql.SQL("correlation_id = %(correlation_id)s"))
        params["correlation_id"] = correlation_id
    if from_time:
        conditions.append(sql.SQL("occurred_at >= %(from_time)s"))
        params["from_time"] = from_time
    if to_time:
        conditions.append(sql.SQL("occurred_at <= %(to_time)s"))
        params["to_time"] = to_time

    where_clause = (
        sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
    )

    count_query = sql.SQL("SELECT count(*) FROM deedbook.audit_events ") + where_clause
    total = conn.execute(count_query, params).fetchone()[0]

    select_query = (
        sql.SQL(
            """
            SELECT
                event_id, schema_version, idempotency_key, occurred_at, received_at,
                batch_id, app, untrusted_app,
                actor_end_user, actor_type, actor_role, service_account,
                component, ip, session_id, request_id,
                correlation_id, action,
                resource_type, resource_name, resource_id,
                result_status, result_code, result_message,
                change_before, change_after,
                integrity_seq, event_hash, prev_hash
            FROM deedbook.audit_events
            """
        )
        + where_clause
        + sql.SQL(
            """
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """
        )
    )
    rows = conn.execute(select_query, params).fetchall()
    events = [_row_to_event(r) for r in rows]
    return total, events


def authenticate_app_token(conn: psycopg.Connection, token: str, app_name: str) -> bool:
    """Vérifie le jeton applicatif (hash SHA-256) contre les applications enregistrées.

    Retourne True si l'application est inconnue (acceptée avec le drapeau untrusted_app),
    False si le jeton correspond à l'application active déclarée.
    Lève PermissionError si l'application enregistrée a été désactivée.
    """
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = conn.execute(
        "SELECT name, active FROM deedbook.apps WHERE token_hash = %s",
        (token_hash,),
    ).fetchone()

    if row is None:
        return True

    registered_name, is_active = row
    if not is_active:
        raise PermissionError("Application désactivée")

    if registered_name != app_name:
        return True

    return False


def insert_batch(
    conn: psycopg.Connection,
    batch_data: dict[str, Any],
    events_data: list[dict[str, Any]],
    untrusted_app: bool,
    signing_key_b64: str | None = None,
) -> int:
    """Insère un lot et ses événements de façon atomique, chaînée et idempotente."""
    with conn.transaction():
        # Verrou exclusif de l'état en O(1) pour garantir la continuité stricte sans trou
        state_row = conn.execute(
            "SELECT last_seq, last_hash FROM deedbook.chain_state WHERE id = 1 FOR UPDATE"
        ).fetchone()
        last_seq, last_hash = state_row if state_row else (0, GENESIS_HASH)

        # Chaînage séquentiel SHA-256
        for ev in events_data:
            last_seq += 1
            ev["integrity_seq"] = last_seq
            ev["prev_hash"] = last_hash
            ev["app"] = batch_data["app"]
            ev["untrusted_app"] = untrusted_app
            ev["event_hash"] = compute_event_hash(ev, last_hash, last_seq)
            last_hash = ev["event_hash"]

        # Signature numérique Ed25519 du lot
        if signing_key_b64 and events_data:
            meta = {
                "batch_id": str(batch_data["batch_id"]),
                "app": batch_data["app"],
                "schema_version": batch_data["schema_version"],
                "event_count": len(events_data),
                "first_seq": events_data[0]["integrity_seq"],
                "last_seq": events_data[-1]["integrity_seq"],
                "first_hash": events_data[0]["event_hash"],
                "last_hash": events_data[-1]["event_hash"],
            }
            batch_data["signature"] = sign_batch(meta, signing_key_b64)

        # ON CONFLICT DO NOTHING sans cible évite d'exiger le privilège SELECT
        # sur les colonnes cibles pour le rôle deedbook_ingest (principe du moindre privilège).
        res = conn.execute(
            """
            INSERT INTO deedbook.audit_batches (
                batch_id, app, schema_version, sent_at, event_count, signature
            ) VALUES (
                %(batch_id)s, %(app)s, %(schema_version)s,
                %(sent_at)s, %(event_count)s, %(signature)s
            ) ON CONFLICT DO NOTHING RETURNING 1
            """,
            {
                "batch_id": batch_data["batch_id"],
                "app": batch_data["app"],
                "schema_version": batch_data["schema_version"],
                "sent_at": batch_data.get("sent_at"),
                "event_count": len(events_data),
                "signature": batch_data.get("signature"),
            },
        ).fetchone()

        if res is not None:
            # Nouveau lot inséré : mise à jour persistante du dernier état de chaîne
            conn.execute(
                """
                UPDATE deedbook.chain_state
                SET last_seq = %s, last_hash = %s, updated_at = now()
                WHERE id = 1
                """,
                (last_seq, last_hash),
            )

            # Insertion ordonnée des événements
            for ev in events_data:
                conn.execute(
                    """
                    INSERT INTO deedbook.audit_events (
                        event_id, schema_version, idempotency_key, occurred_at, batch_id,
                        app, untrusted_app,
                        actor_end_user, actor_type, actor_role, service_account,
                        component, ip, session_id, request_id,
                        correlation_id, action,
                        resource_type, resource_name, resource_id,
                        result_status, result_code, result_message,
                        change_before, change_after,
                        integrity_seq, event_hash, prev_hash
                    ) VALUES (
                        %(event_id)s, %(schema_version)s, %(idempotency_key)s,
                        %(occurred_at)s, %(batch_id)s,
                        %(app)s, %(untrusted_app)s,
                        %(actor_end_user)s, %(actor_type)s, %(actor_role)s, %(service_account)s,
                        %(component)s, %(ip)s, %(session_id)s, %(request_id)s,
                        %(correlation_id)s, %(action)s,
                        %(resource_type)s, %(resource_name)s, %(resource_id)s,
                        %(result_status)s, %(result_code)s, %(result_message)s,
                        %(change_before)s, %(change_after)s,
                        %(integrity_seq)s, %(event_hash)s, %(prev_hash)s
                    ) ON CONFLICT DO NOTHING
                    """,
                    {
                        "event_id": ev["event_id"],
                        "schema_version": ev["schema_version"],
                        "idempotency_key": ev["idempotency_key"],
                        "occurred_at": ev["occurred_at"],
                        "batch_id": batch_data["batch_id"],
                        "app": batch_data["app"],
                        "untrusted_app": untrusted_app,
                        "actor_end_user": ev.get("actor_end_user"),
                        "actor_type": ev["actor_type"],
                        "actor_role": ev.get("actor_role"),
                        "service_account": ev.get("service_account"),
                        "component": ev.get("component"),
                        "ip": ev.get("ip"),
                        "session_id": ev.get("session_id"),
                        "request_id": ev.get("request_id"),
                        "correlation_id": ev.get("correlation_id"),
                        "action": ev["action"],
                        "resource_type": ev.get("resource_type"),
                        "resource_name": ev.get("resource_name"),
                        "resource_id": ev.get("resource_id"),
                        "result_status": ev["result_status"],
                        "result_code": ev.get("result_code"),
                        "result_message": ev.get("result_message"),
                        "change_before": (
                            Jsonb(ev["change_before"])
                            if ev.get("change_before") is not None
                            else None
                        ),
                        "change_after": (
                            Jsonb(ev["change_after"])
                            if ev.get("change_after") is not None
                            else None
                        ),
                        "integrity_seq": ev.get("integrity_seq"),
                        "event_hash": ev.get("event_hash"),
                        "prev_hash": ev.get("prev_hash"),
                    },
                )

    return len(events_data)
