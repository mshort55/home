#!/usr/bin/env python3
"""Exercise real DHCP packets only inside an isolated network-none test container."""

import argparse
import ipaddress
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args):
    subprocess.run(args, check=True)  # noqa: S603 -- Fixed test commands inside isolated container.


def options(data):
    result = {}
    offset = 240
    while offset < len(data):
        key = data[offset]
        offset += 1
        if key == 255:
            break
        if key == 0:
            continue
        length = data[offset]
        offset += 1
        result[key] = data[offset : offset + length]
        offset += length
    return result


def checksum(data):
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total & 65535) + (total >> 16)
    total = (total & 65535) + (total >> 16)
    return (~total) & 65535


class Client:
    def __init__(self):
        self.socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        self.socket.bind(("dhcp-client", 0))
        self.socket.settimeout(0.2)
        self.xid = 100

    def exchange(self, mac, kind, requested=None, ciaddr="0.0.0.0", selecting=False, timeout=2):  # noqa: S104 -- DHCP wire field, not a socket bind.
        self.xid += 1
        hardware = bytes.fromhex(mac.replace(":", ""))
        header = struct.pack(
            "!BBBBIHH4s4s4s4s16s64s128s",
            1,
            1,
            6,
            0,
            self.xid,
            0,
            0x8000,
            socket.inet_aton(ciaddr),
            bytes(4),
            bytes(4),
            bytes(4),
            hardware,
            bytes(64),
            bytes(128),
        )
        opts = bytes([53, 1, kind, 55, 5, 3, 6, 15, 42, 119])
        if requested:
            opts += bytes([50, 4]) + socket.inet_aton(requested)
        if selecting:
            opts += bytes([54, 4]) + socket.inet_aton("192.0.2.254")
        data = header + bytes([99, 130, 83, 99]) + opts + bytes([255])
        udp = struct.pack("!HHHH", 68, 67, 8 + len(data), 0) + data
        ip = struct.pack(
            "!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), self.xid, 0, 64, 17, 0, socket.inet_aton(ciaddr), bytes([255] * 4)
        )
        ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
        self.socket.send(bytes([255] * 6) + hardware + bytes.fromhex("0800") + ip + udp)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                frame = self.socket.recv(4096)
            except TimeoutError:
                continue
            # Answer ARP for the synthetic renewing client so unicast ACKs
            # are observable without assigning its address to the server kernel.
            if frame[12:14] == bytes.fromhex("0806") and len(frame) >= 42:
                if frame[20:22] == bytes.fromhex("0001") and frame[38:42] == socket.inet_aton(ciaddr):
                    reply = frame[6:12] + hardware + bytes.fromhex("0806")
                    reply += bytes.fromhex("0001080006040002") + hardware + socket.inet_aton(ciaddr)
                    reply += frame[22:28] + frame[28:32]
                    self.socket.send(reply)
                continue
            if len(frame) < 282 or frame[23] != 17:
                continue
            off = 14 + (frame[14] & 15) * 4
            if struct.unpack("!HH", frame[off : off + 4]) != (67, 68):
                continue
            packet = frame[off + 8 :]
            if struct.unpack("!I", packet[4:8])[0] == self.xid:
                return socket.inet_ntoa(packet[16:20]), options(packet)
        return None

    def lease(self, mac, requested=None):
        offered = self.exchange(mac, 1, requested=requested)
        require(offered is not None and offered[1].get(53) == b"\x02", "Expected DHCP offer")
        ack = self.exchange(mac, 3, requested=offered[0], selecting=True)
        require(ack is not None and ack[1].get(53) == b"\x05" and ack[0] == offered[0], "Expected matching ACK")
        for key in [3, 6, 42]:
            require(ack[1].get(key) == socket.inet_aton("192.0.2.254"), "Incorrect router/DNS/NTP option")
        require(ack[1].get(15) == b"home.test", "Incorrect domain")
        require(ack[1].get(119) == b"\x04home\x04test\x00", "Incorrect search suffix")
        return ack[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/src/tests/fixtures/dnsmasq.conf")
    parser.add_argument("--plan", default="/src/tests/fixtures/opnsense-dhcp.json")
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    expected = set()
    for interval in plan["allocation"]["primary"]["ranges"]:
        expected.update(
            str(ipaddress.IPv4Address(value))
            for value in range(
                int(ipaddress.IPv4Address(interval["start"])), int(ipaddress.IPv4Address(interval["end"])) + 1
            )
        )
    require(os.environ.get("HOME_DHCP_PACKET_TEST") == "1", "Run only using the documented isolated Docker command")
    require({name for _, name in socket.if_nameindex()} == {"lo"}, "Container must start with network none")
    run("ip", "link", "add", "dhcp-server", "type", "veth", "peer", "name", "dhcp-client")
    run("ip", "addr", "add", "192.0.2.254/24", "dev", "dhcp-server")
    for name in ["lo", "dhcp-server", "dhcp-client"]:
        run("ip", "link", "set", name, "up")
    Path("/usr/local/etc/dnsmasq.conf.d").mkdir(parents=True)
    Path("/var/etc").mkdir(exist_ok=True)
    for name in ["dnsmasq-hosts", "dnsmasq-leases"]:
        Path("/var/etc", name).touch()
    run("dnsmasq", "--test", "--conf-file=" + args.config)
    with tempfile.TemporaryDirectory() as directory, (Path(directory) / "daemon.log").open("w") as log:
        daemon = subprocess.Popen(  # noqa: S603 -- Fixed isolated test executable and arguments.
            [
                "/usr/local/sbin/dnsmasq",
                "--keep-in-foreground",
                "--user=root",
                "--no-ping",
                "--log-dhcp",
                "--log-facility=-",
                "--dhcp-leasefile=" + directory + "/test.leases",
                "--conf-file=" + args.config,
            ],
            stdout=log,
            stderr=log,
        )
        try:
            time.sleep(0.3)
            require(daemon.poll() is None, "Test DHCP daemon failed to start")
            client = Client()
            printer = client.lease("02:00:00:00:00:01")
            require(printer == "192.0.2.116", "Printer reservation not honored")
            for address in sorted(
                {"192.0.2.116", "192.0.2.135", "192.0.2.248", "192.0.2.249", "192.0.2.254"}
                | ({"192.0.2.110", "192.0.2.115", "192.0.2.117", "192.0.2.134"} - expected)
            ):
                for renew in [False, True]:
                    reply = client.exchange(
                        "02:00:00:ff:ff:ff",
                        3,
                        requested=None if renew else address,
                        ciaddr=address if renew else "0.0.0.0",  # noqa: S104 -- DHCP wire field.
                        selecting=not renew,
                    )
                    require(reply is None or reply[1].get(53) != b"\x05", "ACK for forbidden requested/renewed address")
            allocated = set()
            for number in range(len(expected)):
                mac = f"02:00:01:00:00:{number:02x}"
                ip = client.lease(mac, requested="192.0.2.116" if number == 0 else None)
                allocated.add(ip)
            require(allocated == expected, "Dynamic allocation must exactly exhaust both approved ranges")
            require(client.exchange("02:00:02:00:00:01", 1) is None, "Pool exhaustion offered an extra address")
            renewed = client.exchange("02:00:00:00:00:01", 3, ciaddr="192.0.2.116")
            require(renewed is not None and renewed[1].get(53) == b"\x05", "Reserved printer renewal failed")
            print(
                f"PASS: {len(expected)} unique dynamic leases, printer reservation/renewal, options, pool exhaustion, "
                "and forbidden printer/standby/excluded/gateway requests and renewals",
                flush=True,
            )
            client.socket.close()
        finally:
            daemon.terminate()
            daemon.wait(timeout=5)
            print((Path(directory) / "daemon.log").read_text()[-1500:], flush=True)


if __name__ == "__main__":
    main()
