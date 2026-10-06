"""Read-only ownership and hardware guard for the permanent UniFi VM."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
from typing import Any, cast


def mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an object with string keys")
    return cast(dict[str, Any], value)


def read(*arguments: str) -> Any:
    return json.loads(subprocess.run(arguments, check=True, capture_output=True, text=True).stdout)


def protected(path: Path, directory: bool = False) -> None:
    if path.is_symlink() or path.exists() and (path.stat().st_uid != 0 or path.stat().st_mode & 0o777 != (0o700 if directory else 0o600)):
        raise ValueError("Unprotected VM installation record")
    if path.exists() and (directory and not path.is_dir() or not directory and not path.is_file()):
        raise ValueError("Unexpected installation artifact type")


def hardware_differences(config: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    for key, value in expected.items():
        actual = config.get(key)
        if type(value) is int:
            # Proxmox returns memory as a numeric string on some API versions.
            matches = (type(actual) is int and actual == value) or (isinstance(actual, str) and actual == str(value))
        else:
            matches = actual == value
        if not matches:
            differences.append(key)
    return differences


def validate_startup(config: dict[str, Any], phase: str) -> None:
    onboot = config.get("onboot", 0)
    if type(onboot) not in [int, str] or str(onboot) not in ["0", "1"] or phase == "complete" and str(onboot) != "1":
        raise ValueError("Controller automatic startup differs from its installation phase")
    startup = dict(item.split("=", 1) for item in str(config.get("startup", "")).split(",") if "=" in item)
    if startup != {"order": "2", "up": "30", "down": "120"} and not (
        phase == "pending" and str(onboot) == "0" and "startup" not in config
    ):
        raise ValueError("Controller startup order differs")


def require_unused_address(interfaces: list[dict[str, Any]], target: ipaddress.IPv4Interface) -> None:
    """Probe on the native management link, avoiding container-generated ICMP replies."""
    candidates = [(item, address) for item in interfaces for address in item.get("addr_info", [])
                  if address.get("family") == "inet" and ipaddress.ip_address(address["local"]) in target.network]
    if len(candidates) != 1:
        raise ValueError("Require one native Proxmox management interface for the address collision probe")
    interface, source = candidates[0]
    if source["local"] == str(target.ip):
        raise ValueError("Controller address is already assigned to Proxmox")
    mac = bytes.fromhex(interface["address"].replace(":", ""))
    address = target.ip.packed
    request = (b"\xff" * 6 + mac + b"\x08\x06" + struct.pack("!HHBBH", 1, 0x0800, 6, 4, 1)
               + mac + socket.inet_aton(source["local"]) + b"\x00" * 6 + address)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806)) as link:
        link.bind((interface["ifname"], 0))
        link.settimeout(0.2)
        for _ in range(3):
            link.send(request)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    frame = link.recv(2048)
                except TimeoutError:
                    continue
                if len(frame) >= 42 and frame[12:14] == b"\x08\x06" and frame[14:20] == b"\x00\x01\x08\x00\x06\x04" and frame[28:32] == address:
                    raise ValueError("Controller address already answers ARP; refusing allocation")


def main() -> None:
    allocation = mapping(json.loads(sys.argv[1]))
    node = sys.argv[2]
    if os.geteuid() != 0 or subprocess.run(["hostname", "-s"], check=True, capture_output=True, text=True).stdout.strip() != node:
        raise ValueError("Unexpected Proxmox host")
    if allocation["vmid"] != 110 or allocation["vlan"] != 10 or allocation["cores"] != 2 or allocation["memory_mib"] != 4096 or allocation["disk_gib"] != 32:
        raise ValueError("Unexpected controller VM budget")
    directory = Path("/var/lib/home-automation/unifi-110")
    record = directory / "intent.json"
    protected(directory, True)
    protected(record)
    previous = mapping(json.loads(record.read_text())) if record.exists() else {}
    if previous and (previous.get("version") != 1 or previous.get("allocation") != allocation or previous.get("phase") not in ["pending", "complete"]):
        raise ValueError("Recorded VM allocation conflicts")
    resources = read("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    matches = [item for item in resources if item["vmid"] == allocation["vmid"]]
    config: dict[str, Any] = {}
    state = "absent"
    if matches:
        if len(matches) != 1 or matches[0]["type"] != "qemu" or matches[0]["node"] != node or not previous:
            raise ValueError("VM ID is owned by another workload")
        config = mapping(read("pvesh", "get", "/nodes/localhost/qemu/110/config", "--current", "1", "--output-format", "json"))
        pending = read("pvesh", "get", "/nodes/localhost/qemu/110/pending", "--output-format", "json")
        if any("pending" in item or item.get("delete") for item in pending):
            raise ValueError("VM has pending configuration changes")
        state = str(read("pvesh", "get", "/nodes/localhost/qemu/110/status/current", "--output-format", "json")["status"])
        validate_startup(config, str(previous["phase"]))
        expected = {"name": allocation["name"], "description": "Managed by create-unifi-vm.yml; vmid=110", "cores": 2, "memory": 4096, "sockets": 1, "balloon": 0, "ostype": "l26", "scsihw": "virtio-scsi-single", "bios": "seabios", "serial0": "socket", "vga": "serial0"}
        differences = hardware_differences(config, expected)
        if differences:
            raise ValueError("Owned VM hardware has drifted: " + ", ".join(differences))
        if str(config.get("agent", "")) not in ["1", "enabled=1"] or config.get("cicustom") != "user=home-cloudinit:snippets/unifi01-user.yml":
            raise ValueError("Guest agent or seeded cloud-init selection differs")
        if config.get("ipconfig0") != f"ip={allocation['address']},gw={allocation['gateway']}" or config.get("nameserver") != allocation["dns"] or config.get("searchdomain") != allocation["domain"]:
            raise ValueError("Cloud-init networking has drifted")
        network = str(config.get("net0", "")).split(",")
        expected_network = {"virtio": allocation["mac"], "bridge": allocation["bridge"], "tag": "10"}
        parsed = dict(item.split("=", 1) for item in network if "=" in item)
        if parsed != expected_network:
            raise ValueError("MGMT network attachment differs")
        if any(key.startswith(("net", "hostpci", "usb", "unused", "args")) and key != "net0" for key in config):
            raise ValueError("Unexpected VM interface, device passthrough or unattached disk")
        if any(key.startswith(("scsi", "sata", "ide", "virtio")) and key not in ["scsi0", "scsihw", "ide2"] for key in config):
            raise ValueError("Unexpected VM disk or installation media")
        if "scsi0" in config:
            volume = str(config["scsi0"]).split(",")[0]
            if not volume.startswith(allocation["storage"] + ":vm-110-disk-"):
                raise ValueError("System disk belongs to another VM/storage")
        if "ide2" not in config or not str(config["ide2"]).startswith(allocation["storage"] + ":vm-110-cloudinit,"):
            raise ValueError("Unexpected cloud-init media")
        if previous.get("phase") == "complete" and ("scsi0" not in config or config.get("boot") != "order=scsi0" or "size=32G" not in str(config["scsi0"]).split(",")):
            raise ValueError("Completed VM boot disk has drifted")
        if state == "running" and "scsi0" not in config:
            raise ValueError("Unrecorded diskless running guest")
    elif previous.get("phase") == "complete":
        raise ValueError("Completed VM was removed; refusing automatic recreation")
    interface = ipaddress.ip_interface(allocation["address"])
    if interface.network.prefixlen != 24 or ipaddress.ip_address(allocation["gateway"]) not in interface.network:
        raise ValueError("Invalid guest network allocation")
    storage = read("pvesh", "get", "/nodes/localhost/storage", "--output-format", "json")
    selected = [item for item in storage if item["storage"] == allocation["storage"]]
    if len(selected) != 1 or not selected[0].get("active") or "images" not in selected[0].get("content", "").split(","):
        raise ValueError("Guest disk storage is unavailable")
    if not matches and selected[0]["avail"] < 40 * 1024 ** 3:
        raise ValueError("Insufficient storage headroom for the 32 GiB controller VM")
    if not matches:
        if selected[0]["used"] / selected[0]["total"] >= 0.70:
            raise ValueError("Storage has reached the planned 70 percent investigation threshold")
        total_memory = sum(item.get("maxmem", 0) for item in resources)
        if total_memory + 4096 * 1024 ** 2 > 56 * 1024 ** 3:
            raise ValueError("Controller allocation exceeds the planned guest RAM budget")
    bridges = read("ip", "-j", "-d", "address", "show")
    if not matches:
        if not isinstance(interface, ipaddress.IPv4Interface):
            raise ValueError("Controller requires IPv4 management addressing")
        require_unused_address(bridges, interface)
    bridge = [item for item in bridges if item["ifname"] == allocation["bridge"]]
    if len(bridge) != 1 or "UP" not in bridge[0]["flags"] or bridge[0].get("addr_info") or not bridge[0].get("linkinfo", {}).get("info_data", {}).get("vlan_filtering"):
        raise ValueError("Controller requires the running address-free VLAN-aware bridge")
    print(json.dumps({"exists": bool(matches), "state": state, "config": config, "previous": previous, "has_disk": "scsi0" in config}))


if __name__ == "__main__":
    main()
