import datetime as dt
import uuid

import pytest
from starlette.testclient import TestClient

from deedbook.admin import add_project
from deedbook.api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def make_valid_batch(app_name="monapp", event_count=1) -> dict:
    events = []
    for i in range(event_count):
        events.append(
            {
                "schema_version": "1.0",
                "event_id": str(uuid.uuid4()),
                "idempotency_key": f"idemp_{uuid.uuid4().hex[:12]}",
                "occurred_at": dt.datetime.now(dt.UTC).isoformat(),
                "actor": {"type": "human", "end_user": f"user_{i}", "role": "editor"},
                "service_account": None,
                "origin": {"app": app_name, "component": "api"},
                "action": "create",
                "resource": {"type": "record", "name": "users", "id": str(i)},
                "result": {"status": "success"},
                "change": {
                    "before": None,
                    "after": {"name": f"User {i}", "secret_key": "sensitive"},
                },
            }
        )

    return {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "app": app_name,
        "sent_at": dt.datetime.now(dt.UTC).isoformat(),
        "events": events,
    }


def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_missing_auth_header(client):
    batch = make_valid_batch()
    res = client.post("/v1/events", json=batch)
    assert res.status_code == 401
    data = res.json()
    assert data["error"] == "unauthorized"


def test_unknown_app_accepted_as_untrusted(client):
    batch = make_valid_batch("unknown-app-xyz")
    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer some-random-unregistered-token"},
    )
    assert res.status_code == 202
    data = res.json()
    assert data["batch_id"] == batch["batch_id"]
    assert data["received_count"] == 1
    assert data["untrusted_app"] is True


def test_valid_app_accepted_as_trusted(client, monkeypatch):
    test_app_name = f"testapp_{uuid.uuid4().hex[:8]}"

    # Enregistrer un projet pour obtenir un vrai jeton
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = add_project(test_app_name)
    assert ret == 0
    token_line = [line for line in buf.getvalue().splitlines() if "Jeton d'ingestion" in line][0]
    token = token_line.split(":", 1)[1].strip()

    batch = make_valid_batch(test_app_name, event_count=2)
    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 202
    data = res.json()
    assert data["batch_id"] == batch["batch_id"]
    assert data["received_count"] == 2
    assert data["untrusted_app"] is False

    # ATK-10 : rejouer le lot avec les mêmes event_id (idempotence)
    res_replay = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_replay.status_code == 202
    data_replay = res_replay.json()
    assert data_replay["received_count"] == 2


def test_atk_07_batch_too_large_by_event_count(client):
    # ATK-07 : Envoyer un lot de 101 événements -> 413 batch_too_large
    batch = make_valid_batch(event_count=101)
    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer any-token"},
    )
    assert res.status_code == 413
    data = res.json()
    assert data["error"] == "batch_too_large"


def test_validation_error_format(client):
    batch = make_valid_batch()
    # Rendre un événement invalide (occurred_at dans le futur de 1h)
    batch["events"][0]["occurred_at"] = (
        dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    ).isoformat()

    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer any-token"},
    )
    assert res.status_code == 422
    data = res.json()
    assert data["error"] == "validation_failed"
    assert len(data["detail"]) >= 1
    err = data["detail"][0]
    assert err["index"] == 0
    assert err["field"] == "occurred_at"
    assert "futur" in err["reason"]


def test_inactive_app_rejected_401(client):
    test_app_name = f"inactive_{uuid.uuid4().hex[:8]}"

    # Enregistrer un projet puis le désactiver en base
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = add_project(test_app_name)
    assert ret == 0
    token_line = [line for line in buf.getvalue().splitlines() if "Jeton d'ingestion" in line][0]
    token = token_line.split(":", 1)[1].strip()

    # Désactiver l'application
    from deedbook.admin import connect, database_url

    with connect(database_url()) as conn:
        conn.execute("UPDATE deedbook.apps SET active = false WHERE name = %s", (test_app_name,))

    batch = make_valid_batch(test_app_name, event_count=1)
    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error"] == "unauthorized"


def test_masking_applied_in_database(client, monkeypatch):
    test_app_name = f"maskapp_{uuid.uuid4().hex[:8]}"
    batch = make_valid_batch(test_app_name, event_count=1)
    ev_id = batch["events"][0]["event_id"]

    # Simuler des règles de masquage
    fake_policy = {
        "project": {"name": "deedbook"},
        "modules": {"enabled": []},
        "retention": {"default_days": 365},
        "masking": {
            "fields": [
                {"resource": "*", "field": "secret_key", "strategy": "redact"},
                {"resource": "*", "field": "phone", "strategy": "mask", "keep": 3},
            ]
        },
        "ingestion": {},
    }
    monkeypatch.setattr("deedbook.api.routes.load_policy", lambda: fake_policy)

    batch["events"][0]["change"]["after"] = {
        "name": "Bob",
        "secret_key": "supersecretpassword",
        "phone": "0612345678",
    }

    res = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer any-token"},
    )
    assert res.status_code == 202

    # Vérifier directement en base dans audit_events avec deedbook_read
    from deedbook.admin import connect, database_url

    with connect(database_url()) as conn:
        row = conn.execute(
            "SELECT change_after FROM deedbook.audit_events WHERE event_id = %s",
            (ev_id,),
        ).fetchone()
        assert row is not None
        change_after = row[0]
        assert change_after["secret_key"] == "[redacted]"
        assert change_after["phone"] == "061*******"
        assert change_after["name"] == "Bob"


def test_get_event_by_id_endpoint(client):
    from deedbook.config import get_settings

    settings = get_settings()
    admin_token = settings.admin_token.get_secret_value()

    # 1. Requête sans jeton admin -> 401
    res_no_auth = client.get(f"/v1/events/{uuid.uuid4()}")
    assert res_no_auth.status_code == 401

    # 2. Requête pour événement inexistant -> 404
    non_existent = str(uuid.uuid4())
    res_not_found = client.get(
        f"/v1/events/{non_existent}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_not_found.status_code == 404
    assert res_not_found.json()["error"] == "not_found"

    # 3. Insérer un événement valide puis le récupérer
    test_app = f"getapp_{uuid.uuid4().hex[:8]}"
    batch = make_valid_batch(test_app, event_count=1)
    ev_id = batch["events"][0]["event_id"]

    res_post = client.post(
        "/v1/events",
        json=batch,
        headers={"Authorization": "Bearer any-token"},
    )
    assert res_post.status_code == 202

    res_get = client.get(
        f"/v1/events/{ev_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_get.status_code == 200
    ev = res_get.json()
    assert ev["event_id"] == ev_id
    assert ev["origin"]["app"] == test_app
    assert ev["action"] == "create"
    assert ev["result"]["status"] == "success"
    assert "received_at" in ev


def test_search_events_requires_admin_token(client):
    res = client.get("/v1/events")
    assert res.status_code == 401
    assert res.json()["error"] == "unauthorized"


def test_search_events_filtering_and_pagination(client):
    from deedbook.config import get_settings

    settings = get_settings()
    admin_token = settings.admin_token.get_secret_value()
    headers = {"Authorization": f"Bearer {admin_token}"}

    test_prefix = f"filter_{uuid.uuid4().hex[:6]}"
    app_a = f"{test_prefix}_a"
    app_b = f"{test_prefix}_b"

    now = dt.datetime.now(dt.UTC)
    events_payload_a = [
        {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "idempotency_key": f"k1_{uuid.uuid4().hex[:8]}",
            "occurred_at": (now - dt.timedelta(minutes=3)).isoformat(),
            "actor": {"type": "human", "end_user": "alice", "role": "admin"},
            "origin": {"app": app_a},
            "action": "create",
            "resource": {"type": "record", "name": "users", "id": "1"},
            "result": {"status": "success"},
            "change": {"before": None, "after": {"username": "alice"}},
            "correlation_id": f"corr_{test_prefix}_1",
        },
        {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "idempotency_key": f"k2_{uuid.uuid4().hex[:8]}",
            "occurred_at": (now - dt.timedelta(minutes=2)).isoformat(),
            "actor": {"type": "human", "end_user": "bob", "role": "user"},
            "origin": {"app": app_a},
            "action": "login",
            "result": {"status": "success"},
            "correlation_id": f"corr_{test_prefix}_2",
        },
    ]

    events_payload_b = [
        {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "idempotency_key": f"k3_{uuid.uuid4().hex[:8]}",
            "occurred_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "actor": {"type": "human", "end_user": "alice", "role": "admin"},
            "origin": {"app": app_b},
            "action": "delete",
            "resource": {"type": "record", "name": "articles", "id": "99"},
            "result": {"status": "success"},
            "change": {"before": {"title": "Old"}, "after": None},
            "correlation_id": f"corr_{test_prefix}_1",
        }
    ]

    # Ingestion des lots
    batch_a = {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "app": app_a,
        "sent_at": now.isoformat(),
        "events": events_payload_a,
    }
    batch_b = {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "app": app_b,
        "sent_at": now.isoformat(),
        "events": events_payload_b,
    }

    res_a = client.post("/v1/events", json=batch_a, headers={"Authorization": "Bearer any"})
    assert res_a.status_code == 202
    res_b = client.post("/v1/events", json=batch_b, headers={"Authorization": "Bearer any"})
    assert res_b.status_code == 202

    # Recherche filtre par app
    res_app = client.get(f"/v1/events?app={app_a}", headers=headers)
    assert res_app.status_code == 200
    data_app = res_app.json()
    assert data_app["total"] == 2
    assert len(data_app["events"]) == 2
    assert all(e["origin"]["app"] == app_a for e in data_app["events"])

    # Recherche filtre par acteur
    res_actor = client.get(f"/v1/events?app={app_a}&actor=alice", headers=headers)
    assert res_actor.status_code == 200
    data_actor = res_actor.json()
    assert data_actor["total"] == 1
    assert data_actor["events"][0]["actor"]["end_user"] == "alice"

    # Recherche filtre par action
    res_action = client.get("/v1/events?action=login", headers=headers)
    assert res_action.status_code == 200
    data_action = res_action.json()
    assert any(e["action"] == "login" for e in data_action["events"])

    # Recherche filtre par correlation_id
    res_corr = client.get(f"/v1/events?correlation_id=corr_{test_prefix}_1", headers=headers)
    assert res_corr.status_code == 200
    data_corr = res_corr.json()
    assert data_corr["total"] == 2
    assert {e["origin"]["app"] for e in data_corr["events"]} == {app_a, app_b}

    # Pagination
    res_pag = client.get(f"/v1/events?app={app_a}&limit=1&offset=0", headers=headers)
    assert res_pag.status_code == 200
    data_pag = res_pag.json()
    assert data_pag["total"] == 2
    assert len(data_pag["events"]) == 1
    assert data_pag["limit"] == 1
    assert data_pag["offset"] == 0
