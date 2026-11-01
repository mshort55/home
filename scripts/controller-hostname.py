"""Plan or verify a controller hostname mapping without contacting the device."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
from pathlib import Path


def inspect(hostname: str, address: str, hosts: str, *, verify: bool = False) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", hostname):
        raise ValueError("Expected a literal certificate hostname")
    ip = ipaddress.IPv4Address(address)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ValueError("Expected the reviewed device IPv4 address")
    entries = [line.split("#", 1)[0].split() for line in hosts.splitlines()]
    matches = [entry for entry in entries if hostname.lower() in [name.lower() for name in entry[1:]]]
    if len(matches) > 1 or any(len(entry) != 2 or entry[0] != address for entry in matches):
        raise ValueError("Duplicate, shared-alias or conflicting hosts mapping; review it before proceeding")
    try:
        addresses = sorted({result[4][0] for result in socket.getaddrinfo(hostname, None, socket.AF_INET)})
    except socket.gaierror as error:
        if error.errno not in {socket.EAI_NONAME, socket.EAI_AGAIN}:
            raise
        addresses = []
    if addresses and addresses != [address]:
        raise ValueError(f"Certificate hostname resolves to {addresses}, expected only {address}; review the conflict")
    if not addresses and (matches or verify):
        raise ValueError("The reviewed hosts mapping does not resolve; check the controller resolver configuration")
    return {"needs_change": not addresses, "addresses": addresses}


def main() -> None:
    action, hostname, address, hosts_file = sys.argv[1:]
    if action not in {"prepare", "verify"}:
        raise ValueError("Expected prepare or verify")
    print(json.dumps(inspect(hostname, address, Path(hosts_file).read_text(), verify=action == "verify")))


if __name__ == "__main__":
    main()
