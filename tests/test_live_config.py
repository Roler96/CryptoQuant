"""Credential loading: demo and live are separate, and secrets never print."""

import pytest

from cq.live.config import CredentialsError, OkxCredentials

DEMO_VARS = {
    "OKX_SANDBOX_API_KEY": "demo-key-abcd",
    "OKX_SANDBOX_API_SECRET": "demo-secret",
    "OKX_SANDBOX_PASSPHRASE": "demo-pass",
}


@pytest.fixture
def empty_env_file(tmp_path):
    # An empty .env so `load_dotenv` reads nothing and the test controls the
    # environment entirely through monkeypatch.
    path = tmp_path / ".env"
    path.write_text("")
    return path


def test_loads_demo_credentials_from_the_environment(monkeypatch, empty_env_file):
    for key, value in DEMO_VARS.items():
        monkeypatch.setenv(key, value)
    creds = OkxCredentials.from_env(demo=True, env_path=empty_env_file)
    assert creds.demo is True
    assert creds.api_key == DEMO_VARS["OKX_SANDBOX_API_KEY"]
    assert creds.secret == DEMO_VARS["OKX_SANDBOX_API_SECRET"]
    assert creds.passphrase == DEMO_VARS["OKX_SANDBOX_PASSPHRASE"]


def test_demo_and_live_read_different_variables(monkeypatch, empty_env_file):
    monkeypatch.setenv("OKX_API_KEY", "live-key")
    monkeypatch.setenv("OKX_API_SECRET", "live-secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "live-pass")
    for key in DEMO_VARS:
        monkeypatch.delenv(key, raising=False)

    live = OkxCredentials.from_env(demo=False, env_path=empty_env_file)
    assert live.demo is False
    assert live.api_key == "live-key"

    # With no demo keys present, asking for demo must fail rather than fall back
    # to the live keys it can see.
    with pytest.raises(CredentialsError):
        OkxCredentials.from_env(demo=True, env_path=empty_env_file)


def test_missing_credential_is_a_hard_error(monkeypatch, empty_env_file):
    monkeypatch.setenv("OKX_SANDBOX_API_KEY", "only-the-key")
    monkeypatch.delenv("OKX_SANDBOX_API_SECRET", raising=False)
    monkeypatch.delenv("OKX_SANDBOX_PASSPHRASE", raising=False)
    with pytest.raises(CredentialsError) as exc:
        OkxCredentials.from_env(demo=True, env_path=empty_env_file)
    assert "OKX_SANDBOX_API_SECRET" in str(exc.value)


def test_blank_credential_counts_as_missing(monkeypatch, empty_env_file):
    for key in DEMO_VARS:
        monkeypatch.setenv(key, "   ")
    with pytest.raises(CredentialsError):
        OkxCredentials.from_env(demo=True, env_path=empty_env_file)


def test_repr_does_not_leak_the_secret():
    creds = OkxCredentials("key-1234567890", "super-secret", "passphrase", demo=True)
    text = repr(creds)
    assert "super-secret" not in text
    assert "passphrase" not in text
    assert "7890" in text  # last four of the key, for identification
