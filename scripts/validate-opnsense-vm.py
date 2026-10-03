#!/usr/bin/env python3
"""Validate existing Proxmox firewall VM hardware without changing it."""

from __future__ import annotations

import json
import re
import sys
from typing import cast


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object with string keys")
    return cast(dict[str, object], value)


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Expected an integer, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError("Expected an integer")


def properties(value: object, default_key: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in text(value).split(","):
        key, separator, item = part.partition("=")
        if not separator:
            key, item = default_key, key
        if key in result:
            raise ValueError(f"Duplicate property: {key}")
        result[key] = item
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(payload: dict[str, object]) -> bool:
    config = mapping(payload["config"])
    desired = mapping(payload["desired"])
    vmid = integer(desired["vmid"])
    disk_storage = text(desired["disk_storage"])
    disk_pattern = rf"{re.escape(disk_storage)}:vm-{vmid}-disk-[0-9]+"
    require(config.get("description") == desired["description"], "VM ownership marker conflicts")
    for key in ("name", "bios", "machine", "ostype", "scsihw"):
        require(config.get(key) == desired[key], f"VM {key} conflicts")
    defaults: dict[str, object] = {"sockets": 1, "numa": 0, "onboot": 0}
    for key in ("cores", "sockets", "balloon", "numa", "onboot"):
        require(integer(config.get(key, defaults.get(key, ""))) == integer(desired[key]), f"VM {key} conflicts")
    memory = properties(str(config.get("memory", "")), "current")
    require(memory == {"current": str(integer(desired["memory"]))}, "VM memory conflicts")
    require(properties(config.get("cpu", ""), "cputype") == {"cputype": "host"}, "VM CPU conflicts")
    require(properties(config.get("startup", ""), "order") ==
            {"order": "1", "up": "30", "down": "120"}, "VM startup ordering conflicts")
    require(properties(str(config.get("agent", "0")), "enabled").get("enabled") == "0",
            "Guest agent must remain disabled during bootstrap")
    require(properties(config.get("vga", "std"), "type") == {"type": "std"}, "VM VGA conflicts")
    boot = properties(config.get("boot", ""), "legacy")
    require(boot in ({"order": "scsi0;ide2"}, {"order": "scsi0"}),
            "Use explicit disk-first boot order; installation media must not have priority")
    require(not any(key in config for key in ("args", "lock", "template")),
            "VM has unexpected custom arguments, a lock or template state")

    expected_networks = mapping(desired["networks"])
    actual_networks = {key: value for key, value in config.items() if re.fullmatch(r"net[0-9]+", key)}
    require(actual_networks.keys() == expected_networks.keys(), "VM network device set conflicts")
    wan_link_change = False
    for device, expected in expected_networks.items():
        actual = properties(actual_networks[device], "model")
        target = mapping(expected)
        if "virtio" in actual:
            actual["macaddr"] = actual.pop("virtio").lower()
            actual["model"] = "virtio"
        elif "macaddr" in actual:
            actual["macaddr"] = actual["macaddr"].lower()
        if actual.get("link_down") == "0":
            del actual["link_down"]
        if device == 'net0':
            actual_link = actual.pop('link_down', '0')
            desired_link = text(target.get('link_down', '0'))
            require(actual_link in ('0', '1'), 'Invalid WAN link state')
            target = {key: value for key, value in target.items() if key != 'link_down'}
            wan_link_change = actual_link != desired_link
        require(actual == target, f"VM {device} MAC, bridge, VLAN or firewall settings conflict")

    disk = properties(config.get("scsi0", ""), "file")
    require(re.fullmatch(disk_pattern, disk.get("file", "")) is not None,
            "System disk does not belong to this VM and storage")
    require(disk.get("size") == f"{integer(desired['disk_gib'])}G", "System disk size conflicts")
    require(disk.get("cache") == "none" and disk.get("iothread") == "1", "System disk I/O policy conflicts")
    disk_defaults = {"discard": "ignore", "ssd": "0", "backup": "1", "replicate": "1", "format": "raw"}
    for key, value in disk_defaults.items():
        require(disk.get(key, value) == value, f"System disk {key} conflicts")
    require(disk.keys() <= {"file", "size", "cache", "iothread", *disk_defaults},
            "System disk contains unreviewed settings")

    efi = properties(config.get("efidisk0", ""), "file")
    require(re.fullmatch(disk_pattern, efi.get("file", "")) is not None,
            "EFI variable disk does not belong to this VM and storage")
    require(efi.get("file") != disk.get("file"), "System disk and EFI disk must be distinct")
    require(efi.get("efitype") == "4m" and efi.get("pre-enrolled-keys") == "0",
            "EFI type or Secure Boot policy conflicts")
    require(efi.get("format", "raw") == "raw", "EFI disk format conflicts")
    require(efi.keys() <= {"file", "size", "efitype", "pre-enrolled-keys", "format", "ms-cert"},
            "EFI disk contains unreviewed settings")

    cdrom = properties(config.get("ide2", "none,media=cdrom"), "file")
    require(cdrom.get("media") == "cdrom" and cdrom.get("file") in
            (desired["iso_volume"], desired.get("bootstrap_iso_volume", desired["iso_volume"]), "none"),
            "Attached installation media conflicts")
    require(cdrom.keys() <= {"file", "media", "size"}, "CD-ROM contains unreviewed settings")
    allowed_drives = {"scsi0", "efidisk0", "ide2"}
    for key in config:
        require(not (re.fullmatch(r"(?:scsi|sata|ide|virtio|efidisk|tpmstate|hostpci|usb|unused)[0-9]+", key)
                     and key not in allowed_drives), f"Unexpected VM device: {key}")
    return wan_link_change


def main() -> None:
    try:
        payload: object = json.load(sys.stdin)
        wan_link_change = validate(mapping(payload))
    except (KeyError, ValueError, TypeError) as error:
        print(f"OPNsense VM verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps({"verified": True, "wan_link_change": wan_link_change}))


if __name__ == "__main__":
    main()
