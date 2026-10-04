"""Enroll a scoped API account through an already trusted root SSH connection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import cast

USER = "home-ansible@pve"
ROLE = "HomeAutomation"
TOKEN = "controller"
MARKER = "Managed by configure-proxmox-api.yml"
OWNERSHIP_MARKERS = {MARKER, "Managed by configure-community-api.yml"}
PRIVILEGES = sorted("Sys.Audit Datastore.Audit Datastore.AllocateSpace Datastore.AllocateTemplate SDN.Use VM.Allocate VM.Audit VM.Config.CDROM VM.Config.Cloudinit VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.PowerMgmt".split())
LEGACY_PRIVILEGES = [privilege for privilege in PRIVILEGES if privilege != "VM.Config.Cloudinit"]
DIRECTORY = Path("/root/.home-automation-api")
RECORD = DIRECTORY / "credentials.json"


def run(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout


def read(*arguments: str) -> object:
    return json.loads(run(*arguments, "--output-format", "json"))


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an API object with string keys")
    return cast(dict[str, object], value)


def records(*arguments: str) -> list[dict[str, object]]:
    value = read(*arguments)
    if not isinstance(value, list):
        raise ValueError("Expected an API record list")
    return [mapping(item) for item in value]


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected API text")
    return value


def protect(path: Path, mode: int) -> None:
    if path.is_symlink() or (path.exists() and (path.stat().st_uid != 0 or path.stat().st_mode & 0o777 != mode)):
        raise ValueError("Unowned or unprotected API artifact")


def main() -> None:
    operation, address, node = sys.argv[1:]
    if operation not in ("plan", "apply") or os.geteuid() != 0 or socket.gethostname().split(".")[0] != node:
        raise ValueError("Unexpected API enrollment host or operation")
    # openssl -checkip prints its verdict but exits zero on mismatch on some versions.
    if "does match certificate" not in run("openssl", "x509", "-in", "/etc/pve/local/pve-ssl.pem", "-noout", "-checkip", address):
        raise ValueError("Proxmox certificate does not identify the inventory IP")
    protect(DIRECTORY, 0o700)
    protect(RECORD, 0o600)
    if DIRECTORY.exists() and not DIRECTORY.is_dir() or RECORD.exists() and not RECORD.is_file():
        raise ValueError("API artifact type conflicts")
    users: list[dict[str, object]] = records("pveum", "user", "list")
    roles: list[dict[str, object]] = records("pveum", "role", "list")
    acls: list[dict[str, object]] = records("pveum", "acl", "list")
    user = next((u for u in users if u["userid"] == USER), None)
    role = next((r for r in roles if r["roleid"] == ROLE), None)
    if user and (user.get("comment") not in OWNERSHIP_MARKERS or not user.get("enable", 1) or user.get("expire", 0)):
        raise ValueError("Conflicting automation user")
    role_upgrade = bool(role and sorted(text(role["privs"]).split(",")) == LEGACY_PRIVILEGES)
    if role and sorted(text(role["privs"]).split(",")) not in [PRIVILEGES, LEGACY_PRIVILEGES]:
        raise ValueError("Conflicting automation role")
    owned_acls = [a for a in acls if a.get("ugid") == USER]
    if any(a.get("path") != "/" or a.get("roleid") != ROLE or not a.get("propagate") for a in owned_acls):
        raise ValueError("Conflicting automation ACL")
    tokens: list[dict[str, object]] = records("pveum", "user", "token", "list", USER) if user else []
    token = next((t for t in tokens if t["tokenid"] == TOKEN), None)
    if token and (not RECORD.exists() or token.get("comment") not in OWNERSHIP_MARKERS or token.get("privsep", 1) or token.get("expire", 0)):
        raise ValueError("Existing API token needs its original protected record; refusing rotation")
    if RECORD.exists() and not token:
        raise ValueError("Saved API token is absent on the host")
    if role_upgrade and not (user and token and RECORD.exists() and owned_acls):
        raise ValueError("Cloud-init privilege upgrade requires the original owned enrollment")
    if RECORD.exists():
        existing: dict[str, object] = mapping(json.loads(RECORD.read_text()))
        if existing["api_host"] != address or existing["node"] != node or existing["api_user"] != USER or existing["api_token_id"] != TOKEN:
            raise ValueError("Saved API enrollment identity conflicts")
    changed = not user or not role or not owned_acls or not token or role_upgrade
    if operation == "apply":
        if not role:
            run("pveum", "role", "add", ROLE, "--privs", " ".join(PRIVILEGES))
        elif role_upgrade:
            run("pveum", "role", "modify", ROLE, "--privs", " ".join(PRIVILEGES))
        if not user:
            run("pveum", "user", "add", USER, "--comment", MARKER)
        if not owned_acls:
            run("pveum", "acl", "modify", "/", "--users", USER, "--roles", ROLE, "--propagate", "1")
        if not token:
            DIRECTORY.mkdir(mode=0o700, exist_ok=True)
            created: dict[str, object] = mapping(read("pveum", "user", "token", "add", USER, TOKEN, "--privsep", "0", "--comment", MARKER))
            credentials = {"api_host": address, "api_user": USER, "api_token_id": TOKEN, "api_token_secret": created["value"], "node": node}
            fd = os.open(RECORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(credentials, output)
        saved: dict[str, object] = mapping(json.loads(RECORD.read_text()))
        if saved["api_host"] != address or saved["node"] != node or saved["api_user"] != USER or saved["api_token_id"] != TOKEN:
            raise ValueError("Saved API enrollment identity conflicts")
    print(json.dumps({"changed": bool(changed)}))


if __name__ == "__main__":
    main()
