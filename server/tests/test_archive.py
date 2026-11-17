"""Tests pour l'archivage scellé et la purge contrôlée (archive.py)."""

from __future__ import annotations

import base64
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _signing_key_b64() -> str:
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return base64.b64encode(seed).decode()


def _make_events(n: int = 3) -> list[dict]:
    return [
        {
            "event_id": f"evt-{i}",
            "integrity_seq": i,
            "event_hash": "a" * 64,
            "occurred_at": "2024-01-01T00:00:00+00:00",
            "app": "test",
            "action": "read",
        }
        for i in range(1, n + 1)
    ]


class _Col:
    def __init__(self, name: str) -> None:
        self._name = name

    def __getitem__(self, i: int) -> str:
        return self._name if i == 0 else ""


def _make_conn(events: list[dict] | None = None) -> MagicMock:
    conn = MagicMock()
    rows = events or _make_events()

    fetchall_result = [list(r.values()) for r in rows]

    cursor = conn.execute.return_value
    cursor.fetchall.return_value = fetchall_result
    cursor.fetchone.return_value = None
    cursor.description = [_Col(k) for k in rows[0]]
    return conn


def test_archive_before_cree_fichier_json():
    """archive_before produit un fichier JSON dans le chemin indiqué."""
    from deedbook.archive import archive_before

    conn = _make_conn()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "archive.json"
        archive_before(
            conn,
            before=date(2025, 1, 1),
            signing_key_b64=_signing_key_b64(),
            output_path=out,
        )
        assert out.exists()


def test_archive_before_contient_evenements_et_metadonnees():
    """Le fichier d'archive contient les événements, une signature et des métadonnées."""
    from deedbook.archive import archive_before

    events = _make_events(2)
    conn = _make_conn(events)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "archive.json"
        archive_before(
            conn,
            before=date(2025, 1, 1),
            signing_key_b64=_signing_key_b64(),
            output_path=out,
        )
        data = json.loads(out.read_text())
        assert "events" in data
        assert "signature_ed25519" in data
        assert "archived_at" in data
        assert "before" in data
        assert len(data["events"]) == 2


def test_archive_before_signature_verifiable():
    """La signature Ed25519 de l'archive est vérifiable avec la clé publique."""
    from deedbook.archive import archive_before

    seed_b64 = _signing_key_b64()
    seed = base64.b64decode(seed_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key()

    conn = _make_conn()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "archive.json"
        archive_before(
            conn,
            before=date(2025, 1, 1),
            signing_key_b64=seed_b64,
            output_path=out,
        )
        data = json.loads(out.read_text())
        sig = base64.b64decode(data["signature_ed25519"])
        payload = {k: v for k, v in data.items() if k != "signature_ed25519"}
        message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        public_key.verify(sig, message)


def test_archive_before_retourne_zero_si_aucun_evenement():
    """archive_before retourne 0 et ne crée pas de fichier si rien a archiver."""
    from deedbook.archive import archive_before

    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "archive.json"
        count = archive_before(
            conn,
            before=date(2025, 1, 1),
            signing_key_b64=_signing_key_b64(),
            output_path=out,
        )
        assert count == 0
        assert not out.exists()


def test_archive_before_retourne_nombre_evenements():
    """archive_before retourne le nombre d'événements archivés."""
    from deedbook.archive import archive_before

    conn = _make_conn(_make_events(5))
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "archive.json"
        count = archive_before(
            conn,
            before=date(2025, 1, 1),
            signing_key_b64=_signing_key_b64(),
            output_path=out,
        )
        assert count == 5


def test_cmd_archive_subcommand_existe():
    """La commande 'deedbook archive' est enregistrée dans le CLI."""
    import pytest

    from deedbook.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["archive", "--help"])
    assert exc.value.code == 0


def _make_conn_with_checkpoint(events: list[dict] | None = None) -> MagicMock:
    """Connexion mock qui retourne des evenements ET simule les appels checkpoint."""
    conn = _make_conn(events)
    conn.execute.return_value.fetchone.return_value = None
    return conn


def test_save_checkpoint_insere_en_base():
    """save_checkpoint insere un enregistrement dans archive_checkpoints."""
    from deedbook.archive import save_checkpoint

    conn = MagicMock()
    before = date(2025, 1, 1)
    save_checkpoint(
        conn,
        archived_before=before,
        event_count=10,
        last_seq=42,
        last_hash="a" * 64,
        archive_path="/var/lib/deedbook/archive.json",
    )
    conn.execute.assert_called_once()
    sql, params = conn.execute.call_args[0]
    assert "archive_checkpoints" in sql
    assert params[0] == before
    assert params[1] == 10
    assert params[2] == 42


def test_purge_archived_sans_checkpoint_leve_erreur():
    """purge_archived refuse de purger si aucun checkpoint n'existe pour cette date."""
    from deedbook.archive import purge_archived

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    import pytest

    with pytest.raises(ValueError, match="aucun checkpoint"):
        purge_archived(conn, before=date(2025, 1, 1))


def test_purge_archived_avec_checkpoint_supprime_evenements():
    """purge_archived supprime les evenements anterieurs si un checkpoint existe."""
    from deedbook.archive import purge_archived

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    conn.execute.return_value.rowcount = 5

    count = purge_archived(conn, before=date(2025, 1, 1))
    assert count == 5


def test_cmd_purge_subcommand_existe():
    """La commande 'deedbook purge' est enregistrée dans le CLI."""
    import pytest

    from deedbook.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["purge", "--help"])
    assert exc.value.code == 0
