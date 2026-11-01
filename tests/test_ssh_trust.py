"""Exercise real controller-only Ansible tasks with disposable inventory and homes."""

import base64
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCAL_POPEN = subprocess.Popen


def public_key(seed=0):
    kind = b"ssh-ed25519"
    wire = struct.pack(">I", len(kind)) + kind + struct.pack(">I", 32) + bytes([seed]) * 32
    return "ssh-ed25519 " + base64.b64encode(wire).decode()


@pytest.fixture
def controller(tmp_path, monkeypatch):
    # The harness invokes only local Ansible/ssh-keygen processes. Target hosts
    # use documentation-only addresses; preparation must never contact them.
    monkeypatch.setattr(subprocess, "Popen", LOCAL_POPEN)
    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "ansible.cfg"
    config.write_text(
        "[defaults]\n"
        f"roles_path = {ROOT / 'roles'}\n"
        f"collections_path = {ROOT / '.collections'}\n"
        "host_key_checking = True\n"
        "retry_files_enabled = False\n"
    )
    play = tmp_path / "prepare.yml"
    play.write_text((ROOT / "playbooks/prepare-ssh-trust.yml").read_text())
    env = {key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")}
    env.update(HOME=str(home), ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR="1")
    inventory = tmp_path / "inventory.yml"

    def run(hosts, check=True):
        inventory.write_text(yaml.safe_dump({"all": {"hosts": hosts}}))
        args = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", str(inventory), str(play)]
        if check:
            args.append("--check")
        return subprocess.run(  # noqa: S603 -- Fixed local harness, disposable inputs, no remote tasks.
            args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
        )

    return tmp_path, home, run


def host(seed=0, **extra):
    return {"ansible_host": "192.0.2.10", "ssh_host_public_key": public_key(seed), **extra}


def test_empty_cache_and_fresh_controller_recover_in_check_mode(controller):
    directory, home, run = controller
    result = run({"node": host()})
    assert result.returncode == 0, result.stdout + result.stderr
    cache = directory / ".cache/ssh/known_hosts"
    installed = home / ".ssh/known_hosts"
    expected = f"192.0.2.10 {public_key()}\n"
    assert cache.read_text() == installed.read_text() == expected
    assert cache.stat().st_mode & 0o777 == installed.stat().st_mode & 0o777 == 0o600
    assert cache.parent.stat().st_mode & 0o777 == installed.parent.stat().st_mode & 0o777 == 0o700
    repeat = run({"node": host()}, check=False)
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert "changed=0" in repeat.stdout
    # Simulate a deleted trust cache plus a completely new container home.
    shutil.rmtree(directory / ".cache")
    shutil.rmtree(home / ".ssh")
    recovered = run({"node": host()})
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert cache.read_text() == installed.read_text() == expected


def test_aliases_ports_multiple_hosts_and_unrelated_trust_are_preserved(controller):
    directory, home, run = controller
    installed = home / ".ssh/known_hosts"
    installed.parent.mkdir()
    unrelated = f"unrelated.example.test {public_key(9)}\n"
    installed.write_text(unrelated)
    hosts = {
        "node": host(ssh_trust_names=["192.0.2.10", "node.example.test"], ansible_port=2222),
        "second": host(1, ansible_host="192.0.2.11"),
    }
    result = run(hosts)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        f"[192.0.2.10]:2222 {public_key()}",
        f"[node.example.test]:2222 {public_key()}",
        f"192.0.2.11 {public_key(1)}",
    }
    assert set((directory / ".cache/ssh/known_hosts").read_text().splitlines()) == expected
    assert set(installed.read_text().splitlines()) == expected | {unrelated.strip()}


@pytest.mark.parametrize("key", ["ssh-ed25519 AAAA", public_key() + "\ninjected", "@cert-authority " + public_key()])
def test_invalid_keys_are_refused_before_writing_trust(controller, key):
    directory, home, run = controller
    result = run({"node": host(ssh_host_public_key=key)})
    assert result.returncode != 0
    assert not (directory / ".cache/ssh").exists()
    assert not (home / ".ssh").exists()


def test_unenrolled_hosts_keep_their_existing_workflow(controller):
    directory, home, run = controller
    result = run({"node": {"ansible_host": "192.0.2.10"}})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (directory / ".cache/ssh").exists()
    assert not (home / ".ssh").exists()


def test_preparation_does_not_require_vault_device_credentials(controller):
    directory, home, run = controller
    result = run(
        {
            "switch": host(
                ansible_connection="ansible.netcommon.network_cli",
                ansible_user="{{ vault_devices[inventory_hostname].username }}",
                ansible_password="{{ vault_devices[inventory_hostname].ssh_password }}",  # noqa: S106 -- Unresolved template, not a credential.
                ansible_become_password="{{ vault_devices[inventory_hostname].enable_password }}",  # noqa: S106 -- Unresolved template, not a credential.
            )
        }
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (directory / ".cache/ssh/known_hosts").read_text() == (home / ".ssh/known_hosts").read_text()


def test_ssh_facing_roles_prepare_trust_before_their_operations():
    roles = {
        "cisco_switch",
        "proxmox_api",
        "proxmox_host",
        "opnsense_vm",
        "fedora_dev",
        "unifi_vm",
        "opnsense_install",
        "opnsense_pilot",
        "opnsense_api",
        "opnsense_lab",
        "opnsense_wireguard",
        "opnsense_wireguard_wifi",
        "fedora_host",
        "unifi_host",
        "unifi_site",
        "unifi_network",
    }
    for role in roles:
        dependencies = yaml.safe_load((ROOT / "roles" / role / "meta/main.yml").read_text())["dependencies"]
        assert dependencies == [
            {
                "role": "ssh_trust",
                "ssh_trust_options": {"task_action": "prepare"},
                "when": "ssh_host_public_key is defined",
                "tags": ["always"],
            }
        ]
