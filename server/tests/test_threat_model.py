"""Tests d'attaque ATK-01 à ATK-10 conformément au modèle de menace (docs/modele-de-menace.md)."""

from __future__ import annotations

import datetime as dt
import uuid
from importlib.machinery import SourceFileLoader
from pathlib import Path

import psycopg
import pytest
from starlette.testclient import TestClient

from deedbook.admin import APP_NAME_RE, add_project
from deedbook.api.app import create_app
from deedbook.api.routes import MAX_BATCH_BYTES
from deedbook.chain import verify_chain
from deedbook.config import get_settings


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _make_batch(app_name: str = "monapp", event_count: int = 1, **kwargs) -> dict:
    events = []
    for i in range(event_count):
        ev = {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "idempotency_key": f"atk_idemp_{uuid.uuid4().hex[:12]}",
            "occurred_at": dt.datetime.now(dt.UTC).isoformat(),
            "actor": {"type": "human", "end_user": f"user_{i}", "role": "tester"},
            "service_account": None,
            "origin": {"app": app_name, "component": "api"},
            "action": "create",
            "resource": {"type": "record", "name": "items", "id": str(i)},
            "result": {"status": "success"},
            "change": {"before": None, "after": {"name": f"Item {i}"}},
        }
        ev.update(kwargs)
        events.append(ev)

    return {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "app": app_name,
        "sent_at": dt.datetime.now(dt.UTC).isoformat(),
        "events": events,
    }


def test_atk_01_least_privilege_ingest_and_read_roles():
    """ATK-01 : Le rôle deedbook_ingest ne peut ni lire ni muter les tables d'audit.

    Le rôle deedbook_read peut uniquement lire (aucun INSERT/UPDATE/DELETE).
    """
    settings = get_settings()
    if not settings.ingest_url or not settings.read_url:
        pytest.skip("DEEDBOOK_INGEST_URL ou DEEDBOOK_READ_URL manquant dans la configuration")

    ingest_dsn = settings.ingest_url.get_secret_value()
    read_dsn = settings.read_url.get_secret_value()

    # 1. Rôle d'ingestion : interdiction stricte de SELECT, UPDATE, DELETE, TRUNCATE
    with psycopg.connect(ingest_dsn) as conn:
        for query in (
            "SELECT * FROM deedbook.audit_events LIMIT 1",
            "SELECT * FROM deedbook.audit_batches LIMIT 1",
            "UPDATE deedbook.audit_events SET action = 'tampered'",
            "DELETE FROM deedbook.audit_events",
            "TRUNCATE deedbook.audit_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)
            conn.rollback()

    # 2. Rôle de lecture : SELECT autorisé, mutation interdite
    with psycopg.connect(read_dsn) as conn:
        # Lecture autorisée
        res = conn.execute("SELECT count(*) FROM deedbook.audit_events").fetchone()
        assert res is not None

        # Écriture strictement interdite
        for query in (
            (
                "INSERT INTO deedbook.audit_events (event_id) "
                "VALUES ('00000000-0000-0000-0000-000000000000')"
            ),
            "UPDATE deedbook.audit_events SET action = 'tampered'",
            "DELETE FROM deedbook.audit_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)
            conn.rollback()


def test_atk_02_immutability_triggers_block_audit_events_mutation():
    """ATK-02 : Les triggers PostgreSQL bloquent UPDATE/DELETE/TRUNCATE sur audit_events."""
    settings = get_settings()
    admin_dsn = settings.database_url.get_secret_value()

    with psycopg.connect(admin_dsn) as conn:
        row = conn.execute("SELECT event_id FROM deedbook.audit_events LIMIT 1").fetchone()
        if not row:
            pytest.skip("Aucun événement en base pour tester l'immutabilité")
        event_id = row[0]

        with pytest.raises(psycopg.Error) as exc_update:
            conn.execute(
                "UPDATE deedbook.audit_events SET action = 'tampered' WHERE event_id = %s",
                (event_id,),
            )
        assert "écriture interdite" in str(exc_update.value).lower()
        conn.rollback()

        with pytest.raises(psycopg.Error) as exc_delete:
            conn.execute(
                "DELETE FROM deedbook.audit_events WHERE event_id = %s",
                (event_id,),
            )
        assert "écriture interdite" in str(exc_delete.value).lower()
        conn.rollback()

        with pytest.raises(psycopg.Error) as exc_truncate:
            conn.execute("TRUNCATE deedbook.audit_events")
        assert "écriture interdite" in str(exc_truncate.value).lower()
        conn.rollback()


def test_atk_03_immutability_triggers_block_audit_batches_mutation():
    """ATK-03 : Les triggers PostgreSQL bloquent UPDATE/DELETE/TRUNCATE sur audit_batches."""
    settings = get_settings()
    admin_dsn = settings.database_url.get_secret_value()

    with psycopg.connect(admin_dsn) as conn:
        row = conn.execute("SELECT batch_id FROM deedbook.audit_batches LIMIT 1").fetchone()
        if not row:
            pytest.skip("Aucun lot en base pour tester l'immutabilité des lots")
        batch_id = row[0]

        with pytest.raises(psycopg.Error) as exc_update:
            conn.execute(
                "UPDATE deedbook.audit_batches SET app = 'tampered' WHERE batch_id = %s",
                (batch_id,),
            )
        assert "écriture interdite" in str(exc_update.value).lower()
        conn.rollback()

        with pytest.raises(psycopg.Error) as exc_delete:
            conn.execute(
                "DELETE FROM deedbook.audit_batches WHERE batch_id = %s",
                (batch_id,),
            )
        assert "écriture interdite" in str(exc_delete.value).lower()
        conn.rollback()

        with pytest.raises(psycopg.Error) as exc_truncate:
            conn.execute("TRUNCATE deedbook.audit_batches CASCADE")
        assert "écriture interdite" in str(exc_truncate.value).lower()
        conn.rollback()


def test_atk_04_tampered_event_detected_by_verify_chain():
    """ATK-04 : L'altération d'un événement dans la base est détectée par verify_chain."""
    settings = get_settings()
    admin_dsn = settings.database_url.get_secret_value()

    with psycopg.connect(admin_dsn) as conn:
        row = conn.execute(
            """
            SELECT event_id, event_hash
            FROM deedbook.audit_events
            ORDER BY integrity_seq DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            pytest.skip("Aucun événement en base pour tester la détection d'altération")

        event_id, orig_hash = row

        # Désactivation temporaire du trigger pour simuler une compromission interne
        conn.execute("ALTER TABLE deedbook.audit_events DISABLE TRIGGER audit_events_immutable")
        try:
            conn.execute(
                "UPDATE deedbook.audit_events SET event_hash = %s WHERE event_id = %s",
                ("a" * 64, event_id),
            )
            report = verify_chain(conn)
            assert report.is_valid is False
            assert any(str(event_id) in err or "hash" in err for err in report.errors)
        finally:
            conn.execute(
                "UPDATE deedbook.audit_events SET event_hash = %s WHERE event_id = %s",
                (orig_hash, event_id),
            )
            conn.execute("ALTER TABLE deedbook.audit_events ENABLE TRIGGER audit_events_immutable")


def test_atk_05_orphan_database_write_detection(client):
    """ATK-05 : Rapprochement pgAudit et détection d'écritures orphelines (scénario S2)."""
    from deedbook.reconcile import parse_pgaudit_log, reconcile_pgaudit

    settings = get_settings()
    admin_dsn = settings.database_url.get_secret_value()

    # 1. Ingestion d'un événement applicatif légitime avec correlation_id
    legit_corr_id = f"corr-{uuid.uuid4().hex[:8]}"
    batch = _make_batch(correlation_id=legit_corr_id)
    resp = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer token_test_monapp"},
    )
    assert resp.status_code == 202

    # 2. Simulation d'un journal pgAudit contenant une écriture légitime et une écriture pirate
    line_legit = (
        "2026-11-18 00:00:01 UTC [1000] LOG:  AUDIT: SESSION,1,1,WRITE,INSERT,TABLE,"
        "public.items,INSERT INTO public.items (name) VALUES ('Item 0') "
        "/* correlation_id: CID */,<not logged>"
    ).replace("CID", legit_corr_id)
    line_rogue = (
        "2026-11-18 00:00:02 UTC [1001] LOG:  AUDIT: SESSION,2,1,WRITE,UPDATE,TABLE,"
        "public.items,UPDATE public.items SET price = 0 WHERE id = '0',<not logged>"
    )
    log_content = f"{line_legit}\n{line_rogue}"

    entries = parse_pgaudit_log(log_content)
    assert len(entries) == 2

    # 3. Réconciliation avec la base de données deedbook
    with psycopg.connect(admin_dsn) as conn:
        report = reconcile_pgaudit(conn, entries)

    # 4. Vérification que l'attaque orpheline S2 est détectée
    assert report.is_clean is False
    assert report.writes_analyzed == 2
    assert report.matched_events == 1
    assert len(report.orphans) == 1
    orphan = report.orphans[0]
    assert orphan.entry.command == "UPDATE"
    assert orphan.entry.object_name == "public.items"
    assert "aucun correlation_id" in orphan.reason.lower()


def test_atk_06_malicious_script_and_sql_injection_payloads(client):
    """ATK-06 : Injections XSS et SQL dans les champs journalisés restent des données inertes."""
    settings = get_settings()
    malicious_script = "<script>alert('xss');</script>"
    sql_injection = "users'; DROP TABLE deedbook.audit_events; --"

    batch = _make_batch()
    batch["events"][0]["action"] = "create"
    batch["events"][0]["resource"] = {
        "type": "record",
        "name": sql_injection,
        "id": "<img src=x onerror=alert(1)>",
    }
    batch["events"][0]["result"] = {
        "status": "success",
        "message": malicious_script,
    }
    batch["events"][0]["change"] = {
        "before": None,
        "after": {
            "xss_field": malicious_script,
            "sql_field": sql_injection,
        },
    }

    headers = {"Authorization": "Bearer test-atk-token"}
    res = client.post("/v1/events", json=batch, headers=headers)
    assert res.status_code == 202

    # Consultation : restitution textuelle sans altération ni exécution
    event_id = batch["events"][0]["event_id"]
    admin_headers = {"Authorization": f"Bearer {settings.admin_token.get_secret_value()}"}
    get_res = client.get(f"/v1/events/{event_id}", headers=admin_headers)
    assert get_res.status_code == 200
    ev_data = get_res.json()

    assert ev_data["result"]["message"] == malicious_script
    assert ev_data["resource"]["name"] == sql_injection
    assert ev_data["change"]["after"]["xss_field"] == malicious_script

    # Vérification que la table d'audit n'a pas été affectée par le fragment SQL
    settings = get_settings()
    with psycopg.connect(settings.database_url.get_secret_value()) as conn:
        count = conn.execute("SELECT count(*) FROM deedbook.audit_events").fetchone()[0]
        assert count > 0


def test_atk_07_batch_limits_max_events_and_max_bytes(client):
    """ATK-07 : Rejet des lots dépassant 100 événements ou 256 Ko (413 batch_too_large)."""
    headers = {"Authorization": "Bearer test-atk-token"}

    # 1. Plus de 100 événements -> rejet HTTP 413
    oversized_count_batch = _make_batch(event_count=101)
    res_count = client.post("/v1/events", json=oversized_count_batch, headers=headers)
    assert res_count.status_code == 413
    assert res_count.json()["error"] == "batch_too_large"

    # 2. Plus de 256 Ko de charge utile brute -> rejet HTTP 413
    huge_data = "x" * (MAX_BATCH_BYTES + 1024)
    res_bytes = client.post(
        "/v1/events",
        content=huge_data.encode("utf-8"),
        headers={"Authorization": "Bearer test-atk-token", "Content-Type": "application/json"},
    )
    assert res_bytes.status_code == 413
    assert res_bytes.json()["error"] == "batch_too_large"


def test_atk_08_precommit_hook_blocks_secrets_and_env_files():
    """ATK-08 : Le hook pre-commit bloque les fichiers .env et les affectations de secrets."""
    import types

    repo_root = Path(__file__).resolve().parents[2]
    hook_path = repo_root / ".githooks" / "pre-commit"

    # Chargement dynamique du script du hook
    loader = SourceFileLoader("pre_commit", str(hook_path))
    module = types.ModuleType(loader.name)
    loader.exec_module(module)

    # Vérification du blocage des fichiers .env
    assert module.BLOCKED_FILES.search(".env") is not None
    assert module.BLOCKED_FILES.search("sub/.env") is not None
    assert module.BLOCKED_FILES.search(".env.local") is not None
    assert any(".env.example".endswith(a) for a in module.ALLOWED) is True

    # Vérification de la détection de motif de secret en clair
    patterns = module.SECRET_PATTERNS
    # Chaînes assemblées dynamiquement pour ne pas déclencher le hook sur ce fichier de test
    leak_line = "+DEEDBOOK_ADMIN_" + 'TOKEN="' + "x" * 32 + '"'
    matches = [label for pat, label in patterns if pat.search(leak_line)]
    assert len(matches) > 0

    privkey_line = "-----" + "BEGIN RSA PRIVATE KEY" + "-----"
    assert any(pat.search(privkey_line) for pat, _ in patterns)


def test_atk_09_project_add_rejects_invalid_app_names():
    """ATK-09 : La commande d'ajout de projet rejette les noms d'application non conformes."""
    invalid_names = [
        "MonApp",  # Majuscule interdite
        "-bad-start",  # Tiret en premier caractère
        "app name with spaces",  # Espaces interdits
        "app/slash",  # Caractères spéciaux interdits
        "a" * 64,  # Longueur max 63
    ]
    for bad in invalid_names:
        assert not APP_NAME_RE.match(bad)
        assert add_project(bad) == 1


def test_atk_10_batch_replay_deduplication_and_zero_duplicate(client):
    """ATK-10 : Le rejeu d'un lot identique est idempotent et n'engendre aucun doublon."""
    batch = _make_batch(app_name="replay-test", event_count=2)
    headers = {"Authorization": "Bearer test-atk-token"}

    # Premier envoi
    res1 = client.post("/v1/events", json=batch, headers=headers)
    assert res1.status_code == 202
    assert res1.json()["received_count"] == 2

    # Rejeu identique immédiat
    res2 = client.post("/v1/events", json=batch, headers=headers)
    assert res2.status_code == 202

    # Vérification en base : les événements ne sont pas dupliqués
    settings = get_settings()
    with psycopg.connect(settings.database_url.get_secret_value()) as conn:
        rows = conn.execute(
            "SELECT count(*) FROM deedbook.audit_events WHERE batch_id = %s",
            (batch["batch_id"],),
        ).fetchone()
        assert rows[0] == 2
