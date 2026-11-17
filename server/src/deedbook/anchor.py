"""Ancrage externe d'intégrité : publie l'état de chain_state vers un endpoint tiers."""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from httpx import HTTPError

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


def publish_anchor(
    conn: psycopg.Connection,
    anchor_url: str | None,
    signing_key_b64: str,
) -> None:
    """Publie l'empreinte courante de chain_state vers anchor_url.

    Silencieux sur toute erreur réseau ou HTTP : l'ingestion ne doit jamais
    être bloquée par une indisponibilité du serveur d'ancrage.
    """
    if not anchor_url:
        return

    row = conn.execute(
        "SELECT last_seq, last_hash FROM deedbook.chain_state WHERE id = 1"
    ).fetchone()

    last_seq: int = row[0]
    last_hash: str = row[1]
    timestamp = datetime.now(UTC).isoformat()

    # Payload sans signature pour construire le message à signer
    payload_body = {
        "last_seq": last_seq,
        "last_hash": last_hash,
        "timestamp": timestamp,
    }
    message = json.dumps(payload_body, sort_keys=True, separators=(",", ":")).encode()

    # Signature Ed25519 du payload canonique
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = base64.b64decode(signing_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = base64.b64encode(private_key.sign(message)).decode()

    payload = {**payload_body, "signature_ed25519": signature}

    try:
        httpx.post(anchor_url, json=payload, timeout=5).raise_for_status()
        logger.info("ancrage publié : seq=%d hash=%.16s...", last_seq, last_hash)
    except (OSError, HTTPError) as exc:
        # Échec silencieux : l'ancrage est une preuve complémentaire, pas critique.
        logger.warning("ancrage indisponible (ignoré) : %s", exc)
