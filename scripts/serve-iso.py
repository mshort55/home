#!/usr/bin/env python3
"""Serve one verified ISO with byte ranges on a dedicated local IPv4 address."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from typing import cast, override
from urllib.parse import quote


class ISOArguments(argparse.Namespace):
    image: Path
    bind: str
    allow_client: str
    port: int
    sha256: str


class ISOHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        image_fd: int,
        image_identity: tuple[int, int],
        image_path: str,
        allowed_clients: set[str],
        etag: str,
    ) -> None:
        self.image_fd: int = image_fd
        self.image_identity: tuple[int, int] = image_identity
        self.image_path: str = image_path
        self.allowed_clients: set[str] = allowed_clients
        self.etag: str = etag
        super().__init__(server_address, ISOHandler)


class ISOHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HomeISOServer/1"
    sys_version = ""

    @property
    def iso_server(self) -> ISOHTTPServer:
        # The HTTP framework types this as a generic server; our constructor
        # always registers this handler with ISOHTTPServer.
        return cast(ISOHTTPServer, self.server)

    @override
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def do_HEAD(self) -> None:
        self.serve_image(head_only=True)

    def do_GET(self) -> None:
        self.serve_image(head_only=False)

    def serve_image(self, head_only: bool) -> None:
        server = self.iso_server
        if self.client_address[0] not in server.allowed_clients:
            self.send_error(403)
            return
        if self.path != server.image_path:
            self.send_error(404)
            return
        current = os.fstat(server.image_fd)
        if (current.st_size, current.st_mtime_ns) != server.image_identity:
            self.send_error(503, "ISO changed; stop hosting and verify the new image")
            return

        size = current.st_size
        start, end = 0, size - 1
        byte_range = self.headers.get("Range")
        if_range = self.headers.get("If-Range")
        if if_range and if_range not in (server.etag, self.date_time_string(current.st_mtime)):
            byte_range = None
        if byte_range:
            match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", byte_range)
            valid = False
            if match is not None and any(match.groups()):
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                    valid = True
                else:
                    suffix = int(last)
                    start = max(0, size - suffix)
                    valid = suffix > 0
                valid = valid and start < size and start <= end
            if not valid:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", server.etag)
        self.send_header("Last-Modified", self.date_time_string(current.st_mtime))
        self.send_header("Cache-Control", "no-store")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        try:
            position = start
            while position <= end:
                chunk = os.pread(server.image_fd, min(1024 * 1024, end - position + 1), position)
                if not chunk:
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                position += len(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    @override
    def log_message(self, format_string: str, *args: object) -> None:
        # Keep request paths/headers out of logs, including rejected requests.
        if len(args) >= 2 and str(args[1]).isdigit():
            method = self.command if self.command in ("GET", "HEAD") else "OTHER"
            has_range = hasattr(self, "headers") and "Range" in self.headers
            print(
                f"{self.client_address[0]} HTTP {args[1]} method={method} range={has_range}",
                flush=True,
            )


def ipv4(value: str) -> str:
    try:
        address = IPv4Address(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use an IPv4 address") from error
    if address.is_unspecified or address.is_multicast or address == IPv4Address("255.255.255.255"):
        raise argparse.ArgumentTypeError("Use a specific unicast IPv4 address")
    return str(address)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--bind", required=True, type=ipv4)
    parser.add_argument("--allow-client", required=True, type=ipv4)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(namespace=ISOArguments())
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port between 1024 and 65535")
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256):
        parser.error("Supply the expected lowercase SHA-256")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.iso", args.image.name):
        parser.error("Use an ISO filename containing only letters, digits, dots, underscores or hyphens")

    image_fd = os.open(args.image, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(image_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size == 0:
            parser.error("Select a regular, nonempty ISO file")
        digest = hashlib.sha256()
        position = 0
        while position < before.st_size:
            chunk = os.pread(image_fd, min(4 * 1024 * 1024, before.st_size - position), position)
            if not chunk:
                parser.error("ISO changed while verifying")
            digest.update(chunk)
            position += len(chunk)
        after = os.fstat(image_fd)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            parser.error("ISO changed while verifying")
        if digest.hexdigest() != args.sha256:
            parser.error("ISO SHA-256 does not match")
        with ISOHTTPServer(
            (args.bind, args.port),
            image_fd=image_fd,
            image_identity=(after.st_size, after.st_mtime_ns),
            image_path="/" + quote(args.image.name, safe=""),
            allowed_clients={args.bind, args.allow_client},
            etag='"' + args.sha256 + '"',
        ) as server:
            print(
                f"Serving {after.st_size} verified bytes at http://{args.bind}:{args.port}{server.image_path}",
                flush=True,
            )
            print("Allowed clients: " + ", ".join(sorted(server.allowed_clients)), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        os.close(image_fd)


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        sys.exit(f"ISO server could not start: {error}")
