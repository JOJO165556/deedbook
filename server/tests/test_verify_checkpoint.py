"""Tests TDD pour verify_chain avec reprise depuis checkpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from deedbook.chain import compute_event_hash, verify_chain


def _cursor(rows: list, fetchone_result=None) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchone.return_value = fetchone_result
    return cur


def _conn_two_queries(event_rows: list, batch_rows: list | None = None) -> MagicMock:
    """Connexion mock retournant des curseurs differents pour les deux requetes de verify_chain."""
    conn = MagicMock()
    conn.execute.side_effect = [
        _cursor(event_rows),
        _cursor(batch_rows or []),
    ]
    return conn


def test_verify_chain_sans_checkpoint_part_de_genesis():
    """Sans checkpoint, verify_chain demarre a seq=1 et prev=GENESIS."""
    conn = _conn_two_queries([])
    report = verify_chain(conn)
    assert report.is_valid
    assert report.events_verified == 0


def test_verify_chain_avec_from_seq_et_from_hash():
    """verify_chain accepte from_seq et from_hash pour reprendre apres purge."""
    conn = _conn_two_queries([])
    report = verify_chain(conn, from_seq=10, from_hash="a" * 64)
    assert report.is_valid
    assert report.events_verified == 0


def test_verify_chain_checkpoint_modifie_point_de_depart():
    """Avec from_seq=5, from_hash=H5, le premier evenement attendu est seq=6 avec prev=H5."""
    prev_hash = "b" * 64
    seq = 6

    ev_data = {
        "schema_version": "1.0",
        "event_id": "evt-6",
        "idempotency_key": None,
        "occurred_at": "2024-01-01T00:00:00+00:00",
        "actor_end_user": None,
        "actor_type": None,
        "actor_role": None,
        "service_account": None,
        "app": "test",
        "untrusted_app": None,
        "component": None,
        "ip": None,
        "session_id": None,
        "request_id": None,
        "correlation_id": None,
        "action": "read",
        "resource_type": None,
        "resource_name": None,
        "resource_id": None,
        "result_status": "ok",
        "result_code": None,
        "result_message": None,
        "change_before": None,
        "change_after": None,
    }
    good_hash = compute_event_hash(ev_data, prev_hash, seq)

    row = (
        seq,
        prev_hash,
        good_hash,
        "evt-6",
        "1.0",
        None,
        "2024-01-01T00:00:00+00:00",
        None,
        None,
        None,
        None,
        "test",
        None,
        None,
        None,
        None,
        None,
        None,
        "read",
        None,
        None,
        None,
        "ok",
        None,
        None,
        None,
        None,
    )

    conn = _conn_two_queries([row])
    report = verify_chain(conn, from_seq=5, from_hash=prev_hash)

    assert report.is_valid, report.errors
    assert report.events_verified == 1


def test_verify_chain_checkpoint_detecte_rupture():
    """Si from_seq=5 mais le premier event est seq=7, rupture de sequence detectee."""
    row = (
        7,
        "b" * 64,
        "c" * 64,
        "evt-7",
        "1.0",
        None,
        "2024-01-01T00:00:00+00:00",
        None,
        None,
        None,
        None,
        "test",
        None,
        None,
        None,
        None,
        None,
        None,
        "read",
        None,
        None,
        None,
        "ok",
        None,
        None,
        None,
        None,
    )

    conn = _conn_two_queries([row])
    report = verify_chain(conn, from_seq=5, from_hash="b" * 64)

    assert not report.is_valid
    assert any("séquence" in e for e in report.errors)
