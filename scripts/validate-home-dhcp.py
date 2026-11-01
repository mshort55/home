#!/usr/bin/env python3
"""Validate and render the permanent HOME DHCP allocation without device changes."""

import argparse
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path

import yaml


def require(condition, message):
    if not condition:
        raise ValueError(message)


def address(value, network):
    result = ipaddress.IPv4Address(value)
    require(
        result in network and result not in (network.network_address, network.broadcast_address),
        "Address must be a usable host in HOME.",
    )
    return int(result)


def expand(ranges, network):
    require(isinstance(ranges, list) and ranges, "At least one range is required.")
    result = set()
    for item in ranges:
        start, end = address(item["start"], network), address(item["end"], network)
        require(start <= end, "Range start exceeds end.")
        values = set(range(start, end + 1))
        require(not result & values, "Ranges within one pool overlap.")
        result |= values
    return result


def compact(values):
    ranges = []
    for value in sorted(values):
        if ranges and value == ranges[-1][1] + 1:
            ranges[-1][1] = value
        else:
            ranges.append([value, value])
    return [{"start": str(ipaddress.IPv4Address(a)), "end": str(ipaddress.IPv4Address(b))} for a, b in ranges]


def validate(config):
    network = ipaddress.IPv4Network(config["subnet"])
    require(network.prefixlen == 24, "This HOME DHCP contract requires an IPv4 /24.")
    gateway = address(config["gateway"], network)
    primary = expand(config["primary_ranges"], network)
    standby = expand(config["standby_ranges"], network)
    require(not primary & standby, "Primary and standby pools overlap.")
    require(len(primary) == len(standby), "Approved primary and standby capacity must be equal.")
    reserved, macs = set(), set()
    for item in config["reservations"]:
        ip = address(item["address"], network)
        mac = item["mac"].lower()
        require(re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac), "Invalid reservation MAC.")
        require(ip not in reserved and mac not in macs, "Duplicate reservation address or MAC.")
        reserved.add(ip)
        macs.add(mac)
    protected = {gateway} | reserved
    protected |= {address(x, network) for x in config["excluded_addresses"]}
    protected |= {address(x, network) for x in config["known_static_addresses"]}
    require(not protected & (primary | standby), "A dynamic pool includes a protected/static address.")
    return {
        "status": "valid",
        "device_changes_performed": False,
        "subnet": str(network),
        "gateway": str(ipaddress.IPv4Address(gateway)),
        "primary": {"ranges": compact(primary), "capacity": len(primary)},
        "standby": {"ranges": compact(standby), "capacity": len(standby)},
        "reservations": config["reservations"],
    }


def write_private(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not path.is_symlink(), "Output must not be a symlink.")
    fd, temporary = tempfile.mkstemp(prefix=".home-plan-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        inventory = yaml.safe_load(args.inventory.read_text())
        result = validate(inventory["all"]["vars"]["home_dhcp"])
        require(args.output.resolve() != args.inventory.resolve(), "Output cannot replace inventory.")
        write_private(args.output, result)
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        # Do not echo input or parser details from the private inventory.
        parser.exit(1, f"HOME DHCP validation failed ({type(error).__name__}); check the documented input contract.\n")
    print(
        f"Validated HOME DHCP: primary={result['primary']['capacity']}, "
        f"standby={result['standby']['capacity']}. Saved {args.output}; no device changes."
    )


if __name__ == "__main__":
    main()
