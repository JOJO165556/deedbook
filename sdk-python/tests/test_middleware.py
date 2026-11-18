"""Tests pour les middlewares ASGI et WSGI de deedbook_sdk."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest

from deedbook_sdk.client import AuditClient
from deedbook_sdk.middleware import DeedbookASGIMiddleware, DeedbookWSGIMiddleware


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=AuditClient)
    client.app_name = "testapp"
    return client


def test_asgi_middleware_traite_requete_et_emet_evenement(mock_client: MagicMock):
    """Le middleware ASGI extrait le correlation_id et émet un événement d'audit."""

    async def _run():
        async def dummy_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = DeedbookASGIMiddleware(dummy_app, client=mock_client)

        corr_id = f"corr-{uuid.uuid4().hex[:8]}"
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/users",
            "client": ("192.168.1.10", 12345),
            "headers": [(b"x-correlation-id", corr_id.encode())],
        }

        sent_messages = []

        async def mock_receive():
            return {"type": "http.request"}

        async def mock_send(msg):
            sent_messages.append(msg)

        await middleware(scope, mock_receive, mock_send)

        assert any(msg.get("status") == 200 for msg in sent_messages)

        mock_client.emit.assert_called_once()
        event = mock_client.emit.call_args[0][0]
        assert event["correlation_id"] == corr_id
        assert event["action"] == "http_post"
        assert event["resource"]["name"] == "/api/users"
        assert event["result"]["status"] == "success"
        assert event["origin"]["ip"] == "192.168.1.10"

    asyncio.run(_run())


def test_asgi_middleware_garantie_zero_plantage_si_audit_echoue(mock_client: MagicMock):
    """Même si mock_client.emit lève une exception, la réponse HTTP hôte n'est pas bloquée."""

    async def _run():
        mock_client.emit.side_effect = RuntimeError("Panne totale du client d'audit")

        async def dummy_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"Created"})

        middleware = DeedbookASGIMiddleware(dummy_app, client=mock_client)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/orders",
            "client": ("127.0.0.1", 5000),
            "headers": [],
        }

        sent_messages = []

        async def mock_send(msg):
            sent_messages.append(msg)

        await middleware(scope, lambda: None, mock_send)
        assert any(msg.get("status") == 201 for msg in sent_messages)

    asyncio.run(_run())


def test_wsgi_middleware_traite_requete_et_emet_evenement(mock_client: MagicMock):
    """Le middleware WSGI extrait le contexte et transmet l'événement d'audit."""

    def dummy_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"Hello World"]

    middleware = DeedbookWSGIMiddleware(dummy_app, client=mock_client)

    environ = {
        "REQUEST_METHOD": "PUT",
        "PATH_INFO": "/items/42",
        "REMOTE_ADDR": "10.0.0.5",
        "HTTP_X_CORRELATION_ID": "corr-wsgi-999",
    }

    start_response_mock = MagicMock()
    result = middleware(environ, start_response_mock)

    assert result == [b"Hello World"]
    start_response_mock.assert_called_once()

    mock_client.emit.assert_called_once()
    event = mock_client.emit.call_args[0][0]
    assert event["correlation_id"] == "corr-wsgi-999"
    assert event["action"] == "http_put"
    assert event["resource"]["name"] == "/items/42"
    assert event["result"]["status"] == "success"
    assert event["origin"]["ip"] == "10.0.0.5"


def test_wsgi_middleware_garantie_zero_plantage_si_audit_echoue(mock_client: MagicMock):
    """Si l'émission d'audit lève une exception, le middleware WSGI ne plante pas l'hôte."""
    mock_client.emit.side_effect = Exception("Erreur critique d'audit")

    def dummy_app(environ, start_response):
        start_response("204 No Content", [])
        return []

    middleware = DeedbookWSGIMiddleware(dummy_app, client=mock_client)
    environ = {
        "REQUEST_METHOD": "DELETE",
        "PATH_INFO": "/records/1",
        "REMOTE_ADDR": "127.0.0.1",
    }

    start_response_mock = MagicMock()
    # Ne doit pas lever d'exception
    result = middleware(environ, start_response_mock)
    assert result == []
    start_response_mock.assert_called_once()
