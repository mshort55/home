"""Read-only firewall inspection supplied by the controller, never by the guest."""

from __future__ import annotations

import json
import os
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

POLICY = "/etc/home-automation/unifi-policy.nft.json"
UNIT = "/etc/systemd/system/home-unifi-isolation.service"
GUARDS = [f"/etc/systemd/system/{name}.service.d/10-home-isolation.conf" for name in ("uosserver", "uosserver-updater")]
TABLE = {"family": "inet", "name": "home_unifi"}
CHECK = f"/usr/sbin/nft --check -j -f {POLICY}"
LOAD = f"/usr/sbin/nft -j -f {POLICY}"


def read(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()  # noqa: S603 -- Fixed inspection commands; no shell.


def normalize(objects: list[dict]) -> list[dict]:
    result = []
    for item in objects:
        if set(item) == {"metainfo"}:
            continue
        if len(item) != 1 or next(iter(item)) not in {"table", "chain", "rule"}:
            raise ValueError("Unexpected object in owned firewall table")
        kind, fields = next(iter(item.items()))
        if fields.get("family") != "inet" or fields.get("name" if kind == "table" else "table") != "home_unifi":
            raise ValueError("Firewall object is outside the owned table")
        result.append({kind: {key: value for key, value in fields.items() if key != "handle"}})
    order = {"input": 0, "output": 1, "forward": 2}
    return sorted(
        result,
        key=lambda item: (
            0 if "table" in item else 1 if "chain" in item else 2,
            order.get(item.get("chain", {}).get("name", item.get("rule", {}).get("chain", "")), 3),
        ),
    )


def desired_objects(document: dict) -> list[dict]:
    commands = document.get("nftables", [])
    if set(document) != {"nftables"} or commands[:2] != [{"add": {"table": TABLE}}, {"delete": {"table": TABLE}}]:
        raise ValueError("Expected a bounded atomic table replacement")
    if not commands[2:] or any(set(command) != {"add"} for command in commands[2:]):
        raise ValueError("Unexpected firewall command")
    return normalize([command["add"] for command in commands[2:]])


def protected(filename: str, mode: int, *, optional: bool = False) -> bool:
    path = Path(filename)
    if optional and not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode:
        raise ValueError(f"Unprotected firewall artifact: {filename}")
    return True


def property_value(service: str, name: str) -> str:
    return read("systemctl", "show", service, f"--property={name}", "--value")


def require_commands(service: str, name: str, expected: list[str]) -> None:
    # Inspect effective manager properties so a later drop-in cannot silently
    # reset an Exec directive while the original unit text still looks correct.
    value = property_value(service, name)
    parsed = re.findall(r"argv\[\]=(.*?) ; ignore_errors=(yes|no)", value)
    if parsed != [(command, "no") for command in expected] or (not expected and value):
        raise ValueError(f"Effective {service} {name} differs from the managed startup guard")


def verify_units() -> None:
    service = "home-unifi-isolation.service"
    if property_value(service, "FragmentPath") != UNIT or property_value(service, "DropInPaths"):
        raise ValueError("Unexpected firewall unit or override")
    for key, expected in {
        "Type": "oneshot",
        "RemainAfterExit": "yes",
        "DefaultDependencies": "no",
        "User": "",
        "NeedDaemonReload": "no",
        "ActiveState": "active",
    }.items():
        if property_value(service, key) != expected:
            raise ValueError(f"Firewall service {key} differs")
    if read("systemctl", "is-enabled", service) != "enabled":
        raise ValueError("Firewall service must be enabled at boot")
    if not {"network-pre.target", "uosserver.service", "uosserver-updater.service"} <= set(
        property_value(service, "Before").split()
    ):
        raise ValueError("Firewall boot ordering differs")
    for key, commands in {
        "ExecStartPre": [CHECK],
        "ExecStart": [LOAD],
        "ExecReload": [LOAD],
        "ExecStop": [],
        "ExecStopPost": [],
        "ExecStartPost": [],
    }.items():
        require_commands(service, key, commands)
    for vendor, guard in zip(["uosserver.service", "uosserver-updater.service"], GUARDS, strict=True):
        expected_guard = [
            "[Unit]",
            "Requires=" + service,
            "After=" + service,
            "[Service]",
            "ExecStartPre=+" + CHECK,
            "ExecStartPre=+" + LOAD,
        ]
        if [line.strip() for line in Path(guard).read_text().splitlines() if line.strip()] != expected_guard:
            raise ValueError("Saved vendor startup guard differs")
        # Cloud-init installs guards before the vendor unit exists. Once installed,
        # inspect the effective properties too, including any later overrides.
        if property_value(vendor, "LoadState") == "not-found" and not property_value(vendor, "FragmentPath"):
            continue
        for key in ["Requires", "After"]:
            if service not in property_value(vendor, key).split():
                raise ValueError(f"{vendor} must require and follow the firewall loader")
        if property_value(vendor, "NeedDaemonReload") != "no":
            raise ValueError("Service changes have not been loaded")
        require_commands(vendor, "ExecStartPre", [CHECK, LOAD])


def inspect(payload: dict) -> dict:
    mode, settings, desired = payload["mode"], payload["settings"], payload["policy"]
    if mode not in {"plan", "verify"} or os.geteuid() != 0:
        raise ValueError("Expected a root read-only inspection")
    if socket.gethostname().split(".")[0] != settings["hostname"]:
        raise ValueError("Wrong firewall host")
    settings_path = "/etc/home-automation/unifi-isolation.json"
    protected(settings_path, 0o600)
    if json.loads(Path(settings_path).read_text()) != settings:
        raise ValueError("Guest isolation inputs differ from inventory")
    if Path("/etc/systemd/system/nftables.service").resolve() != Path("/dev/null"):
        raise ValueError("The global-flush nftables service must remain masked")
    expected = desired_objects(desired)
    tables = json.loads(read("/usr/sbin/nft", "-j", "list", "tables"))["nftables"]
    exists = any(
        item.get("table", {}).get("family") == "inet" and item.get("table", {}).get("name") == "home_unifi"
        for item in tables
    )
    observed = (
        normalize(json.loads(read("/usr/sbin/nft", "-j", "list", "table", "inet", "home_unifi"))["nftables"])
        if exists
        else []
    )
    matches = observed == expected
    present = [
        path for path in [POLICY, UNIT, *GUARDS] if protected(path, 0o600 if path == POLICY else 0o644, optional=True)
    ]
    migration = POLICY not in present
    if migration and not matches:
        raise ValueError("Legacy migration requires the existing live policy to match inventory")
    if mode == "plan":
        rollback = {
            "nftables": [{"add": {"table": TABLE}}, {"delete": {"table": TABLE}}, *({"add": item} for item in observed)]
        }
        return {"migration": migration, "live_matches": matches, "present": present, "rollback_policy": rollback}
    if migration:
        raise ValueError("Run configure-unifi-firewall.yml to migrate the legacy bootstrap firewall")
    if set(present) != {POLICY, UNIT, *GUARDS}:
        raise ValueError("Missing managed firewall startup artifacts")
    if desired_objects(json.loads(Path(POLICY).read_text())) != expected:
        raise ValueError("Saved boot firewall policy differs from inventory")
    if not matches:
        raise ValueError("Loaded firewall policy differs from inventory")
    verify_units()
    return {"isolated": True, "saved_policy": "verified", "live_policy": "verified", "startup": "verified"}


if __name__ == "__main__":
    print(json.dumps(inspect(json.load(sys.stdin))))
