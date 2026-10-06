"""Own one nftables table isolating the UniFi restore rehearsal, including containers."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

TABLE = "home_unifi"
NON_PUBLIC = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
]


def run(*arguments: str, content: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, input=content, check=True, capture_output=True, text=True, timeout=15)


def match(left: dict[str, Any], right: object, operator: str = "==") -> dict[str, Any]:
    return {"match": {"op": operator, "left": left, "right": right}}


def payload(field: str) -> dict[str, Any]:
    return {"payload": {"protocol": "ip", "field": field}}


def addresses(values: list[str]) -> dict[str, Any]:
    return {"set": sorted(values, key=lambda value: int(ipaddress.IPv4Address(value)))}


def rules(settings: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = [{"table": {"family": "inet", "name": TABLE}}]
    for chain, hook in [("input", "input"), ("output", "output"), ("forward", "forward")]:
        objects.append(
            {
                "chain": {
                    "family": "inet",
                    "table": TABLE,
                    "name": chain,
                    "type": "filter",
                    "hook": hook,
                    "prio": -10,
                    "policy": "drop",
                }
            }
        )

    def add(chain: str, expressions: list[dict[str, Any]], verdict: str = "accept") -> None:
        objects.append(
            {"rule": {"family": "inet", "table": TABLE, "chain": chain, "expr": [*expressions, {verdict: None}]}}
        )

    def protocol(name: str) -> dict[str, Any]:
        return match({"meta": {"key": "l4proto"}}, name)

    def ports(name: str, values: list[int]) -> dict[str, Any]:
        return match(
            {"payload": {"protocol": name, "field": "dport"}}, values[0] if len(values) == 1 else {"set": values}
        )

    established = match({"ct": {"key": "state"}}, {"set": ["established", "related"]})
    admins = addresses([settings["tunnel_address"], settings["recovery_address"]])
    for chain, interface in [("input", "iifname"), ("output", "oifname")]:
        add(chain, [match({"meta": {"key": interface}}, "lo")])
        add(chain, [match({"meta": {"key": "nfproto"}}, "ipv6")], "drop")
    add("input", [established])
    add("input", [match(payload("saddr"), admins), protocol("tcp"), ports("tcp", [22])])
    add("input", [match(payload("saddr"), settings["tunnel_address"]), protocol("tcp"), ports("tcp", [11443])])
    add("input", [match(payload("saddr"), admins), protocol("icmp")])
    # Only these gateway services and replies to administration escape private-range denial.
    add("output", [match(payload("daddr"), settings["gateway"]), protocol("udp"), ports("udp", [53, 123])])
    add("output", [match(payload("daddr"), settings["gateway"]), protocol("tcp"), ports("tcp", [53])])
    add("output", [match(payload("daddr"), admins), match({"ct": {"key": "direction"}}, "reply"), established])
    for cidr in NON_PUBLIC:
        network = ipaddress.ip_network(cidr)
        add(
            "output",
            [match(payload("daddr"), {"prefix": {"addr": str(network.network_address), "len": network.prefixlen}})],
            "drop",
        )
    add("output", [established])
    add("output", [protocol("tcp"), ports("tcp", [80, 443])])
    # No forwarded container traffic. The vendor's rootless pasta mode uses host sockets.
    # nft groups rules by chain and removes redundant L4 matches before port expressions.
    for item in objects:
        if "rule" in item:
            expressions = item["rule"]["expr"]
            if any(
                expr.get("match", {}).get("left", {}).get("payload", {}).get("field") == "dport" for expr in expressions
            ):
                item["rule"]["expr"] = [
                    expr for expr in expressions if expr.get("match", {}).get("left") != {"meta": {"key": "l4proto"}}
                ]
    return normalized(objects)


def normalized(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [
        {kind: {key: value for key, value in fields.items() if key not in ["handle"]}}
        for item in objects
        for kind, fields in item.items()
        if kind in ["table", "chain", "rule"]
    ]
    chain_order = {"input": 0, "output": 1, "forward": 2}
    return sorted(
        filtered,
        key=lambda item: (
            0 if "table" in item else 1 if "chain" in item else 2,
            chain_order.get(item.get("chain", {}).get("name", item.get("rule", {}).get("chain", "")), 0),
        ),
    )


def current() -> list[dict[str, Any]]:
    tables = json.loads(run("/usr/sbin/nft", "-j", "list", "tables").stdout)["nftables"]
    if not any(
        item.get("table", {}).get("family") == "inet" and item.get("table", {}).get("name") == TABLE for item in tables
    ):
        return []
    return normalized(json.loads(run("/usr/sbin/nft", "-j", "list", "table", "inet", TABLE).stdout)["nftables"])


def apply(settings: dict[str, Any], operation: str) -> dict[str, Any]:
    expected = rules(settings)
    observed = current()
    changed = observed != expected
    if operation == "verify" and changed:
        raise ValueError("Saved or loaded UniFi isolation policy differs; restore is blocked")
    if changed and operation == "apply":
        commands = [{"delete": {"table": {"family": "inet", "name": TABLE}}}] if observed else []
        commands += [{"add": item} for item in expected]
        encoded = json.dumps({"nftables": commands})
        run("/usr/sbin/nft", "--check", "-j", "-f", "-", content=encoded)
        run("/usr/sbin/nft", "-j", "-f", "-", content=encoded)
        if current() != expected:
            raise ValueError("Loaded UniFi firewall does not match the bounded policy")
    return {"changed": changed, "isolated": not changed or operation == "apply"}


def main() -> None:
    operation, filename = sys.argv[1:]
    if operation not in ["plan", "apply", "verify"] or os.geteuid() != 0:
        raise ValueError("Use an explicit isolation action as root")
    path = Path(filename)
    info = path.stat()
    if path.is_symlink() or not path.is_file() or info.st_uid != 0 or info.st_mode & 0o777 != 0o600:
        raise ValueError("Unprotected UniFi isolation inputs")
    settings: dict[str, Any] = json.loads(path.read_text())
    if (
        set(settings) != {"hostname", "gateway", "tunnel_address", "recovery_address"}
        or socket.gethostname().split(".")[0] != settings["hostname"]
    ):
        raise ValueError("Unexpected UniFi guest identity")
    for field in ["gateway", "tunnel_address", "recovery_address"]:
        address = ipaddress.IPv4Address(settings[field])
        if not address.is_private or str(address) != settings[field]:
            raise ValueError("Use canonical private administration addresses")
    if len({settings[key] for key in ["gateway", "tunnel_address", "recovery_address"]}) != 3:
        raise ValueError("Duplicate administration address")
    print(json.dumps(apply(settings, operation)))


if __name__ == "__main__":
    main()
