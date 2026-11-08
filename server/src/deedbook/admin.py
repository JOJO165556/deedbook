"""Provisioning : `init` (migrations, rôles, secrets), `doctor`, `project add`."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

ROLE_INGEST = "deedbook_ingest"
ROLE_READ = "deedbook_read"
ROLE_MIGRATE = "deedbook_migrate"

AUDIT_TABLES = ["audit_events", "audit_batches"]

APP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def database_url() -> str:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    url = os.environ.get("DEEDBOOK_DATABASE_URL")
    if not url:
        raise SystemExit(
            "DEEDBOOK_DATABASE_URL manquant - renseignez .env "
            "(voir .env.example) avant de lancer cette commande"
        )
    return url


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or database_url())


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Applique les fichiers SQL non encore joués, dans l'ordre."""
    conn.execute("CREATE SCHEMA IF NOT EXISTS deedbook")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS deedbook.schema_migrations (
               version text PRIMARY KEY,
               applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    applied = {
        row[0] for row in conn.execute("SELECT version FROM deedbook.schema_migrations")
    }
    ran = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO deedbook.schema_migrations (version) VALUES (%s)",
                (path.name,),
            )
        ran.append(path.name)
    return ran


def _role_exists(conn: psycopg.Connection, role: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone() is not None


def _create_login_role(conn: psycopg.Connection, role: str) -> str:
    """Crée un rôle LOGIN avec mot de passe aléatoire. Retourne le mot de passe."""
    password = secrets.token_urlsafe(24)
    conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )
    return password


def role_dsn(base_dsn: str, role: str, password: str) -> str:
    """Reconstruit une URL postgresql:// pour un rôle donné."""
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(base_dsn)
    host = info.get("host", "localhost")
    port = info.get("port", "5432")
    dbname = info.get("dbname") or info.get("database", "")
    return f"postgresql://{quote(role, safe='')}:{quote(password, safe='')}@{host}:{port}/{dbname}"


def _read_env_file() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def _b64_key(nbytes: int) -> str:
    return base64.b64encode(secrets.token_bytes(nbytes)).decode()


def _ed25519_seed() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return base64.b64encode(seed).decode()


def init() -> int:
    dsn = database_url()
    env = os.environ
    existing = {
        **_read_env_file(),
        **{k: v for k, v in env.items() if k.startswith("DEEDBOOK_")},
    }

    with connect(dsn) as conn:
        ran = apply_migrations(conn)
        print(f"Migrations appliquées : {ran or 'aucune (déjà à jour)'}")

        new_passwords: dict[str, str] = {}
        for role in (ROLE_INGEST, ROLE_READ):
            if _role_exists(conn, role):
                print(f"Rôle {role} : déjà présent, mot de passe inchangé")
            else:
                new_passwords[role] = _create_login_role(conn, role)
                print(f"Rôle {role} : créé")
        if not _role_exists(conn, ROLE_MIGRATE):
            conn.execute(
                sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(ROLE_MIGRATE))
            )
            print(f"Rôle {ROLE_MIGRATE} : créé (NOLOGIN)")
        else:
            print(f"Rôle {ROLE_MIGRATE} : déjà présent")

        for table in AUDIT_TABLES:
            conn.execute(
                sql.SQL("GRANT INSERT ON deedbook.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(ROLE_INGEST)
                )
            )
            conn.execute(
                sql.SQL("GRANT SELECT ON deedbook.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(ROLE_READ)
                )
            )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA deedbook TO {}, {}").format(
                sql.Identifier(ROLE_INGEST), sql.Identifier(ROLE_READ)
            )
        )
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA deedbook TO {}").format(
                sql.Identifier(ROLE_INGEST)
            )
        )

    secrets_block = []
    signing_key = existing.get("DEEDBOOK_SIGNING_KEY") or _ed25519_seed()
    hmac_key = existing.get("DEEDBOOK_HMAC_KEY") or _b64_key(32)
    admin_token = existing.get("DEEDBOOK_ADMIN_TOKEN") or _b64_key(32)

    secrets_block += [
        f"DEEDBOOK_SIGNING_KEY={signing_key}",
        f"DEEDBOOK_HMAC_KEY={hmac_key}",
        f"DEEDBOOK_ADMIN_TOKEN={admin_token}",
    ]
    for role, password in new_passwords.items():
        env_name = "DEEDBOOK_INGEST_URL" if role == ROLE_INGEST else "DEEDBOOK_READ_URL"
        secrets_block.append(f"{env_name}={role_dsn(dsn, role, password)}")

    print()
    print("Secrets à copier dans .env (affichés une seule fois) :")
    for line in secrets_block:
        print(f"  {line}")
    print()
    if not new_passwords:
        print("Les URLs des rôles existants ne sont pas réaffichées :")
        print("  si perdues, réinitialiser avec ALTER ROLE <rôle> PASSWORD '...' dans psql")
    return 0


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "OK " if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return ok


def _check_anchor(url: str) -> None:
    """HEAD sur l'URL d'ancrage ; seuls http/https sont acceptés."""
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme == "https":
        conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=3)
    elif parsed.scheme == "http":
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=3)
    else:
        raise ValueError(f"schéma non supporté : {parsed.scheme}")
    try:
        conn.request("HEAD", parsed.path or "/")
        response = conn.getresponse()
        response.read()
        if response.status >= 400:
            raise OSError(f"HTTP {response.status}")
    finally:
        conn.close()


def doctor() -> int:
    from deedbook.config import ConfigError, get_settings

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(exc)
        return 1

    results: list[bool] = []
    print("Configuration :")
    results.append(_check("variables d'environnement", True))

    try:
        with connect(settings.database_url.get_secret_value()) as conn:
            conn.execute("SELECT 1")
            results.append(_check("connexion base de données", True))

            pending = [
                p.name
                for p in sorted(MIGRATIONS_DIR.glob("*.sql"))
                if conn.execute(
                    "SELECT 1 FROM deedbook.schema_migrations WHERE version = %s",
                    (p.name,),
                ).fetchone()
                is None
            ]
            results.append(
                _check(
                    "migrations",
                    not pending,
                    f"en attente : {pending}" if pending else "à jour",
                )
            )

            for role in (ROLE_INGEST, ROLE_READ, ROLE_MIGRATE):
                results.append(
                    _check(f"rôle {role}", _role_exists(conn, role))
                )

            for table in AUDIT_TABLES:
                q = "deedbook." + table
                can_insert = conn.execute(
                    "SELECT has_table_privilege(%s, %s, 'INSERT')",
                    (ROLE_INGEST, q),
                ).fetchone()[0]
                can_delete = conn.execute(
                    "SELECT has_table_privilege(%s, %s, 'DELETE')",
                    (ROLE_INGEST, q),
                ).fetchone()[0]
                can_select = conn.execute(
                    "SELECT has_table_privilege(%s, %s, 'SELECT')",
                    (ROLE_READ, q),
                ).fetchone()[0]
                results.append(
                    _check(
                        f"droits {table}",
                        can_insert and not can_delete and can_select,
                        f"ingest INSERT={can_insert} DELETE={can_delete}, "
                        f"read SELECT={can_select}",
                    )
                )

            db_now = conn.execute("SELECT now()").fetchone()[0]
            import datetime as dt

            skew = abs((db_now - dt.datetime.now(dt.UTC)).total_seconds())
            results.append(
                _check("horloge synchronisée", skew < 30, f"écart {skew:.1f}s")
            )
    except Exception as exc:
        results.append(_check("connexion base de données", False, str(exc)))

    anchor = settings.anchor_url
    if anchor:
        try:
            _check_anchor(anchor)
            results.append(_check("destination d'ancrage", True))
        except Exception as exc:
            results.append(_check("destination d'ancrage", False, str(exc)))
    else:
        print("  [-- ] destination d'ancrage : non configurée (optionnel)")

    print()
    if all(results):
        print("doctor : tout est en ordre")
        return 0
    print("doctor : des vérifications ont échoué")
    return 1


def add_project(name: str) -> int:
    if not APP_NAME_RE.match(name):
        print("Nom invalide : minuscules, chiffres, '_' et '-' uniquement (1-63 car.)")
        return 1
    dsn = database_url()
    token = "dbk_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect(dsn) as conn:
        conn.execute(
            """INSERT INTO deedbook.apps (name, token_hash)
               VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE
               SET token_hash = EXCLUDED.token_hash, active = true""",
            (name, token_hash),
        )
    print(f"Projet {name!r} enregistré")
    print(f"Jeton d'ingestion (affiché une seule fois) : {token}")
    return 0
