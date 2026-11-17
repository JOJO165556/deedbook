"""Tests pour l'ancrage externe d'intégrité (anchor.py)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch


def _make_conn(last_seq: int = 7, last_hash: str = "a" * 64) -> MagicMock:
    """Connexion psycopg simulée renvoyant un état chain_state cohérent."""
    conn = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, i: (last_seq, last_hash)[i]
    conn.execute.return_value.fetchone.return_value = row
    return conn


def _signing_key_b64() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return base64.b64encode(seed).decode()


def test_publish_anchor_lit_chain_state():
    """publish_anchor interroge chain_state pour obtenir last_seq et last_hash."""
    from deedbook.anchor import publish_anchor

    conn = _make_conn(last_seq=3, last_hash="b" * 64)
    with patch("deedbook.anchor.httpx") as mock_httpx:
        mock_httpx.post.return_value.raise_for_status.return_value = None
        key = _signing_key_b64()
        publish_anchor(conn, anchor_url="http://localhost/anchor", signing_key_b64=key)

    conn.execute.assert_called_once()
    sql_called = conn.execute.call_args[0][0]
    assert "chain_state" in sql_called


def test_publish_anchor_payload_contient_champs_requis():
    """Le payload POST contient last_seq, last_hash, timestamp et signature_ed25519."""
    from deedbook.anchor import publish_anchor

    conn = _make_conn(last_seq=5, last_hash="c" * 64)
    captured: list[dict] = []

    def fake_post(url, **kwargs):
        captured.append(kwargs["json"])
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    with patch("deedbook.anchor.httpx") as mock_httpx:
        mock_httpx.post.side_effect = fake_post
        key = _signing_key_b64()
        publish_anchor(conn, anchor_url="http://localhost/anchor", signing_key_b64=key)

    assert len(captured) == 1
    payload = captured[0]
    assert payload["last_seq"] == 5
    assert payload["last_hash"] == "c" * 64
    assert "timestamp" in payload
    assert "signature_ed25519" in payload


def test_publish_anchor_signature_verifiable():
    """La signature Ed25519 du payload est vérifiable avec la clé publique dérivée."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from deedbook.anchor import publish_anchor

    seed_b64 = _signing_key_b64()
    seed = base64.b64decode(seed_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key()

    conn = _make_conn(last_seq=2, last_hash="d" * 64)
    captured: list[dict] = []

    def fake_post(url, **kwargs):
        captured.append(kwargs["json"])
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    with patch("deedbook.anchor.httpx") as mock_httpx:
        mock_httpx.post.side_effect = fake_post
        publish_anchor(conn, anchor_url="http://localhost/anchor", signing_key_b64=seed_b64)

    payload = captured[0]
    sig = base64.b64decode(payload["signature_ed25519"])
    message = json.dumps(
        {k: v for k, v in payload.items() if k != "signature_ed25519"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    public_key.verify(sig, message)


def test_publish_anchor_silencieux_si_indisponible():
    """Une erreur réseau n'interrompt pas l'appelant."""
    from deedbook.anchor import publish_anchor

    conn = _make_conn()
    with patch("deedbook.anchor.httpx") as mock_httpx:
        mock_httpx.post.side_effect = OSError("connection refused")
        key = _signing_key_b64()
        publish_anchor(conn, anchor_url="http://localhost/anchor", signing_key_b64=key)


def test_publish_anchor_silencieux_si_url_none():
    """Si anchor_url est None, publish_anchor retourne sans appel réseau."""
    from deedbook.anchor import publish_anchor

    conn = _make_conn()
    with patch("deedbook.anchor.httpx") as mock_httpx:
        publish_anchor(conn, anchor_url=None, signing_key_b64=_signing_key_b64())
        mock_httpx.post.assert_not_called()
    conn.execute.assert_not_called()


def test_publish_anchor_silencieux_si_http_erreur():
    """Un statut HTTP 5xx n'interrompt pas l'appelant."""
    import httpx as real_httpx

    from deedbook.anchor import publish_anchor

    conn = _make_conn()
    with patch("deedbook.anchor.httpx") as mock_httpx:
        mock_httpx.post.return_value.raise_for_status.side_effect = real_httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        key = _signing_key_b64()
        publish_anchor(conn, anchor_url="http://localhost/anchor", signing_key_b64=key)


def test_cmd_anchor_appelle_publish_anchor():
    """La commande CLI 'deedbook anchor' appelle publish_anchor."""
    from deedbook.cli import main

    with (
        patch("deedbook.anchor.publish_anchor") as mock_pub,
        patch("deedbook.admin.connect") as mock_connect,
        patch("deedbook.admin.database_url", return_value="postgresql://x"),
        patch(
            "deedbook.config.get_settings",
            return_value=MagicMock(
                anchor_url="http://localhost/anchor",
                signing_key=MagicMock(get_secret_value=lambda: _signing_key_b64()),
            ),
        ),
    ):
        mock_connect.return_value.__enter__ = lambda s, *a: MagicMock()
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        result = main(["anchor"])

    assert result == 0
    mock_pub.assert_called_once()


def test_cmd_anchor_retourne_0_si_anchor_url_absente():
    """'deedbook anchor' retourne 0 si anchor_url absente."""
    from deedbook.cli import main

    with patch(
        "deedbook.config.get_settings",
        return_value=MagicMock(anchor_url=None),
    ):
        result = main(["anchor"])

    assert result == 0
