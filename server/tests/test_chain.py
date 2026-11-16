import base64
import datetime as dt
import uuid

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from deedbook.admin import connect, database_url
from deedbook.api.app import create_app
from deedbook.chain import (
    GENESIS_HASH,
    compute_event_hash,
    sign_batch,
    verify_batch_signature,
    verify_chain,
)


@pytest.fixture
def client():
    return TestClient(create_app())


def test_compute_event_hash_deterministic():
    event_dict = {
        "event_id": "01932e8a-7c4f-7b2a-9d1e-3f5a6b7c8d9e",
        "action": "create",
        "actor_type": "human",
        "actor_end_user": "alice",
        "app": "monapp",
        "occurred_at": "2026-11-16T12:00:00Z",
        "result_status": "success",
        "change_after": {"title": "Test"},
    }
    prev_hash = GENESIS_HASH
    seq = 1

    h1 = compute_event_hash(event_dict, prev_hash=prev_hash, seq=seq)
    h2 = compute_event_hash(event_dict, prev_hash=prev_hash, seq=seq)
    assert h1 == h2
    assert len(h1) == 64

    # Une modification minime doit changer le hash
    event_dict_alt = dict(event_dict, action="update")
    h3 = compute_event_hash(event_dict_alt, prev_hash=prev_hash, seq=seq)
    assert h1 != h3

    # Un changement de seq ou prev_hash doit changer le hash
    h4 = compute_event_hash(event_dict, prev_hash="a" * 64, seq=seq)
    assert h1 != h4


def test_sign_and_verify_batch():
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes_raw()
    seed_b64 = base64.b64encode(seed).decode()

    batch_meta = {
        "batch_id": str(uuid.uuid4()),
        "app": "testapp",
        "schema_version": "1.0",
        "event_count": 2,
        "first_seq": 1,
        "last_seq": 2,
        "first_hash": "a" * 64,
        "last_hash": "b" * 64,
    }

    signature = sign_batch(batch_meta, seed_b64)
    assert isinstance(signature, bytes)
    assert len(signature) == 64

    # Vérification avec la clé publique dérivée
    assert verify_batch_signature(batch_meta, signature, seed_b64) is True

    # Falsification d'une métadonnée
    corrupted_meta = dict(batch_meta, event_count=3)
    assert verify_batch_signature(corrupted_meta, signature, seed_b64) is False


def test_chain_created_on_ingest(client):
    app_name = f"chain_{uuid.uuid4().hex[:8]}"
    now = dt.datetime.now(dt.UTC)

    batch_payload = {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "app": app_name,
        "sent_at": now.isoformat(),
        "events": [
            {
                "schema_version": "1.0",
                "event_id": str(uuid.uuid4()),
                "idempotency_key": f"key_{uuid.uuid4().hex[:12]}",
                "occurred_at": now.isoformat(),
                "actor": {"type": "human", "end_user": "u1"},
                "origin": {"app": app_name},
                "action": "login",
                "result": {"status": "success"},
            },
            {
                "schema_version": "1.0",
                "event_id": str(uuid.uuid4()),
                "idempotency_key": f"key_{uuid.uuid4().hex[:12]}",
                "occurred_at": now.isoformat(),
                "actor": {"type": "human", "end_user": "u2"},
                "origin": {"app": app_name},
                "action": "logout",
                "result": {"status": "success"},
            },
        ],
    }

    res = client.post("/v1/events", json=batch_payload, headers={"Authorization": "Bearer any"})
    assert res.status_code == 202

    # Vérifier que les événements ont bien un integrity_seq, prev_hash et event_hash
    with connect(database_url()) as conn:
        rows = conn.execute(
            """
            SELECT integrity_seq, prev_hash, event_hash
            FROM deedbook.audit_events
            WHERE batch_id = %s
            ORDER BY integrity_seq ASC
            """,
            (batch_payload["batch_id"],),
        ).fetchall()
        assert len(rows) == 2
        seq1, prev1, hash1 = rows[0]
        seq2, prev2, hash2 = rows[1]

        assert seq1 is not None and seq2 is not None
        assert seq2 == seq1 + 1
        assert prev2 == hash1
        assert len(hash1) == 64
        assert len(hash2) == 64

        # Vérifier la signature du lot
        batch_row = conn.execute(
            "SELECT signature FROM deedbook.audit_batches WHERE batch_id = %s",
            (batch_payload["batch_id"],),
        ).fetchone()
        assert batch_row is not None
        assert batch_row[0] is not None
        assert len(batch_row[0]) == 64


def test_verify_chain_detects_valid_chain():
    with connect(database_url()) as conn:
        report = verify_chain(conn)
        assert report.is_valid is True
        assert report.events_verified >= 0


def test_atk_04_tampered_event_detected():
    # ATK-04 : Modification d'un événement -> verify_chain détecte l'incohérence
    with connect(database_url()) as conn:
        # Trouver un événement existant
        row = conn.execute(
            """
            SELECT event_id, event_hash
            FROM deedbook.audit_events
            ORDER BY integrity_seq DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            pytest.skip("Aucun événement en base pour tester l'altération")

        event_id, orig_hash = row

        # Désactiver temporairement le trigger pour simuler une altération interne par attaquant
        conn.execute("ALTER TABLE deedbook.audit_events DISABLE TRIGGER audit_events_immutable")
        try:
            conn.execute(
                "UPDATE deedbook.audit_events SET event_hash = %s WHERE event_id = %s",
                ("f" * 64, event_id),
            )
            report = verify_chain(conn)
            assert report.is_valid is False
            assert any(str(event_id) in err or "hash" in err for err in report.errors)
        finally:
            # Restaurer le hash original et réactiver le trigger
            conn.execute(
                "UPDATE deedbook.audit_events SET event_hash = %s WHERE event_id = %s",
                (orig_hash, event_id),
            )
            conn.execute("ALTER TABLE deedbook.audit_events ENABLE TRIGGER audit_events_immutable")


def test_atk_01_and_02_and_03_immutability():
    # ATK-01 / ATK-02 / ATK-03 : Les triggers bloquent UPDATE / DELETE / TRUNCATE
    with connect(database_url()) as conn:
        row = conn.execute("SELECT event_id FROM deedbook.audit_events LIMIT 1").fetchone()
        if not row:
            pytest.skip("Aucun événement pour tester les triggers")

        event_id = row[0]

        # Tenter un UPDATE -> doit échouer
        with pytest.raises(psycopg.Error) as exc_update:
            conn.execute(
                "UPDATE deedbook.audit_events SET action = 'tampered' WHERE event_id = %s",
                (event_id,),
            )
        assert "écriture interdite" in str(exc_update.value).lower()
        conn.rollback()

        # Tenter un DELETE -> doit échouer
        with pytest.raises(psycopg.Error) as exc_delete:
            conn.execute(
                "DELETE FROM deedbook.audit_events WHERE event_id = %s",
                (event_id,),
            )
        assert "écriture interdite" in str(exc_delete.value).lower()
        conn.rollback()

        # Tenter un TRUNCATE -> doit échouer
        with pytest.raises(psycopg.Error) as exc_truncate:
            conn.execute("TRUNCATE deedbook.audit_events")
        assert "écriture interdite" in str(exc_truncate.value).lower()
        conn.rollback()
