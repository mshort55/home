import base64
import json
from types import SimpleNamespace

import pytest
from ansible.errors import AnsibleActionFail, AnsibleError
from ansible.parsing.vault import VaultLib, VaultSecret


@pytest.fixture
def keys(load_module):
    return load_module("plugins/action/wireguard_keys.py")


@pytest.fixture
def settings():
    return {
        "tunnel_subnet": "10.77.99.0/24",
        "management_subnet": "10.77.10.0/24",
        "endpoint": "10.77.200.254",
        "server_address": "10.77.99.1",
        "peer_address": "10.77.99.2",
        "management_address": "10.77.10.254",
        "proxmox_address": "10.77.10.10",
        "switch_address": "10.77.10.2",
    }


@pytest.fixture
def action(keys, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(keys.ActionBase, "run", lambda *args: {})
    value = object.__new__(keys.ActionModule)
    value._task = SimpleNamespace(
        args={"directory": str(tmp_path / "keys"), "identity": "opnsense01", "settings": settings}, check_mode=False
    )
    value._loader = SimpleNamespace(_vault=VaultLib([("default", VaultSecret(b"synthetic-test-password"))]))
    return value


def test_encrypted_creation_reuse_and_no_secret_output(keys, action, capsys):
    result = action.run()
    path = keys.Path(result["path"])
    encrypted = path.read_bytes()
    assert VaultLib.is_encrypted(encrypted)
    data = json.loads(action._loader._vault.decrypt(encrypted))
    keys.validate_pair(data["server"])
    keys.validate_pair(data["client"])
    assert data["server"]["public"] != data["client"]["public"]
    raw = base64.b64decode(data["server"]["private"])
    assert raw[0] & 7 == 0 and raw[31] & 128 == 0 and raw[31] & 64 == 64
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert action.run()["changed"] is False
    assert path.read_bytes() == encrypted
    assert "private" not in result and "public" not in result
    output = str(result) + str(capsys.readouterr())
    assert data["server"]["private"] not in output


def test_check_mode_creates_nothing(action):
    action._task.check_mode = True
    result = action.run()
    assert result["changed"] is True and result["exists"] is False
    assert not __import__("pathlib").Path(result["path"]).parent.exists()


@pytest.mark.parametrize(
    "kind",
    ["identity", "plaintext", "corrupt", "wrong_password", "missing_public", "mismatched_pair", "same_pair", "version"],
)
def test_saved_key_conflict_never_rotates(keys, action, kind):
    path = keys.Path(action.run()["path"])
    data = json.loads(action._loader._vault.decrypt(path.read_bytes()))
    if kind == "identity":
        action._task.args["identity"] = "other"
    elif kind == "plaintext":
        path.write_text(json.dumps(data))
    elif kind == "corrupt":
        path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nbroken\n")
    elif kind == "wrong_password":
        action._loader._vault = VaultLib([("default", VaultSecret(b"different-test-password"))])
    else:
        if kind == "missing_public":
            del data["server"]["public"]
        elif kind == "mismatched_pair":
            data["server"]["public"] = data["client"]["public"]
        elif kind == "same_pair":
            data["client"] = data["server"]
        else:
            data["version"] = 2
        path.write_bytes(action._loader._vault.encrypt(json.dumps(data)))
    before = path.read_bytes()
    with pytest.raises((AnsibleError, ValueError)):
        action.run()
    assert path.read_bytes() == before


def test_missing_keys_with_existing_client_is_not_repaired(keys, action):
    directory = keys.Path(action._task.args["directory"])
    directory.mkdir(mode=0o700)
    client = directory / "home-admin.conf"
    client.write_text("existing-client-identity")
    client.chmod(0o600)
    with pytest.raises(AnsibleActionFail, match="Restore the original"):
        action.run()
    assert not (directory / "keys.vault.yml").exists()


@pytest.mark.parametrize("kind", ["file_mode", "directory_mode", "symlink", "parent_symlink"])
def test_rejects_unprotected_paths(keys, action, tmp_path, kind):
    path = keys.Path(action.run()["path"])
    if kind == "file_mode":
        path.chmod(0o644)
    elif kind == "directory_mode":
        path.parent.chmod(0o755)
    elif kind == "symlink":
        saved = path.with_name("saved")
        path.rename(saved)
        path.symlink_to(saved)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(path.parent, target_is_directory=True)
        action._task.args["directory"] = str(alias)
    with pytest.raises(AnsibleActionFail):
        action.run()


@pytest.mark.parametrize(
    "field,value",
    [
        ("tunnel_subnet", "10.77.10.0/24"),
        ("server_address", "10.77.99.0"),
        ("peer_address", "10.77.99.1"),
        ("management_address", "10.77.11.1"),
        ("endpoint", "10.77.10.254"),
        ("management_subnet", "192.168.1.0/24"),
        ("tunnel_subnet", "10.77.99.0/25"),
    ],
)
def test_rejects_invalid_networks(keys, settings, field, value):
    settings[field] = value
    with pytest.raises(AnsibleActionFail):
        keys.validate_networks(settings)


@pytest.mark.parametrize("field,value", [("identity", "../escape"), ("directory", "relative/path"), ("settings", None)])
def test_rejects_bad_arguments(action, field, value):
    action._task.args[field] = value
    with pytest.raises(AnsibleActionFail):
        action.run()


def test_requires_unlocked_vault(action):
    action._loader._vault = VaultLib([])
    with pytest.raises(AnsibleActionFail, match="Unlock Ansible Vault"):
        action.run()


@pytest.mark.parametrize("bad", [None, {"private": "invalid", "public": "invalid"}])
def test_rejects_bad_pair(keys, bad):
    with pytest.raises(AnsibleActionFail):
        keys.validate_pair(bad)
