from copy import deepcopy

import pytest


@pytest.fixture
def vm(load_module):
    return load_module("scripts/validate-opnsense-vm.py")


@pytest.fixture
def payload():
    desired = {
        "vmid": 100,
        "disk_storage": "local-lvm",
        "description": "fixture-owned",
        "name": "opnsense01",
        "bios": "ovmf",
        "machine": "q35",
        "ostype": "other",
        "scsihw": "virtio-scsi-single",
        "cores": 4,
        "sockets": 1,
        "balloon": 0,
        "numa": 0,
        "onboot": 0,
        "memory": 8192,
        "disk_gib": 32,
        "iso_volume": "local:iso/fixture.iso",
        "networks": {
            "net0": {
                "model": "virtio",
                "macaddr": "02:77:00:00:64:00",
                "bridge": "vmbr2",
                "firewall": "0",
                "link_down": "1",
            },
            "net1": {
                "model": "virtio",
                "macaddr": "02:77:00:00:64:01",
                "bridge": "vmbr1",
                "tag": "10",
                "firewall": "0",
            },
        },
    }
    config = {
        key: desired[key]
        for key in [
            "description",
            "name",
            "bios",
            "machine",
            "ostype",
            "scsihw",
            "cores",
            "sockets",
            "balloon",
            "numa",
            "onboot",
        ]
    }
    config.update(
        memory="8192",
        cpu="host",
        startup="order=1,up=30,down=120",
        boot="order=scsi0;ide2",
        net0="virtio=02:77:00:00:64:00,bridge=vmbr2,link_down=1",
        net1="virtio=02:77:00:00:64:01,bridge=vmbr1,tag=10",
        scsi0="local-lvm:vm-100-disk-0,size=32G,cache=none,iothread=1",
        efidisk0="local-lvm:vm-100-disk-1,efitype=4m,pre-enrolled-keys=0",
        ide2="local:iso/fixture.iso,media=cdrom",
    )
    return {"config": config, "desired": desired}


def test_valid_hardware_and_wan_difference(vm, payload):
    before = deepcopy(payload)
    assert vm.validate(payload) is False
    assert payload == before
    payload["config"]["net0"] = payload["config"]["net0"].replace(",link_down=1", "")
    assert vm.validate(payload) is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("description", "foreign"),
        ("memory", "current=8192,max=16384"),
        ("cores", True),
        ("cpu", "host,hidden=1"),
        ("startup", "order=2,up=30,down=120"),
        ("agent", "1"),
        ("vga", "serial0"),
        ("boot", "order=ide2;scsi0"),
        ("args", "custom"),
        ("lock", "backup"),
        ("template", 1),
        ("net0", "virtio=02:77:00:00:64:ff,bridge=vmbr2,link_down=1"),
        ("net1", "virtio=02:77:00:00:64:01,bridge=vmbr1,tag=20"),
        ("net2", "virtio=02:77:00:00:64:02,bridge=vmbr1"),
        ("scsi0", "local-lvm:vm-200-disk-0,size=32G,cache=none,iothread=1"),
        ("scsi0", "local-lvm:vm-100-disk-0,size=80G,cache=none,iothread=1"),
        ("scsi0", "local-lvm:vm-100-disk-0,size=32G,cache=unsafe,iothread=1"),
        ("scsi0", "local-lvm:vm-100-disk-0,size=32G,cache=none,iothread=1,unreviewed=1"),
        ("efidisk0", "local-lvm:vm-100-disk-0,efitype=4m,pre-enrolled-keys=0"),
        ("efidisk0", "local-lvm:vm-100-disk-1,efitype=4m,pre-enrolled-keys=1"),
        ("ide2", "local:iso/foreign.iso,media=cdrom"),
        ("hostpci0", "0000:00:00.0"),
        ("unused0", "foreign-disk"),
    ],
)
def test_refuses_hardware_or_ownership_drift(vm, payload, key, value):
    payload["config"][key] = value
    with pytest.raises(ValueError):
        vm.validate(payload)


@pytest.mark.parametrize("value", [True, False, None, "NaN", 1.5])
def test_integer_rejects_type_confusion(vm, value):
    with pytest.raises(ValueError):
        vm.integer(value)


def test_duplicate_device_properties_rejected(vm):
    with pytest.raises(ValueError, match="Duplicate property"):
        vm.properties("virtio=aa,bridge=vmbr1,bridge=vmbr2", "model")


def test_json_cli_failure(vm, monkeypatch, capsys):
    import io

    monkeypatch.setattr(vm.sys, "stdin", io.StringIO('{"config": {}}'))
    with pytest.raises(SystemExit) as error:
        vm.main()
    assert error.value.code == 1
    assert "verification failed" in capsys.readouterr().err
