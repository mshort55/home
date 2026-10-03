#!/usr/bin/env python3
"""Seed a verified DVD with management SSH access; booting alone never installs."""

from __future__ import annotations

import argparse
import base64
import hashlib
from ipaddress import IPv4Address
import json
import os
import pwd
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import cast
import xml.etree.ElementTree as ET

import bcrypt


def object_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError("Expected an object")
    return cast(dict[str, object], value)


def string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=True)
    return result.stdout + result.stderr


def write(path: Path, content: str, mode: int = 0o600) -> None:
    path.write_text(content)
    path.chmod(mode)


def node(parent: ET.Element, name: str, value: str) -> ET.Element:
    element = parent.find(name)
    if element is None:
        element = ET.SubElement(parent, name)
    element.text = value
    return element


INSPECT = r'''<?php
$base = '/usr/local/share/ansible-opnsense';
$intent = json_decode(file_get_contents("$base/intent.json"), true, 512, JSON_THROW_ON_ERROR);
$config = simplexml_load_file('/conf/config.xml');
if (!$config) { throw new Exception('Invalid configuration'); }
foreach ($intent['networks'] as $nic) {
    $section = $nic['section'];
    $if = (string)$config->interfaces->$section->if;
    if (!preg_match('/^vtnet[0-9]+$/', $if)) { throw new Exception('Unexpected interface'); }
    $info = shell_exec('/sbin/ifconfig ' . escapeshellarg($if));
    if (!preg_match('/ether\s+([0-9a-f:]+)/i', $info, $match) || strtolower($match[1]) !== $nic['mac']) {
        throw new Exception('MAC-to-role mismatch');
    }
}
if ((string)$config->interfaces->lan->ipaddr !== $intent['address'] ||
    (string)$config->interfaces->lan->subnet !== '24' ||
    !isset($config->system->ssh->enabled) || isset($config->system->ssh->passwordauth)) {
    throw new Exception('Management configuration mismatch');
}
$pub = trim(file_get_contents('/conf/sshd/ssh_host_ed25519_key.pub'));
if ($pub !== $intent['ssh_host_key']) { throw new Exception('SSH host key mismatch'); }
$root = trim(shell_exec("/sbin/mount -p | /usr/bin/awk '$2 == \"/\" {print $3}'"));
if ($root === 'cd9660') { $state = 'live'; }
elseif ($root === 'zfs') {
    $marker = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    if ($marker !== $intent) { throw new Exception('Installation marker mismatch'); }
    $state = 'installed';
} else { throw new Exception('Unexpected root filesystem'); }
echo json_encode(['state'=>$state, 'seed_id'=>$intent['seed_id'], 'filesystem'=>$root], JSON_THROW_ON_ERROR) . "\n";
'''


def build(settings: dict[str, object], source: Path, work: Path, installer: Path, password: bytes) -> None:
    address = IPv4Address(string(settings["address"]))
    if not address.is_private or address.packed[0] != 10 or address.packed[-1] in (0, 255):
        raise ValueError("Use an ordinary private 10/8 management address")
    manifest_path = work / "completion.json"
    output = work / "opnsense-bootstrap.iso"
    credentials = work / "password-hash"
    for path in (manifest_path, output, credentials):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Bootstrap artifacts must be regular nonsymlink files")
    if not 12 <= len(password) <= 72 or b"\n" in password or b"\x00" in password:
        raise ValueError("Root password must contain 12–72 UTF-8 bytes, without NUL/newline")
    password_hash = credentials.read_bytes() if credentials.is_file() and not credentials.is_symlink() else b""
    if not password_hash or not bcrypt.checkpw(password, password_hash):
        password_hash = bcrypt.hashpw(password, bcrypt.gensalt(rounds=12))
    source_sha = string(settings["source_sha256"])
    if source.is_symlink() or not source.is_file() or sha(source) != source_sha:
        raise ValueError("Source ISO checksum conflicts")
    recipe = {"settings": settings, "password_hash": password_hash.decode(),
              "builder_sha256": sha(Path(__file__)), "installer_sha256": sha(installer)}
    seed_id = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    if manifest_path.is_file() and not manifest_path.is_symlink() and output.is_file() and not output.is_symlink():
        old = object_map(json.loads(manifest_path.read_text()))
        if old.get("seed_id") == seed_id and old.get("iso_sha256") == sha(output):
            print(json.dumps({"changed": False, "seed_id": seed_id}))
            return
    # Rebuilding media changes embedded host keys; do not silently replace an existing seed.
    if manifest_path.exists() or output.exists():
        raise ValueError("Existing bootstrap differs; use a new private artifact directory for a new seed")
    write(credentials, password_hash.decode())
    with tempfile.TemporaryDirectory(prefix="build-", dir=work) as temp:
        tempdir = Path(temp)
        built = tempdir / "bootstrap.iso"
        # Native Mac/container UIDs need not exist in Debian's read-only passwd database.
        try:
            pwd.getpwuid(os.getuid())
        except KeyError:
            passwd = tempdir / "passwd"
            group = tempdir / "group"
            write(passwd, f"builder:x:{os.getuid()}:{os.getgid()}:ISO builder:/work:/bin/sh\n")
            write(group, f"builder:x:{os.getgid()}:\n")
            wrappers = list(Path('/usr/lib').glob('*/libnss_wrapper.so'))
            if len(wrappers) != 1:
                raise ValueError("Missing UID lookup wrapper")
            os.environ.update(LD_PRELOAD=str(wrappers[0]), NSS_WRAPPER_PASSWD=str(passwd), NSS_WRAPPER_GROUP=str(group))
        sample = tempdir / "sample.xml"
        report = run(["xorriso", "-osirrox", "on", "-indev", str(source), "-report_el_torito", "plain",
                      "-extract", "/usr/local/etc/config.xml.sample", str(sample)])
        # The vendor's second boot image is an embedded FAT ESP, with 4096 512-byte sectors.
        match = re.search(r"El Torito boot img\s*:\s*2\s+BIOS\s+y\s+none\s+0x0000\s+0x00\s+4096\s+(\d+)", report)
        if match is None:
            raise ValueError("Unexpected vendor DVD boot layout")
        efi = tempdir / "efiboot.img"
        with source.open("rb") as stream:
            stream.seek(int(match[1]) * 2048)
            efi.write_bytes(stream.read(4096 * 512))
        if efi.stat().st_size != 2097152 or b"FAT" not in efi.read_bytes()[:100]:
            raise ValueError("Invalid EFI image")

        assets = tempdir / "assets"
        assets.mkdir(mode=0o700)
        keys = tempdir / "keys"
        keys.mkdir(mode=0o700)
        authorized = tempdir / "authorized_keys"
        write(authorized, string(settings["authorized_keys"]))
        for line in authorized.read_text().splitlines():
            if re.match(r'^(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+(?: |$)', line) is None:
                raise ValueError("Invalid or unsupported public key")
        run(["ssh-keygen", "-lf", str(authorized)])
        for key_type in ("rsa", "ecdsa", "ed25519"):
            path = keys / f"ssh_host_{key_type}_key"
            run(["ssh-keygen", "-q", "-t", key_type, "-N", "", "-C", "", "-f", str(path)])
        host_key = (keys / "ssh_host_ed25519_key.pub").read_text().strip()
        networks_value = settings["networks"]
        if not isinstance(networks_value, list) or len(networks_value) != 5:
            raise ValueError("Expected five networks")
        networks = [object_map(nic) for nic in networks_value]
        sections = ["wan", "lan", "opt1", "opt2", "opt3"]
        intent: dict[str, object] = {"seed_id": seed_id, "address": settings["address"],
                                   "ssh_host_key": host_key,
                                   "networks": [dict(nic, section=section) for nic, section in zip(networks, sections, strict=True)]}
        write(assets / "intent.json", json.dumps(intent, sort_keys=True))
        write(assets / "inspect.php", INSPECT)
        write(assets / "install.sh", installer.read_text(), 0o700)
        shim = assets / "shim"
        shim.mkdir(mode=0o700)
        write(shim / "bsddialog", '#!/bin/sh\ncase " $* " in *" --mixedgauge "*) exit 0;; esac\necho "Unexpected installer dialog; see installer log" >&2\nexit 1\n', 0o700)

        root = ET.parse(sample).getroot()
        for tag in ("trigger_initial_wizard", "dnsmasq", "unbound"):
            item = root.find(tag)
            if item is not None:
                root.remove(item)
        system = root.find("system")
        if system is None:
            raise ValueError("Missing vendor system configuration")
        for tag in ("ipv6allow", "dnsallowoverride", "disableconsolemenu"):
            item = system.find(tag)
            if item is not None:
                system.remove(item)
        node(system, "hostname", string(settings["hostname"]))
        node(system, "domain", string(settings["domain"]))
        node(system, "timezone", string(settings["timezone"]))
        hardware = node(node(root, "OPNsense", ""), "Interfaces", "")
        hwsettings = node(hardware, "settings", "")
        for tag in ("disablechecksumoffloading", "disablesegmentationoffloading", "disablelargereceiveoffloading"):
            node(hwsettings, tag, "1")
        user = system.find("user")
        if user is None:
            raise ValueError("Missing root user")
        node(user, "password", password_hash.decode())
        public_keys = string(settings["authorized_keys"])
        node(user, "authorizedkeys", base64.b64encode(public_keys.encode()).decode())
        ssh = node(system, "ssh", "")
        node(ssh, "enabled", "1")
        node(ssh, "permitrootlogin", "1")
        node(ssh, "interfaces", "lan")
        interfaces = root.find("interfaces")
        if interfaces is None:
            raise ValueError("Missing interface definitions")
        interfaces.clear()
        for nic, section in zip(networks, sections, strict=True):
            iface = ET.SubElement(interfaces, section)
            node(iface, "if", f"SEED_{section.upper()}")
            node(iface, "descr", string(nic["role"]))
            # Optional interfaces stay assigned but disabled until firewall policy is configured.
            if section in ("wan", "lan"):
                node(iface, "enable", "1")
                node(iface, "ipaddr", "dhcp" if section == "wan" else string(settings["address"]))
            if section == "lan":
                node(iface, "subnet", "24")
        # Bootstrap management may reach the firewall itself; no forwarding policy is installed.
        modern_rules = root.find("OPNsense/Firewall/Filter/rules")
        if modern_rules is not None:
            for rule in list(modern_rules):
                if rule.findtext("ipprotocol") != "inet":
                    modern_rules.remove(rule)
                else:
                    node(rule, "destination_net", "(self)")
                    node(rule, "description", "Bootstrap MGMT to firewall")
        nat_mode = root.find("nat/outbound/mode")
        if nat_mode is not None:
            nat_mode.text = "disabled"
        config = tempdir / "config.xml"
        write(config, ET.tostring(root, encoding="unicode"))
        hook = tempdir / "05-ansible-seed"
        lines = ["#!/bin/sh", "set -eu", "[ \"$(mount -p | awk '$2 == \"/\" {print $3}')\" = cd9660 ] || exit 0"]
        for nic, section in zip(networks, sections, strict=True):
            mac = string(nic["mac"])
            if re.fullmatch(r"02:(?:[0-9a-f]{2}:){4}[0-9a-f]{2}", mac) is None:
                raise ValueError("Invalid stable MAC")
            lines += [f"found=", "for iface in $(ifconfig -l); do",
                      f"  if ifconfig \"$iface\" | grep -q 'ether {mac}'; then [ -z \"$found\" ] || exit 1; found=$iface; fi", "done",
                      "[ -n \"$found\" ] || exit 1",
                      f"sed -i '' \"s/SEED_{section.upper()}/$found/g\" /conf/config.xml"]
        write(hook, "\n".join(lines) + "\n", 0o700)
        args = ["xorriso", "-indev", str(source), "-outdev", str(built), "-boot_image", "any", "discard",
                "-map", str(config), "/conf/config.xml", "-map", str(keys), "/conf/sshd",
                "-map", str(assets), "/usr/local/share/ansible-opnsense",
                "-map", str(hook), "/usr/local/etc/rc.syshook.d/import/05-ansible-seed",
                "-map", str(efi), "/boot/ansible-efiboot.img",
                "-uid", "0", "-gid", "0", "-boot_image", "any", "cat_path=/boot/ansible-boot.cat",
                "-boot_image", "any", "bin_path=/boot/cdboot", "-boot_image", "any", "load_size=2048",
                "-boot_image", "any", "next", "-boot_image", "any", "efi_path=/boot/ansible-efiboot.img", "-commit"]
        run(args)
        built.chmod(0o600)
        # Verify exact seeded bytes and the real UEFI boot catalog before recording completion.
        verified = tempdir / "verified.xml"
        verified_efi = tempdir / "verified-efi.img"
        report = run(["xorriso", "-osirrox", "on", "-indev", str(built), "-report_el_torito", "plain",
                      "-extract", "/conf/config.xml", str(verified),
                      "-extract", "/boot/ansible-efiboot.img", str(verified_efi)])
        if verified.read_bytes() != config.read_bytes() or sha(verified_efi) != sha(efi) or not re.search(r"boot img\s*:\s*2\s+UEFI\s+y", report):
            raise ValueError("Seeded media verification failed")
        os.replace(built, output)
        write(work / "ssh-host-key.pub", host_key + "\n")
        completion = dict(intent, schema_version=1, source_sha256=source_sha,
                          iso_sha256=sha(output), iso_size=output.stat().st_size,
                          settings=settings, efi_boot_verified=True)
        write(manifest_path, json.dumps(completion, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"changed": True, "seed_id": seed_id}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--installer", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    build(object_map(json.loads(args.settings.read_text())), args.source, args.work, args.installer, sys.stdin.buffer.read())


if __name__ == "__main__":
    main()
