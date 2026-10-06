"""Read-only checks for the standalone Proxmox 9 package workflow."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from functools import cmp_to_key
from pathlib import Path
from typing import cast

import apt_pkg
from debian.deb822 import Deb822

SOURCES = Path("/etc/apt/sources.list.d")
KEYRING = "/usr/share/keyrings/proxmox-archive-keyring.gpg"
PROTECTED = [
    Path("/etc/network/interfaces"),
    Path("/etc/network/interfaces.d/ansible-guest-bridges"),
    Path("/etc/pve/storage.cfg"),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout.strip()


def regular(path: Path) -> None:
    require(path.is_file() and not path.is_symlink(), f"Expected a nonsymlink regular file: {path}")
    require(path.stat().st_uid == 0 and not path.stat().st_mode & 0o022, f"Unprotected host file: {path}")


def records(path: Path) -> list[dict[str, str]]:
    regular(path)
    return [
        {str(key): str(value) for key, value in paragraph.items()}
        for paragraph in Deb822.iter_paragraphs(path.read_text())
    ]


def repository_specs(channel: str) -> list[dict[str, object]]:
    require(channel in {"enterprise", "no-subscription"}, "Unknown repository channel")
    return [
        {
            "name": "pve-enterprise",
            "uri": "https://enterprise.proxmox.com/debian/pve",
            "component": "pve-enterprise",
            "enabled": channel == "enterprise",
        },
        {
            "name": "proxmox",
            "uri": "http://download.proxmox.com/debian/pve",
            "component": "pve-no-subscription",
            "enabled": channel == "no-subscription",
        },
        {
            "name": "ceph",
            "uri": ("https://enterprise.proxmox.com" if channel == "enterprise" else "http://download.proxmox.com")
            + "/debian/ceph-squid",
            "component": "enterprise" if channel == "enterprise" else "no-subscription",
            "enabled": True,
        },
    ]


def repository_body(spec: dict[str, object]) -> str:
    # Match deb822_repository's sorted fields, including its repository name.
    paragraph = Deb822()
    for key, value in [
        ("Architectures", "amd64"),
        ("Components", spec["component"]),
        ("Enabled", "yes" if spec["enabled"] else "no"),
        ("X-Repolib-Name", spec["name"]),
        ("Signed-By", KEYRING),
        ("Suites", "trixie"),
        ("Types", "deb"),
        ("URIs", spec["uri"]),
    ]:
        paragraph[key] = str(value)
    return str(paragraph.dump())


def inspect_sources(channel: str) -> dict[str, object]:
    require(SOURCES.is_dir() and not SOURCES.is_symlink(), "Unexpected APT sources directory")
    expected_names = {"debian.sources", "pve-enterprise.sources", "proxmox.sources", "ceph.sources"}
    active_paths = [path for path in SOURCES.iterdir() if path.suffix in {".sources", ".list"}]
    require(all(path.name in expected_names for path in active_paths), "Unmanaged APT sources require separate review")
    legacy = Path("/etc/apt/sources.list")
    if legacy.exists() or legacy.is_symlink():
        regular(legacy)
        require(
            not any(line.strip() and not line.lstrip().startswith("#") for line in legacy.read_text().splitlines()),
            "Active legacy APT sources require separate review",
        )
    debian = records(SOURCES / "debian.sources")
    require(len(debian) == 2, "Expected the two installed Debian base/security sources")
    for source in debian:
        require(
            set(source) <= {"Types", "URIs", "Suites", "Components", "Signed-By", "Enabled", "X-Repolib-Name"},
            "Unexpected Debian source options",
        )
        require(
            source.get("Types") in {"deb", "deb deb-src"} and source.get("Enabled", "yes") == "yes",
            "Disabled or unsupported Debian source",
        )
        require(
            source.get("Components") == "main contrib non-free-firmware"
            and source.get("Signed-By") == "/usr/share/keyrings/debian-archive-keyring.gpg",
            "Unexpected Debian components or signing key",
        )
    require(
        {(source["URIs"].rstrip("/"), source["Suites"]) for source in debian}
        in [
            {
                ("http://deb.debian.org/debian", "trixie trixie-updates"),
                ("http://security.debian.org/debian-security", "trixie-security"),
            },
            {
                ("https://deb.debian.org/debian", "trixie trixie-updates"),
                ("https://security.debian.org/debian-security", "trixie-security"),
            },
        ],
        "Debian release or source identity conflicts",
    )
    allowed: dict[str, set[tuple[str, str]]] = {
        "pve-enterprise.sources": {("https://enterprise.proxmox.com/debian/pve", "pve-enterprise")},
        "proxmox.sources": {("http://download.proxmox.com/debian/pve", "pve-no-subscription")},
        "ceph.sources": {
            ("https://enterprise.proxmox.com/debian/ceph-squid", "enterprise"),
            ("http://download.proxmox.com/debian/ceph-squid", "no-subscription"),
        },
    }
    for name, identities in allowed.items():
        path = SOURCES / name
        if path.exists() or path.is_symlink():
            sources = records(path)
            require(len(sources) == 1, f"Expected one bounded repository in {name}")
            source = sources[0]
            require(
                set(source)
                <= {"Types", "URIs", "Suites", "Components", "Signed-By", "Enabled", "X-Repolib-Name", "Architectures"},
                f"Unexpected repository options in {name}",
            )
            require(
                (source.get("URIs", "").rstrip("/"), source.get("Components", "")) in identities,
                f"Conflicting repository in {name}",
            )
            require(
                source.get("Types") == "deb"
                and source.get("Suites") == "trixie"
                and source.get("Signed-By") == KEYRING
                and source.get("Enabled", "yes") in {"yes", "no"},
                f"Release, signing key or enablement conflicts in {name}",
            )
            require(source.get("Architectures", "amd64") == "amd64", f"Unexpected architecture in {name}")
    regular(Path(KEYRING))
    specs = repository_specs(channel)
    changed = any(
        not (SOURCES / (str(spec["name"]) + ".sources")).exists()
        or (SOURCES / (str(spec["name"]) + ".sources")).read_text() != repository_body(spec)
        for spec in specs
    )
    files = sorted([str(path) for path in active_paths] + ([str(legacy)] if legacy.exists() else []))
    return {
        "repositories": specs,
        "repositories_changed": changed,
        "repository_files": files,
        "debian_sha256": hashlib.sha256((SOURCES / "debian.sources").read_bytes()).hexdigest(),
    }


def compare_versions(left: str, right: str) -> int:
    return int(apt_pkg.version_compare(left, right))


def main() -> None:
    channel, node = sys.argv[1:]
    require(os.geteuid() == 0 and socket.gethostname().split(".")[0] == node, "Unexpected package-management host")
    require(platform.machine() == "x86_64", "This workflow requires an amd64 Proxmox host")
    release = platform.freedesktop_os_release()
    require(
        release.get("ID") == "debian" and release.get("VERSION_CODENAME") == "trixie",
        "This workflow requires Debian 13 trixie",
    )
    require(run("pveversion").startswith("pve-manager/9."), "This workflow requires Proxmox VE 9")
    require(
        not Path("/etc/pve/corosync.conf").exists() and not Path("/etc/pve/ceph.conf").exists(),
        "Cluster or local Ceph maintenance requires a separate workflow",
    )
    require(not run("dpkg", "--audit"), "Repair the incomplete dpkg transaction before host updates")
    require(not run("apt-mark", "showhold"), "Held packages require separate review")
    require(
        run("dpkg-query", "-W", "-f=${db:Status-Status}", "proxmox-ve") == "installed", "Proxmox meta-package is absent"
    )
    require(
        run("dpkg-query", "-W", "-f=${Version}", "ceph-common").startswith("19."),
        "This workflow preserves Ceph 19 Squid client packages",
    )
    run("/usr/bin/python3", "-c", "import apt, debian.deb822")
    subscription = cast(
        dict[str, object], json.loads(run("pvesh", "get", "/nodes/localhost/subscription", "--output-format", "json"))
    )
    if channel == "enterprise":
        require(subscription.get("status") == "active", "The enterprise channel requires an active subscription")
    storage = cast(list[dict[str, object]], json.loads(run("pvesh", "get", "/storage", "--output-format", "json")))
    require(
        all(item.get("type") not in {"rbd", "cephfs"} for item in storage),
        "External Ceph storage requires a separate repository review",
    )
    protected: dict[str, str] = {}
    for path in PROTECTED:
        regular(path)
        protected[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    free_root = os.statvfs("/")
    free_boot = os.statvfs("/boot")
    require(free_root.f_bavail * free_root.f_frsize >= 4 * 1024**3, "At least 4 GiB free root space is required")
    require(free_boot.f_bavail * free_boot.f_frsize >= 512 * 1024**2, "At least 512 MiB free boot space is required")
    apt_pkg.init_system()
    kernels = sorted(
        [path.name.removeprefix("vmlinuz-") for path in Path("/boot").glob("vmlinuz-*-pve")],
        key=cmp_to_key(compare_versions),
    )
    require(bool(kernels), "No installed Proxmox kernel image")
    running = platform.uname().release
    routes = cast(list[dict[str, object]], json.loads(run("ip", "-j", "route", "show", "default")))
    require(len(routes) == 1, "Expected one management default route")
    route = {key: routes[0].get(key) for key in ["dev", "gateway"]}
    result = inspect_sources(channel)
    result.update(
        {
            "protected_sha256": protected,
            "default_route": route,
            "running_kernel": running,
            "latest_installed_kernel": kernels[-1],
            "reboot_needed": Path("/var/run/reboot-required").exists() or compare_versions(kernels[-1], running) > 0,
            "pveversion": run("pveversion"),
        }
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
