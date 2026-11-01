"""Render the inventory-owned UniFi firewall as a native nftables JSON transaction."""

from __future__ import annotations

import ipaddress
import json
import sys
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


def document(settings: dict[str, Any]) -> dict[str, Any]:
    if set(settings) != {"hostname", "gateway", "tunnel_address", "recovery_address"}:
        raise ValueError("Expected the inventory isolation settings")
    if not isinstance(settings["hostname"], str) or not settings["hostname"]:
        raise ValueError("Expected the guest hostname")
    for field in ["gateway", "tunnel_address", "recovery_address"]:
        address = ipaddress.IPv4Address(settings[field])
        if not address.is_private or str(address) != settings[field]:
            raise ValueError("Use canonical private administration addresses")
    if len({settings[key] for key in ["gateway", "tunnel_address", "recovery_address"]}) != 3:
        raise ValueError("Duplicate administration address")
    # add is idempotent for an existing table. The whole document is one nft
    # transaction, including initial creation, replacement and every rule.
    table = {"table": {"family": "inet", "name": TABLE}}
    return {"nftables": [{"add": table}, {"delete": table}, *({"add": item} for item in rules(settings))]}


def main() -> None:
    print(json.dumps(document(json.load(sys.stdin)), sort_keys=True))


if __name__ == "__main__":
    main()
