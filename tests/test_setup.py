import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup(load_module):
    return load_module("tools/setup.py")


def test_existing_environment_keeps_ssh_before_dependency_lock(setup, tmp_path, monkeypatch):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps([str(python.parent.parent), [3, 12]]))

    monkeypatch.setattr(setup, "run", run)
    assert setup.prepare_environment(python.parent.parent, "requirements.txt") == python
    assert not any("venv" in call for call in calls)
    assert calls[1][1].endswith("install-ssh.py")
    assert calls[2][1:4] == ["-m", "pip", "install"]
    assert "--require-hashes" in calls[2]
    assert calls[-1][1].endswith("check-ssh.py")


def test_wrong_environment_is_not_overwritten(setup, tmp_path, monkeypatch):
    python = tmp_path / "bin/python"
    python.parent.mkdir()
    python.touch()
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps(["/another/environment", [3, 12]]))

    monkeypatch.setattr(setup, "run", run)
    with pytest.raises(ValueError, match="move it aside"):
        setup.prepare_environment(tmp_path, "requirements.txt")
    assert len(calls) == 1


def test_only_missing_system_packages_are_installed(setup, monkeypatch):
    monkeypatch.setattr(setup.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu"})
    monkeypatch.setattr(setup.os, "geteuid", lambda: 1000)
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="" if argv[-1] == "php-xml" else "install ok installed")

    monkeypatch.setattr(setup, "run", run)
    setup.system_dependencies("Linux")
    assert [call for call in calls if call[0] == "sudo"] == [
        ["sudo", "apt-get", "update"],
        ["sudo", "apt-get", "install", "--yes", "--no-install-recommends", "php-xml"],
    ]


@pytest.mark.parametrize("system,suffix", [("Linux", ""), ("Darwin", "-macos")])
def test_shared_setup_selects_native_environments_and_isolates_ansible(setup, tmp_path, monkeypatch, system, suffix):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup.platform, "system", lambda: system)
    monkeypatch.setattr(setup, "system_dependencies", lambda _: None)
    environments = []

    def environment(path, lock):
        (path / "bin").mkdir(parents=True)
        environments.append((path.name, lock))
        return path / "bin/python"

    monkeypatch.setattr(setup, "prepare_environment", environment)
    monkeypatch.setattr(setup, "native_tools_ready", lambda: True)
    monkeypatch.setenv("ANSIBLE_INVENTORY", "/private/inventory")
    monkeypatch.setenv("ANSIBLE_VAULT_PASSWORD_FILE", "/private/password")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        env = kwargs["env"]
        assert "ANSIBLE_INVENTORY" not in env and "ANSIBLE_VAULT_PASSWORD_FILE" not in env
        assert (
            Path(env["ANSIBLE_CONFIG"]).read_text() == f"[defaults]\ncollections_path = {tmp_path / '.collections'}\n"
        )

    monkeypatch.setattr(setup, "run", run)
    setup.main()
    assert environments == [
        (".venv" + suffix, "requirements.txt"),
        (".venv-validation" + suffix, "requirements-dev.txt"),
    ]
    assert len(calls) == 1 and calls[0][1:3] == ["collection", "install"]


def test_native_tools_repaired_when_missing(setup, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup, "system_dependencies", lambda _: None)

    def environment(path, _):
        (path / "bin").mkdir(parents=True)
        return path / "bin/python"

    monkeypatch.setattr(setup, "prepare_environment", environment)
    observations = iter([False, True])
    monkeypatch.setattr(setup, "native_tools_ready", lambda: next(observations))
    calls = []
    monkeypatch.setattr(setup, "run", lambda argv, **_: calls.append(argv))
    setup.main()
    assert calls[-1] == [
        str(tmp_path / ".venv-validation/bin/python"),
        str(tmp_path / "tools/install-validation-tools.py"),
    ]


def test_new_environment_created_before_ssh_build(setup, tmp_path, monkeypatch):
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps([str(tmp_path), [3, 12]]))

    monkeypatch.setattr(setup, "run", run)
    setup.prepare_environment(tmp_path, "requirements.txt")
    assert calls[0] == [setup.sys.executable, "-m", "venv", str(tmp_path)]
    assert calls[2][1].endswith("install-ssh.py")


def test_satisfied_system_packages_skip_apt(setup, monkeypatch):
    monkeypatch.setattr(setup.platform, "freedesktop_os_release", lambda: {"ID": "debian"})
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="install ok installed")

    monkeypatch.setattr(setup, "run", run)
    setup.system_dependencies("Linux")
    assert all("apt-get" not in call for call in calls)
    assert calls[-1] == ["bash", str(setup.ROOT / "tools/install-php.sh")]
