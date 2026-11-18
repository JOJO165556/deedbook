"""Tests pour le système de modules activables et le module webhooks."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from deedbook.api.app import create_app
from deedbook.modules import load_manifest, load_modules


def test_load_manifest_valide():
    """Charge correctement un fichier module.toml valide."""
    toml_content = """
[module]
name = "webhooks"
permissions = ["events:read"]
functions = ["notify"]
menu = ["Alertes"]
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "module.toml"
        p.write_text(toml_content)
        m = load_manifest(p)
        assert m.name == "webhooks"
        assert m.permissions == ["events:read"]
        assert m.functions == ["notify"]
        assert m.menu == ["Alertes"]


def test_load_manifest_sans_nom_leve_erreur():
    """Un module.toml sans nom de module lève ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "module.toml"
        p.write_text("[module]\npermissions = []")
        with pytest.raises(ValueError, match="name requise"):
            load_manifest(p)


def test_load_modules_module_introuvable_leve_erreur():
    """Demander un module activé inexistant lève FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(FileNotFoundError, match="introuvable"):
            load_modules(Path(tmpdir), enabled=["inexistant"])


def test_routes_modules_non_exposes_par_defaut():
    """Si aucun module n'est activé, aucune route /v1/modules n'est accessible."""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/v1/modules/webhooks/status")
    assert resp.status_code == 404


def test_routes_modules_exposes_quand_active():
    """Quand un module est activé dans la configuration, ses routes sont montées."""
    with patch("deedbook.config.policy", return_value={"modules": {"enabled": ["webhooks"]}}):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/v1/modules/webhooks/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["module"] == "webhooks"
        assert data["status"] == "active"


def test_detection_evenement_critique():
    """Le module webhooks identifie correctement les événements critiques d'audit."""
    from deedbook.modules.webhooks.notifier import is_critical_event

    assert is_critical_event({"result": {"status": "denied"}})
    assert is_critical_event({"result_status": "denied"})
    assert is_critical_event({"action": "authz_change"})
    assert is_critical_event({"action": "role_change"})

    # Événement normal non critique
    assert not is_critical_event({"action": "read", "result_status": "ok"})
    assert not is_critical_event({"action": "create", "result": {"status": "success"}})


def test_dispatch_webhook_envoie_requete_post():
    """dispatch_webhook émet une requête POST avec les en-têtes et données de l'événement."""
    from deedbook.modules.webhooks.notifier import dispatch_webhook

    event = {
        "event_id": "evt-123",
        "action": "authz_change",
        "result_status": "denied",
        "app": "monapp",
    }

    with patch("httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok = dispatch_webhook(
            url="https://alerts.example.com/webhook",
            event=event,
            signing_key_b64=None,
        )
        assert ok is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://alerts.example.com/webhook"
        assert kwargs["json"]["event_id"] == "evt-123"
        assert kwargs["timeout"] == 3


def test_dispatch_webhook_silencieux_sur_erreur_reseau():
    """Un échec réseau sur l'envoi d'un webhook ne fait pas planter l'application."""
    from httpx import ConnectError

    from deedbook.modules.webhooks.notifier import dispatch_webhook

    event = {"event_id": "evt-err", "action": "authz_change"}

    with patch("httpx.post", side_effect=ConnectError("Connexion refusée")):
        ok = dispatch_webhook(
            url="https://unreachable.example.com/webhook",
            event=event,
        )
        assert ok is False


def test_ingestion_declenche_webhook_sur_evenement_critique():
    """L'ingestion d'un événement critique appelle dispatch_webhook si webhooks est actif."""
    batch_payload = {
        "schema_version": "1.0",
        "batch_id": "00000000-0000-0000-0000-000000000099",
        "app": "monapp",
        "sent_at": "2026-11-18T00:00:00+00:00",
        "events": [
            {
                "schema_version": "1.0",
                "event_id": "00000000-0000-0000-0000-000000000098",
                "idempotency_key": "idemp-crit-1",
                "occurred_at": "2026-11-18T00:00:00+00:00",
                "actor": {"type": "human", "end_user": "alice", "role": "admin"},
                "action": "authz_change",
                "origin": {"app": "monapp", "component": "web"},
                "resource": {"type": "other", "name": "root"},
                "result": {"status": "denied"},
            }
        ],
    }

    mock_policy = {
        "modules": {
            "enabled": ["webhooks"],
            "webhooks": {"url": "https://example.com/alerts"},
        }
    }
    with (
        patch("deedbook.api.routes.load_policy", return_value=mock_policy),
        patch("deedbook.modules.webhooks.notifier.dispatch_webhook") as mock_dispatch,
    ):
        app = create_app()
        client = TestClient(app)
        resp = client.post(
            "/v1/events",
            json=batch_payload,
            headers={"Authorization": "Bearer token_test_monapp"},
        )
        assert resp.status_code == 202
        mock_dispatch.assert_called_once()
        args, _ = mock_dispatch.call_args
        assert args[0] == "https://example.com/alerts"
        assert args[1]["event_id"] == "00000000-0000-0000-0000-000000000098"
