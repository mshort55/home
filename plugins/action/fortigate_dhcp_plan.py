"""Plan a bounded DHCP reservation merge without changing the live server."""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase


def mac(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", value):
        raise AnsibleActionFail("Supply stable six-octet MAC addresses.")
    if int(value[:2], 16) & 1 or value.lower() == "00:00:00:00:00:00":
        raise AnsibleActionFail("Reservations require unicast MAC addresses.")
    return value.lower()


def reservations(server: dict[str, Any]) -> list[dict[str, Any]]:
    raw = server.get("reserved-address", [])
    if not isinstance(raw, list):
        raise AnsibleActionFail("Incomplete DHCP reservation response.")
    fields = {"id", "ip", "mac", "action", "description", "type", "circuit_id", "remote_id", "circuit_id_type", "remote_id_type"}
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or "id" not in item or set(item) - {name.replace("_", "-") for name in fields} - {"q_origin_key"}:
            raise AnsibleActionFail("Unsupported existing reservation fields; refusing a lossy merge.")
        result.append({key.replace("-", "_"): value for key, value in item.items() if key != "q_origin_key"})
    if len({item["id"] for item in result}) != len(result):
        raise AnsibleActionFail("Duplicate reservation IDs.")
    return result


def plan(server: dict[str, Any], settings: dict[str, Any], leases: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        network = ipaddress.IPv4Network(settings["subnet"])
        gateway = ipaddress.IPv4Address(settings["gateway"])
        if network.prefixlen != 24 or not network.subnet_of(ipaddress.IPv4Network("10.0.0.0/8")) or gateway not in network:
            raise ValueError("Invalid pilot subnet")
        if server["id"] != settings["server_id"] or server["interface"] != settings["interface"] or server["netmask"] != "255.255.255.0" or server["default-gateway"] != str(gateway) or server.get("status", "enable") != "enable":
            raise ValueError("Wrong DHCP server")
        desired = settings["reservations"]
        if len(desired) != 2 or {item["role"] for item in desired} != {"pilot_wan", "wifi_admin"}:
            raise ValueError("Require exactly WAN and Wi-Fi reservations")
        merged = reservations(server)
        original = [dict(item) for item in merged]
        desired_ids: set[int] = set()
        desired_ips: set[str] = set()
        desired_macs: set[str] = set()
        for entry in desired:
            address = ipaddress.IPv4Address(entry["address"])
            identity = mac(entry["mac"])
            index = entry["id"]
            if not isinstance(index, int) or index < 1 or index in desired_ids or str(address) in desired_ips or identity in desired_macs:
                raise ValueError("Duplicate reservation identity")
            if address not in network or address in (network.network_address, network.broadcast_address, gateway):
                raise ValueError("Invalid reservation address")
            if not any(ipaddress.IPv4Address(pool["start-ip"]) <= address <= ipaddress.IPv4Address(pool["end-ip"]) for pool in server["ip-range"]):
                raise ValueError("Use an already leased address in the existing pool")
            desired_ids.add(index); desired_ips.add(str(address)); desired_macs.add(identity)
            existing = next((item for item in merged if item["id"] == index), None)
            description = "Home automation: " + entry["role"]
            expected = {"id": index, "ip": str(address), "mac": identity, "action": "reserved", "description": description, "type": "mac"}
            if existing is not None and any(existing.get(key) != value for key, value in expected.items()):
                raise ValueError("Reservation ID is already owned or has drifted")
            for item in merged:
                if item["id"] != index and (item.get("ip") == str(address) or str(item.get("mac", "")).lower() == identity):
                    raise ValueError("Conflicting IP or MAC reservation")
            for lease in leases:
                lease_ip = lease.get("ip", lease.get("ipaddr", lease.get("ip-address")))
                lease_mac = lease.get("mac", lease.get("macaddr", lease.get("mac-address")))
                if lease_ip == str(address) and str(lease_mac).lower() != identity:
                    raise ValueError("Address is leased to another device")
            if existing is None:
                if not any(lease.get("ip", lease.get("ipaddr", lease.get("ip-address"))) == str(address) and str(lease.get("mac", lease.get("macaddr", lease.get("mac-address", "")))).lower() == identity for lease in leases):
                    raise ValueError("New reservation must match a current lease; inspect DHCP leases first")
                merged.append(expected)
        return {"changed": False, "needs_change": merged != original, "reservations": sorted(merged, key=lambda item: item["id"])}
    except (ValueError, KeyError, TypeError) as error:
        raise AnsibleActionFail("Pilot DHCP reservation validation failed: " + str(error)) from error


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _supports_check_mode = True

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = super().run(tmp, task_vars)
        args: dict[str, Any] = self._task.args
        if set(args) != {"server", "settings", "leases"} or not isinstance(args["server"], dict) or not isinstance(args["settings"], dict) or not isinstance(args["leases"], list) or any(not isinstance(item, dict) for item in args["leases"]):
            raise AnsibleActionFail("Supply complete DHCP server, reservation settings and lease responses.")
        result.update(plan(args["server"], args["settings"], args["leases"]))
        return result
