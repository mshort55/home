"""Exercise real guest inspectors with temporary records and mocked read-only commands."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.fixture(params=["fedora", "unifi"])
def guest(request, load_module, tmp_path, monkeypatch):
    kind = request.param
    module = load_module(f"scripts/inspect-{kind}-vm.py")
    vmid, vlan, cores, memory, disk, name = (
        (200, 30, 4, 8192, 80, "dev01") if kind == "fedora" else (110, 10, 2, 4096, 32, "unifi01")
    )
    allocation = {
        "vmid": vmid,
        "vlan": vlan,
        "cores": cores,
        "memory_mib": memory,
        "disk_gib": disk,
        "name": name,
        "address": f"10.77.{vlan}.20/24",
        "gateway": f"10.77.{vlan}.254",
        "dns": f"10.77.{vlan}.254",
        "domain": "lab.home.arpa",
        "storage": "local-lvm",
        "bridge": "vmbr1",
        "mac": "02:77:00:00:00:20",
    }
    directory = tmp_path / "record"
    directory.mkdir(mode=0o700)
    previous = {"version": 1, "phase": "complete", "allocation": deepcopy(allocation)}
    (directory / "intent.json").write_text(json.dumps(previous))
    (directory / "intent.json").chmod(0o600)
    config = {
        "name": name,
        "description": f"Managed by create-{kind}-vm.yml; vmid={vmid}"
        if kind == "unifi"
        else "Managed by create-fedora-dev-vm.yml; vmid=200",
        "cores": cores,
        "memory": str(memory),
        "sockets": 1,
        "onboot": 0 if kind == "fedora" else 1,
        "ostype": "l26",
        "scsihw": "virtio-scsi-single",
        "bios": "seabios",
        "serial0": "socket",
        "vga": "serial0",
        "agent": "enabled=1",
        "cicustom": f"user=home-cloudinit:snippets/{name}-user.yml",
        "ipconfig0": f"ip={allocation['address']},gw={allocation['gateway']}",
        "nameserver": allocation["dns"],
        "searchdomain": allocation["domain"],
        "net0": f"virtio={allocation['mac']},bridge=vmbr1,tag={vlan}",
        "scsi0": f"local-lvm:vm-{vmid}-disk-0,size={disk}G",
        "ide2": f"local-lvm:vm-{vmid}-cloudinit,media=cdrom",
        "boot": "order=scsi0",
    }
    if kind == "unifi":
        config.update(balloon=0, startup="order=2,up=30,down=120")
    state = {
        "resources": [{"vmid": vmid, "type": "qemu", "node": "pve01"}],
        "pending": [],
        "config": config,
        "status": "stopped",
        "storage": [
            {
                "storage": "local-lvm",
                "active": 1,
                "content": "images",
                "avail": 200 * 1024**3,
                "used": 100 * 1024**3,
                "total": 500 * 1024**3,
            }
        ],
        "bridges": [
            {"ifname": "vmbr1", "flags": ["UP"], "addr_info": [], "linkinfo": {"info_data": {"vlan_filtering": 1}}}
        ],
    }

    def read(*args):
        if args[0] == "ip":
            return state["bridges"]
        route = args[2]
        if route == "/cluster/resources":
            return state["resources"]
        if route.endswith("/config"):
            return state["config"]
        if route.endswith("/pending"):
            return state["pending"]
        if route.endswith("/status/current"):
            return {"status": state["status"]}
        if route.endswith("/storage"):
            return state["storage"]
        raise AssertionError(f"Unexpected external operation: {args}")

    def hostname(args, **kwargs):
        assert args == ["hostname", "-s"]
        return SimpleNamespace(stdout="pve01\n")

    def protected(path, is_directory=False):
        assert path == directory or path == directory / "intent.json"
        if path.exists():
            assert path.stat().st_mode & 0o777 == (0o700 if is_directory else 0o600)

    monkeypatch.setattr(module, "read", read)
    monkeypatch.setattr(module.subprocess, "run", hostname)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "Path", lambda path: directory)
    monkeypatch.setattr(module, "protected", protected)
    monkeypatch.setattr(module.sys, "argv", ["inspect", json.dumps(allocation), "pve01"])
    if kind == "unifi":
        monkeypatch.setattr(module, "require_unused_address", lambda *args: None)
    return module, state, directory, previous


def test_completed_owned_guest_is_read_only(guest, capsys):
    module, _, directory, _ = guest
    before = (directory / "intent.json").read_bytes()
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["exists"] and result["has_disk"]
    assert (directory / "intent.json").read_bytes() == before


@pytest.mark.parametrize(
    "kind",
    [
        "foreign_host",
        "foreign_type",
        "missing_record",
        "allocation",
        "invalid_phase",
        "removed_complete",
        "pending",
        "diskless_complete",
        "foreign_disk",
        "extra_nic",
        "wrong_bridge",
    ],
)
def test_refuses_unsafe_guest_state(guest, kind):
    module, state, directory, previous = guest
    record = directory / "intent.json"
    if kind == "foreign_host":
        state["resources"][0]["node"] = "other-node"
    elif kind == "foreign_type":
        state["resources"][0]["type"] = "lxc"
    elif kind == "missing_record":
        record.unlink()
    elif kind == "allocation":
        previous["allocation"]["mac"] = "02:77:00:00:00:ff"
        record.write_text(json.dumps(previous))
    elif kind == "invalid_phase":
        previous["phase"] = "unexpected"
        record.write_text(json.dumps(previous))
    elif kind == "removed_complete":
        state["resources"].clear()
    elif kind == "pending":
        state["pending"] = [{"key": "net0", "pending": "foreign-network"}]
    elif kind == "diskless_complete":
        del state["config"]["scsi0"]
    elif kind == "foreign_disk":
        state["config"]["scsi0"] = "local-lvm:vm-999-disk-0,size=32G"
    elif kind == "extra_nic":
        state["config"]["net1"] = "foreign-network"
    else:
        state["bridges"][0]["addr_info"] = [{"family": "inet", "local": "10.77.10.1"}]
    before = record.read_bytes() if record.exists() else None
    with pytest.raises(ValueError):
        module.main()
    assert (record.read_bytes() if record.exists() else None) == before


def test_interrupted_owned_diskless_guest_can_resume_stopped(guest, capsys):
    module, state, directory, previous = guest
    previous["phase"] = "pending"
    (directory / "intent.json").write_text(json.dumps(previous))
    del state["config"]["scsi0"]
    if previous["allocation"]["vmid"] == 110:
        state["config"]["onboot"] = 0
        del state["config"]["startup"]
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["exists"] and not result["has_disk"]
    state["status"] = "running"
    with pytest.raises(ValueError, match="diskless running"):
        module.main()


@pytest.mark.parametrize("value", [True, False, "4096.0", None])
def test_numeric_hardware_comparison_rejects_type_confusion(guest, value):
    module = guest[0]
    assert module.hardware_differences({"memory": value}, {"memory": 4096}) == ["memory"]


def test_real_record_protection_rejects_symlink(load_module, tmp_path):
    module = load_module("scripts/inspect-unifi-vm.py")
    target = tmp_path / "target"
    target.write_text("synthetic-record")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="Unprotected"):
        module.protected(link)


@pytest.mark.parametrize(
    "onboot,startup,phase",
    [(0, None, "complete"), (True, "order=2,up=30,down=120", "complete"), (1, "order=1,up=30,down=120", "complete")],
)
def test_controller_startup_refuses_phase_or_order_drift(load_module, onboot, startup, phase):
    module = load_module("scripts/inspect-unifi-vm.py")
    with pytest.raises(ValueError):
        module.validate_startup({"onboot": onboot, "startup": startup}, phase)
