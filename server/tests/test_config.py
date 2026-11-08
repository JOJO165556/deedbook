import pytest

from deedbook.config import ConfigError, Settings, get_settings, load_policy

REQUIRED = {
    "DEEDBOOK_DATABASE_URL": "postgresql://u:p@localhost:5432/db",
    "DEEDBOOK_SIGNING_KEY": "c2lnbmluZy1rZXk=",
    "DEEDBOOK_HMAC_KEY": "aG1hYy1rZXk=",
    "DEEDBOOK_ADMIN_TOKEN": "dG9rZW4=",
}


@pytest.fixture
def clean_env(monkeypatch):
    # Ignore le .env réel du dépôt : les tests ne dépendent que des variables
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_settings_valid(clean_env):
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.port == 8000


def test_missing_vars_refuse_start(clean_env):
    with pytest.raises(ConfigError) as exc:
        get_settings()
    message = str(exc.value)
    assert "DEEDBOOK_DATABASE_URL" in message
    assert "DEEDBOOK_SIGNING_KEY" in message


def test_empty_env_file_does_not_mask_os_env(clean_env):
    """Un .env.example vide ne doit pas être chargé comme .env."""
    clean_env.setenv("DEEDBOOK_DATABASE_URL", REQUIRED["DEEDBOOK_DATABASE_URL"])
    with pytest.raises(ConfigError):
        get_settings()


def test_policy_loads_without_secrets():
    policy = load_policy()
    assert policy["project"]["name"] == "deedbook"
    assert policy["modules"]["enabled"] == []
