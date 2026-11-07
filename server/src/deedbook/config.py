"""Configuration stricte du moteur deedbook.

Règle : les secrets vivent exclusivement dans les variables d'environnement,
la politique (non secrète) dans `deedbook.toml`. Le serveur refuse de
démarrer si quelque chose manque.
"""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "deedbook.toml"


class Settings(BaseSettings):
    """Secrets et réglages d'exécution, tous sourcés depuis l'environnement."""

    model_config = SettingsConfigDict(
        env_prefix="DEEDBOOK_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(min_length=1)
    signing_key: SecretStr = Field(min_length=1)
    hmac_key: SecretStr = Field(min_length=1)
    admin_token: SecretStr = Field(min_length=1)
    anchor_url: str | None = None
    port: int = 8000


def load_policy(path: Path = POLICY_PATH) -> dict:
    """Charge la politique projet depuis deedbook.toml (sans secret)."""
    with path.open("rb") as f:
        return tomllib.load(f)


class ConfigError(SystemExit):
    """Levée quand la configuration est incomplète ou invalide."""

    def __init__(self, missing: list[str]):
        names = ", ".join(sorted(missing))
        super().__init__(
            f"Configuration incomplète — variables manquantes : {names}\n"
            "Copiez .env.example en .env puis lancez `deedbook init`."
        )


def get_settings() -> Settings:
    """Retourne les settings ou refuse de démarrer en listant le manque."""
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as exc:
        missing = sorted(
            err["loc"][0].upper()
            for err in exc.errors()
            if err["type"] == "missing" and err.get("loc")
        )
        raise ConfigError([f"DEEDBOOK_{name}" for name in missing]) from exc


@lru_cache(maxsize=1)
def policy() -> dict:
    return load_policy()
