import configparser
from pathlib import Path

import pytest


@pytest.fixture
def checks(load_module):
    return load_module("tools/repository_checks.py")


@pytest.fixture
def runner(checks, load_module, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "repository_checks", checks)
    return load_module("tools/validate.py")


@pytest.mark.parametrize(
    "name",
    [
        "inventory.private.yml",
        "secrets/credentials.yml",
        "backups/config.xml",
        ".cache/key.json",
        ".venv-macos/bin/python",
        ".venv-validation/bin/python",
        "client.unf",
        "client.pem",
        ".env",
        ".vault-pass",
        ".ssh/id_ed25519",
    ],
)
def test_private_source_paths_are_rejected(checks, name):
    assert checks.private_path(Path(name))


@pytest.mark.parametrize(
    "name",
    [
        "inventory.example.yml",
        ".env.example",
        "files/opnsense/26.7.pub",
        "files/ubuntu-cloud-image-signing-key.asc",
        "tests/test_wireguard_keys.py",
    ],
)
def test_public_examples_signing_keys_and_tests_are_allowed(checks, name):
    assert not checks.private_path(Path(name))


def test_duplicate_yaml_keys_are_not_silently_discarded(checks, tmp_path):
    fixture = tmp_path / "duplicate.yml"
    fixture.write_text("all:\n  hosts: {}\n  hosts: {other: {}}\n")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        checks.load_yaml(fixture)


def test_operator_overrides_cannot_redirect_validation(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("ANSIBLE_CONFIG", "/private/operator-config")
    monkeypatch.setenv("ANSIBLE_INVENTORY", "/private/inventory")
    monkeypatch.setenv("ANSIBLE_VAULT_PASSWORD_FILE", "/private/password")
    monkeypatch.setenv("ANSIBLE_CALLBACK_PLUGINS", "/private/callbacks")
    monkeypatch.setenv("GITLEAKS_CONFIG", "/private/disabled-rules")
    env = runner.validation_environment(tmp_path)
    assert "ANSIBLE_INVENTORY" not in env and "ANSIBLE_VAULT_PASSWORD_FILE" not in env
    assert "ANSIBLE_CALLBACK_PLUGINS" not in env and "GITLEAKS_CONFIG" not in env
    config = configparser.ConfigParser()
    config.read(env["ANSIBLE_CONFIG"])
    assert config["defaults"]["inventory"].endswith("/inventory.example.yml")
    assert config.getboolean("defaults", "ask_vault_pass") is False
    assert Path(env["HOME_VALIDATION_VAULT"]).read_text() == "vault_devices: {}\n"


@pytest.mark.parametrize("name", ["secrets/credentials.yml", "inventory.private.yml", "../outside", "/absolute/source"])
def test_secret_scanner_refuses_unsafe_input_before_copy(runner, tmp_path, name):
    with pytest.raises(ValueError, match="Refusing to scan"):
        runner.secret_checks([Path(name)], {}, tmp_path)
    assert not (tmp_path / "public-source").exists()
