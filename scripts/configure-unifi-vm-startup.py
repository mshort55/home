"""Set only the owned controller's host startup options over trusted root SSH."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any

STARTUP = "order=2,up=30,down=120"


def inspect(allocation: dict[str, Any], node: str, probe: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", probe, json.dumps(allocation), node],
        check=True,
        capture_output=True,
        text=True,
    )
    observed: dict[str, Any] = json.loads(result.stdout)
    if not observed.get("exists") or observed["previous"].get("phase") not in ["pending", "complete"]:
        raise ValueError("Require the recorded owned VM before changing host startup")
    return observed


def configure(operation: str, allocation: dict[str, Any], node: str, probe: str) -> dict[str, Any]:
    if operation not in ["prepare", "enable"] or allocation.get("vmid") != 110:
        raise ValueError("Use an explicit VM 110 startup operation")
    before = inspect(allocation, node, probe)
    config = before["config"]
    startup = dict(item.split("=", 1) for item in str(config.get("startup", "")).split(",") if "=" in item)
    changes: list[str] = []
    if startup != {"order": "2", "up": "30", "down": "120"}:
        if operation != "prepare" or before["state"] != "stopped" or before["previous"]["phase"] != "pending":
            raise ValueError("Set initial startup ordering only on the stopped pending guest")
        changes += ["--startup", STARTUP]
    if operation == "enable" and str(config.get("onboot", 0)) != "1":
        if before["state"] != "running" or not before["has_disk"] or config.get("boot") != "order=scsi0":
            raise ValueError("Require the running owned disk boot before enabling automatic startup")
        changes += ["--onboot", "1"]
    if changes:
        digest = config.get("digest", "")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{40}", digest) is None:
            raise ValueError("Require the current VM configuration digest")
        subprocess.run(["qm", "set", "110", "--digest", digest, *changes], check=True, capture_output=True, text=True)
        after = inspect(allocation, node, probe)
        excluded = {"digest", "startup", "onboot"}
        if {key: value for key, value in config.items() if key not in excluded} != {
            key: value for key, value in after["config"].items() if key not in excluded
        } or after["state"] != before["state"]:
            raise ValueError("Unrelated VM hardware or power changed during startup configuration")
        loaded = dict(item.split("=", 1) for item in after["config"].get("startup", "").split(",") if "=" in item)
        if loaded != {"order": "2", "up": "30", "down": "120"}:
            raise ValueError("Controller startup order did not persist")
        expected_onboot = "1" if operation == "enable" else str(config.get("onboot", 0))
        if str(after["config"].get("onboot", 0)) != expected_onboot:
            raise ValueError("Controller automatic startup changed unexpectedly")
    return {"changed": bool(changes), "operation": operation}


def main() -> None:
    operation, encoded, node, probe = sys.argv[1:]
    print(json.dumps(configure(operation, json.loads(encoded), node, probe)))


if __name__ == "__main__":
    main()
