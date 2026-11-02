#!/usr/bin/env python3
"""Render the permanent DHCP-only Dnsmasq model from validated HOME declarations."""

import importlib.util
import ipaddress
import json
import re
import sys
import uuid
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("home_dhcp", Path(__file__).with_name("validate-home-dhcp.py"))
HOME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOME)


def identity(kind, name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"home-automation/dnsmasq/{kind}/{name}"))


def plan(allocation, settings):
    validated = HOME.validate(allocation)
    HOME.require(
        {"interface", "domain", "lease_seconds"} <= set(settings) <= {"interface", "domain", "lease_seconds", "ranges"},
        "Unexpected DHCP service settings.",
    )
    interface, domain, lease = settings["interface"], settings["domain"], settings["lease_seconds"]
    HOME.require(interface == "opt1", "This role serves only the owned HOME interface opt1.")
    HOME.require(isinstance(domain, str) and len(domain) <= 253, "Invalid DHCP domain.")
    HOME.require(
        all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in domain.split(".")), "Invalid DHCP domain."
    )
    HOME.require(type(lease) is int and 600 <= lease <= 86400, "Lease must be 600–86400 seconds.")
    if "ranges" in settings:
        network = ipaddress.IPv4Network(allocation["subnet"])
        active = HOME.expand(settings["ranges"], network)
        approved = HOME.expand(validated["primary"]["ranges"], network)
        HOME.require(active <= approved, "Configured ranges must stay within the approved primary pool.")
        validated["primary"] = {"ranges": HOME.compact(active), "capacity": len(active)}
    names = set()
    hosts = {}
    for item in validated["reservations"]:
        name, mac = item["name"], item["mac"].lower()
        HOME.require(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name), "Invalid reservation name.")
        HOME.require(name not in names, "Duplicate reservation name.")
        HOME.require(not int(mac[:2], 16) & 1 and mac != "00:00:00:00:00:00", "Reservation MAC must be unicast.")
        HOME.require(item["address"] != allocation["gateway"], "Reservation cannot use gateway.")
        names.add(name)
        hosts[identity("host", name)] = {
            "host": name,
            "domain": domain,
            "ip": item["address"],
            "hwaddr": mac,
            "client_id": "*",
            "lease_time": str(lease),
            "descr": f"Home automation: DHCP {name}",
        }
    ranges = {}
    for index, item in enumerate(validated["primary"]["ranges"]):
        ranges[identity("range", str(index))] = {
            "interface": interface,
            "start_addr": item["start"],
            "end_addr": item["end"],
            "subnet_mask": str(ipaddress.IPv4Network(allocation["subnet"]).netmask),
            "lease_time": str(lease),
            "domain_type": "range",
            "domain": domain,
            "nosync": "1",
            "description": f"Home automation: HOME DHCP range {index + 1}",
        }
    options = {}
    for number, value in [
        (3, allocation["gateway"]),
        (6, allocation["gateway"]),
        (15, domain),
        (42, allocation["gateway"]),
        (119, domain),
    ]:
        options[identity("option", str(number))] = {
            "type": "set",
            "option": str(number),
            "interface": interface,
            "value": value,
            "force": "0",
            "description": f"Home automation: HOME DHCP option {number}",
        }
    model = {
        "enable": "1",
        "interface": interface,
        "port": "0",
        "strictbind": "1",
        "no_resolv": "1",
        "no_hosts": "1",
        "regdhcp": "0",
        "regdhcpstatic": "0",
        "dhcpfirst": "0",
        "regdhcpdomain": "",
        "dhcp": {
            "no_interface": "",
            "fqdn": "1",
            "domain": domain,
            "local": "1",
            "lease_max": str(validated["primary"]["capacity"] + len(hosts)),
            "authoritative": "1",
            "default_fw_rules": "1",
            "reply_delay": "0",
            "enable_ra": "0",
            "host_ping": "1",
            "nosync": "1",
            "log_dhcp": "0",
            "log_quiet": "0",
        },
        "hosts": hosts,
        "dhcp_ranges": ranges,
        "dhcp_options": options,
        "domainoverrides": {},
        "dhcp_tags": {},
        "dhcp_boot": {},
    }
    return {
        "version": 1,
        "subnet": allocation["subnet"],
        "gateway": allocation["gateway"],
        "model": model,
        "allocation": validated,
        "settings": settings,
    }


def main():
    try:
        data = json.load(sys.stdin)
        print(json.dumps(plan(data["home_dhcp"], data["settings"])))
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"DHCP declaration rejected: {error}") from error


if __name__ == "__main__":
    main()
