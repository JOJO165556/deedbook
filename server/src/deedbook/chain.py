"""Chaînage cryptographique SHA-256, signature Ed25519 des lots et vérification."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import psycopg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

GENESIS_HASH = "0" * 64

# Clés canoniques normalisées pour le hachage d'un événement (spec v1.0)
CANONICAL_KEYS = (
    "schema_version",
    "event_id",
    "idempotency_key",
    "occurred_at",
    "actor_end_user",
    "actor_type",
    "actor_role",
    "service_account",
    "app",
    "untrusted_app",
    "component",
    "ip",
    "session_id",
    "request_id",
    "correlation_id",
    "action",
    "resource_type",
    "resource_name",
    "resource_id",
    "result_status",
    "result_code",
    "result_message",
    "change_before",
    "change_after",
)


def compute_event_hash(event_data: dict[str, Any], prev_hash: str, seq: int) -> str:
    """Calcule l'empreinte SHA-256 canonique d'un événement liée à l'empreinte précédente."""
    canonical: dict[str, Any] = {}
    for key in CANONICAL_KEYS:
        val = event_data.get(key)
        # Normalisation des objets horodatage en ISO 8601
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        canonical[key] = val

    canonical_json = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    hasher = hashlib.sha256()
    hasher.update(f"{prev_hash}:{seq}:".encode())
    hasher.update(canonical_json.encode("utf-8"))
    return hasher.hexdigest()


def _batch_signing_payload(meta: dict[str, Any]) -> bytes:
    return (
        f"deedbook:batch:v1:{meta['batch_id']}:{meta['app']}:{meta['schema_version']}:"
        f"{meta['event_count']}:{meta['first_seq']}:{meta['last_seq']}:"
        f"{meta['first_hash']}:{meta['last_hash']}"
    ).encode()


def sign_batch(meta: dict[str, Any], signing_key_b64: str) -> bytes:
    """Signe les métadonnées d'un lot avec la clé privée Ed25519 (64 octets)."""
    raw_seed = base64.b64decode(signing_key_b64)
    priv_key = Ed25519PrivateKey.from_private_bytes(raw_seed)
    payload = _batch_signing_payload(meta)
    return priv_key.sign(payload)


def verify_batch_signature(meta: dict[str, Any], signature: bytes, signing_key_b64: str) -> bool:
    """Vérifie la signature Ed25519 d'un lot d'audit."""
    try:
        raw_seed = base64.b64decode(signing_key_b64)
        priv_key = Ed25519PrivateKey.from_private_bytes(raw_seed)
        pub_key: Ed25519PublicKey = priv_key.public_key()
        pub_key.verify(signature, _batch_signing_payload(meta))
        return True
    except (InvalidSignature, ValueError, KeyError):
        return False


@dataclass
class VerifyReport:
    """Rapport d'audit et de vérification d'intégrité de la chaîne."""

    is_valid: bool = True
    events_verified: int = 0
    batches_verified: int = 0
    errors: list[str] = field(default_factory=list)


def verify_chain(
    conn: psycopg.Connection,
    signing_key_b64: str | None = None,
    from_seq: int | None = None,
    from_hash: str | None = None,
) -> VerifyReport:
    """Parcourt le journal d'audit et vérifie la chaîne SHA-256 et les signatures Ed25519.

    Si `from_seq` et `from_hash` sont fournis, la vérification reprend depuis ce point
    (utile après une purge conditionnée par un checkpoint d'archivage).
    """
    report = VerifyReport()

    # 1. Vérification séquentielle des événements
    if from_seq is not None:
        cursor = conn.execute(
            """
            SELECT
                integrity_seq, prev_hash, event_hash, event_id, schema_version, idempotency_key,
                occurred_at, actor_end_user, actor_type, actor_role, service_account,
                app, untrusted_app, component, ip, session_id, request_id, correlation_id,
                action, resource_type, resource_name, resource_id,
                result_status, result_code, result_message, change_before, change_after
            FROM deedbook.audit_events
            WHERE integrity_seq IS NOT NULL AND integrity_seq > %s
            ORDER BY integrity_seq ASC
            """,
            (from_seq,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT
                integrity_seq, prev_hash, event_hash, event_id, schema_version, idempotency_key,
                occurred_at, actor_end_user, actor_type, actor_role, service_account,
                app, untrusted_app, component, ip, session_id, request_id, correlation_id,
                action, resource_type, resource_name, resource_id,
                result_status, result_code, result_message, change_before, change_after
            FROM deedbook.audit_events
            WHERE integrity_seq IS NOT NULL
            ORDER BY integrity_seq ASC
            """
        )
    rows = cursor.fetchall()
    expected_seq = (from_seq + 1) if from_seq is not None else 1
    expected_prev = from_hash if from_hash is not None else GENESIS_HASH

    for row in rows:
        seq = row[0]
        stored_prev = row[1]
        stored_hash = row[2]

        ev_dict = {
            "schema_version": row[4],
            "event_id": str(row[3]),
            "idempotency_key": row[5],
            "occurred_at": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
            "actor_end_user": row[7],
            "actor_type": row[8],
            "actor_role": row[9],
            "service_account": row[10],
            "app": row[11],
            "untrusted_app": row[12],
            "component": row[13],
            "ip": row[14],
            "session_id": row[15],
            "request_id": row[16],
            "correlation_id": row[17],
            "action": row[18],
            "resource_type": row[19],
            "resource_name": row[20],
            "resource_id": row[21],
            "result_status": row[22],
            "result_code": row[23],
            "result_message": row[24],
            "change_before": row[25],
            "change_after": row[26],
        }

        if seq != expected_seq:
            report.is_valid = False
            report.errors.append(
                f"Rupture de séquence: attendu {expected_seq}, trouvé {seq} (event_id={row[3]})"
            )

        if stored_prev != expected_prev:
            report.is_valid = False
            report.errors.append(
                f"Rupture de prev_hash à seq={seq}: attendu {expected_prev}, trouvé {stored_prev}"
            )

        calculated_hash = compute_event_hash(ev_dict, stored_prev, seq)
        if calculated_hash != stored_hash:
            report.is_valid = False
            report.errors.append(
                f"Altération du hash à seq={seq} (event_id={row[3]}): "
                f"recalculé {calculated_hash} != stocké {stored_hash}"
            )

        expected_prev = stored_hash
        expected_seq = seq + 1
        report.events_verified += 1

    # 2. Vérification des lots
    batches_cursor = conn.execute(
        """
        SELECT b.batch_id, b.app, b.schema_version, b.event_count, b.signature,
               min(e.integrity_seq), max(e.integrity_seq),
               (SELECT event_hash FROM deedbook.audit_events
                WHERE integrity_seq = min(e.integrity_seq)),
               (SELECT event_hash FROM deedbook.audit_events
                WHERE integrity_seq = max(e.integrity_seq)),
               count(e.event_id)
        FROM deedbook.audit_batches b
        LEFT JOIN deedbook.audit_events e ON b.batch_id = e.batch_id
        GROUP BY b.batch_id, b.app, b.schema_version, b.event_count, b.signature
        ORDER BY min(e.integrity_seq) ASC NULLS LAST
        """
    )
    for b_row in batches_cursor.fetchall():
        (
            b_id,
            app,
            s_ver,
            count,
            sig,
            first_seq,
            last_seq,
            first_hash,
            last_hash,
            actual_count,
        ) = b_row
        report.batches_verified += 1

        if count != actual_count:
            report.is_valid = False
            report.errors.append(
                f"Incohérence du lot {b_id}: event_count={count} != événements réels={actual_count}"
            )

        if signing_key_b64 and sig and first_seq is not None:
            meta = {
                "batch_id": str(b_id),
                "app": app,
                "schema_version": s_ver,
                "event_count": count,
                "first_seq": first_seq,
                "last_seq": last_seq,
                "first_hash": first_hash,
                "last_hash": last_hash,
            }
            sig_bytes = bytes(sig)
            if not verify_batch_signature(meta, sig_bytes, signing_key_b64):
                report.is_valid = False
                report.errors.append(f"Signature invalide pour le lot {b_id}")

    return report
