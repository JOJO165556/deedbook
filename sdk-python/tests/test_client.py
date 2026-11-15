import json

import httpx
import pytest

from deedbook_sdk import AuditClient, disable, enable


@pytest.fixture(autouse=True)
def _reset_global_state():
    enable()
    yield
    enable()


def test_emit_never_raises_on_invalid_data():
    client = AuditClient("http://localhost:8000", "my-token", app_name="testapp")
    # Ne doit jamais lever d'exception
    client.emit(None)
    client.emit("not a dict")
    client.emit({})


def test_emit_never_raises_on_network_failure():
    # URL sur un port inaccessible
    client = AuditClient("http://127.0.0.1:59999", "my-token", app_name="testapp")
    client.emit({"action": "login", "result": {"status": "success"}})
    # flush ne doit jamais lever
    client.flush()


def test_disable_feature():
    client = AuditClient("http://localhost:8000", "my-token", app_name="testapp")
    assert not client.is_disabled
    client.disable()
    assert client.is_disabled
    client.emit({"action": "login", "result": {"status": "success"}})
    assert client.pending_count == 0


def test_global_disable():
    client = AuditClient("http://localhost:8000", "my-token", app_name="testapp")
    disable()
    assert client.is_disabled


def test_emit_and_flush_sends_batch_to_engine():
    recorded_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(202, json={"batch_id": "b1", "received_count": 1})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.Client(transport=transport)

    client = AuditClient(
        "http://engine.local:8000",
        "secret-token-123",
        app_name="monapp",
        http_client=http_client,
    )

    client.emit(
        {
            "action": "create",
            "actor": {"type": "human", "end_user": "alice"},
            "resource": {"type": "record", "name": "users", "id": "1"},
            "result": {"status": "success"},
            "change": {"before": None, "after": {"name": "Alice"}},
        }
    )

    client.flush()

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.method == "POST"
    assert req.url == "http://engine.local:8000/v1/events"
    assert req.headers["Authorization"] == "Bearer secret-token-123"

    body = json.loads(req.content.decode("utf-8"))
    assert body["app"] == "monapp"
    assert body["schema_version"] == "1.0"
    assert "batch_id" in body
    assert len(body["events"]) == 1

    ev = body["events"][0]
    assert ev["action"] == "create"
    assert ev["origin"]["app"] == "monapp"
    assert "event_id" in ev
    assert "occurred_at" in ev
    assert "idempotency_key" in ev
