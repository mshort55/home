#!/usr/bin/env python3
"""Build and verify one private unattended ISO using the official Proxmox tool."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast


class BuildError(Exception):
    """An input or build stage could not be verified."""


class Arguments(argparse.Namespace):
    settings: Path
    source: Path
    work_dir: Path


@dataclass(frozen=True)
class Settings:
    fqdn: str
    mailto: str
    country: str
    keyboard: str
    timezone: str
    cidr: str
    dns: str
    gateway: str
    disk_serial: str
    management_mac: str
    source_sha256: str
    ssh_public_keys: tuple[str, ...]
    maxroot: int
    swapsize: int
    minfree: int


def require_string(data: dict[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value or any(char in value for char in "\0\r\n"):
        raise BuildError(f"Invalid {name} setting")
    return value


def require_integer(data: dict[str, object], name: str, minimum: int) -> int:
    value = data.get(name)
    if type(value) is not int or value < minimum:
        raise BuildError(f"Invalid {name} setting")
    return value


def read_settings(path: Path) -> Settings:
    raw: object = json.loads(path.read_text())
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise BuildError("Settings must be a JSON object")
    data = cast(dict[str, object], raw)
    keys = data.get("ssh_public_keys")
    if not isinstance(keys, list) or not keys or not all(isinstance(key, str) for key in keys):
        raise BuildError("Supply at least one SSH public key")
    public_keys = tuple(cast(list[str], keys))
    for key in public_keys:
        parts = key.split()
        if len(parts) < 2 or any(char in key for char in "\0\r\n"):
            raise BuildError("Invalid SSH public key")
        if parts[0] not in (
            "ssh-ed25519",
            "ssh-rsa",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
        ):
            raise BuildError("Unsupported SSH public key type")
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except ValueError as error:
            raise BuildError("Invalid SSH public key encoding") from error
        algorithm = parts[0].encode()
        if (
            len(blob) <= 4 + len(algorithm)
            or blob[:4] != len(algorithm).to_bytes(4, "big")
            or blob[4 : 4 + len(algorithm)] != algorithm
        ):
            raise BuildError("SSH public key algorithm does not match its encoding")
    settings = Settings(
        fqdn=require_string(data, "fqdn"),
        mailto=require_string(data, "mailto"),
        country=require_string(data, "country"),
        keyboard=require_string(data, "keyboard"),
        timezone=require_string(data, "timezone"),
        cidr=require_string(data, "cidr"),
        dns=require_string(data, "dns"),
        gateway=require_string(data, "gateway"),
        disk_serial=require_string(data, "disk_serial"),
        management_mac=require_string(data, "management_mac"),
        source_sha256=require_string(data, "source_sha256"),
        ssh_public_keys=public_keys,
        maxroot=require_integer(data, "maxroot", 1),
        swapsize=require_integer(data, "swapsize", 0),
        minfree=require_integer(data, "minfree", 0),
    )
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", settings.disk_serial):
        raise BuildError("Disk serial must be exact, without glob patterns")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", settings.management_mac):
        raise BuildError("Management MAC must be a lowercase full MAC address")
    if not re.fullmatch(r"[0-9a-f]{64}", settings.source_sha256):
        raise BuildError("Supply the expected source ISO SHA-256")
    try:
        network = ipaddress.IPv4Interface(settings.cidr)
        gateway = ipaddress.IPv4Address(settings.gateway)
        dns = ipaddress.IPv4Address(settings.dns)
    except ValueError as error:
        raise BuildError("Invalid static IPv4 network setting") from error
    if network.network.prefixlen > 30 or network.ip in (
        network.network.network_address,
        network.network.broadcast_address,
    ):
        raise BuildError("Management address must be a usable host on a subnet")
    if (
        gateway not in network.network
        or gateway == network.ip
        or gateway in (network.network.network_address, network.network.broadcast_address)
    ):
        raise BuildError("Gateway must be another usable host on the management subnet")
    if dns.is_unspecified or dns.is_multicast:
        raise BuildError("DNS must be a specific unicast address")
    return settings


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_step(argv: list[str], log: Path, stage: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    with log.open("a") as stream:
        stream.write(f"\n{stage}: exit {result.returncode}\n")
        stream.write(result.stdout)
        stream.write(result.stderr)
    if result.returncode or re.search(r"^Error(?:[: ])", result.stdout + result.stderr, re.MULTILINE):
        raise BuildError(f"{stage} failed; inspect the private build.log")
    return result.stdout + result.stderr


def write_answer(path: Path, settings: Settings, password_hash: str) -> None:
    def quoted(value: str) -> str:
        return json.dumps(value, ensure_ascii=True)

    text = "\n".join(
        (
            "[global]",
            f"keyboard = {quoted(settings.keyboard)}",
            f"country = {quoted(settings.country)}",
            f"fqdn = {quoted(settings.fqdn)}",
            f"mailto = {quoted(settings.mailto)}",
            f"timezone = {quoted(settings.timezone)}",
            f"root-password-hashed = {quoted(password_hash)}",
            f"root-ssh-keys = {json.dumps(settings.ssh_public_keys)}",
            "",
            "[network]",
            'source = "from-answer"',
            f"cidr = {quoted(settings.cidr)}",
            f"dns = {quoted(settings.dns)}",
            f"gateway = {quoted(settings.gateway)}",
            f"filter.ID_NET_NAME_MAC = {quoted('enx' + settings.management_mac.replace(':', ''))}",
            "",
            "[disk-setup]",
            'filesystem = "ext4"',
            f"filter.ID_SERIAL = {quoted(settings.disk_serial)}",
            f"lvm.maxroot = {settings.maxroot}",
            f"lvm.swapsize = {settings.swapsize}",
            f"lvm.minfree = {settings.minfree}",
            "",
        )
    )
    path.write_text(text)
    path.chmod(0o600)


def build(arguments: Arguments) -> None:
    os.umask(0o077)
    settings = read_settings(arguments.settings)
    source_stat = arguments.source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size == 0:
        raise BuildError("Source ISO must be a regular, nonempty, nonsymlink file")
    if checksum(arguments.source) != settings.source_sha256:
        raise BuildError("Source ISO does not match the expected SHA-256")
    if not arguments.work_dir.is_dir() or arguments.work_dir.is_symlink():
        raise BuildError("Work directory must be an existing, nonsymlink directory")
    answer = arguments.work_dir / "answer.toml"
    output = arguments.work_dir / "proxmox-auto.iso"
    manifest = arguments.work_dir / "completion.json"
    if any(path.exists() for path in (answer, output, manifest)):
        raise BuildError("Use a fresh work directory; existing artifacts are never overwritten")
    log = arguments.work_dir / "build.log"
    log.touch(mode=0o600, exist_ok=False)
    password = sys.stdin.read()
    if len(password) < 8 or any(char in password for char in "\0\r\n"):
        raise BuildError("Root password must have at least eight characters and no NUL or newline")
    hashed = subprocess.run(
        ["mkpasswd", "--method=yescrypt", "--stdin"],
        input=password,
        capture_output=True,
        text=True,
        check=False,
    )
    del password
    password_hash = hashed.stdout.strip()
    if hashed.returncode or not re.fullmatch(r"\$y\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+", password_hash):
        raise BuildError("Root password hashing failed")
    write_answer(answer, settings, password_hash)
    run_step(["proxmox-auto-install-assistant", "validate-answer", str(answer)], log, "Answer validation")
    staging = arguments.work_dir / "staging"
    staging.mkdir(mode=0o700)
    run_step(
        [
            "proxmox-auto-install-assistant",
            "prepare-iso",
            str(arguments.source),
            "--fetch-from",
            "iso",
            "--answer-file",
            str(answer),
            "--output",
            str(output),
            "--tmp",
            str(staging),
        ],
        log,
        "ISO preparation",
    )
    output.chmod(0o600)
    verification = arguments.work_dir / "verification"
    verification.mkdir(mode=0o700)
    boot_report = run_step(
        [
            "xorriso",
            "-osirrox",
            "on",
            "-indev",
            str(output),
            "-extract",
            "/answer.toml",
            str(verification / "answer.toml"),
            "-extract",
            "/auto-installer-mode.toml",
            str(verification / "auto-installer-mode.toml"),
            "-report_el_torito",
            "plain",
        ],
        log,
        "Embedded answers and boot catalog verification",
    )
    for extracted in verification.iterdir():
        extracted.chmod(0o600)
    if (verification / "answer.toml").read_bytes() != answer.read_bytes():
        raise BuildError("Embedded answer file does not match the validated answer")
    with (verification / "auto-installer-mode.toml").open("rb") as stream:
        mode: dict[str, object] = tomllib.load(stream)
    if mode.get("mode") != "iso":
        raise BuildError("ISO is not configured to fetch embedded answers")
    if not re.search(r"El Torito boot img\s*:[^\n]*\bUEFI\b", boot_report):
        raise BuildError("Generated ISO has no verified UEFI boot image")
    source_after = arguments.source.stat()
    if (source_stat.st_size, source_stat.st_mtime_ns) != (source_after.st_size, source_after.st_mtime_ns) or checksum(
        arguments.source
    ) != settings.source_sha256:
        raise BuildError("Source ISO changed during the build")
    package = run_step(
        ["dpkg-query", "-W", "-f=${Version}", "proxmox-auto-install-assistant"], log, "Preparation tool version"
    ).strip()
    record = {
        "iso_filename": output.name,
        "iso_sha256": checksum(output),
        "iso_bytes": output.stat().st_size,
        "source_sha256": settings.source_sha256,
        "answer_sha256": checksum(answer),
        "assistant_version": package,
        "disk_serial": settings.disk_serial,
        "management_mac": settings.management_mac,
        "fqdn": settings.fqdn,
        "cidr": settings.cidr,
        "ssh_key_count": len(settings.ssh_public_keys),
        "root_password_storage": "yescrypt hash",
        "uefi_boot_image_verified": True,
        "embedded_answers_verified": True,
    }
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    manifest.chmod(0o600)
    print("Verified private unattended ISO and completion.json created.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    arguments = parser.parse_args(namespace=Arguments())
    try:
        build(arguments)
    except (BuildError, OSError, ValueError) as error:
        print(f"ISO preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
