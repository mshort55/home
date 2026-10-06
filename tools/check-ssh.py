#!/usr/bin/env python3
"""Reject outdated SSH bindings/native libraries and insecure default algorithms offline."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    import pylibsshext
    from pylibsshext.session import Session

    pins = json.loads((Path(__file__).parent / "ssh-sources.json").read_text())
    if version("ansible-pylibssh") != pins["ansible-pylibssh"]["installed_version"]:
        raise ValueError("Python SSH bindings differ from their source pin")
    if pylibsshext.__libssh_version__ != pins["libssh"]["version"]:
        raise ValueError("Native libssh differs from its security pin; run tools/install-ssh.py")
    session = Session()
    hostkeys = (session.get_ssh_options("hostkeys") or "").split(",")
    kex = (session.get_ssh_options("key_exchange_algorithms") or "").split(",")
    if not hostkeys[0] or not kex[0] or "ssh-rsa" in hostkeys or any(algorithm.endswith("sha1") for algorithm in kex):
        raise ValueError("Legacy SSH algorithms must require explicit per-device opt-in")
    try:
        session.connect(host="unused.example.test", config_file="/nonexistent-home-ssh-policy", look_for_keys=False)
    except Exception as error:
        if "SSH config file does not exist" not in str(error):
            raise ValueError("SSH config_file binding is missing or broken") from error
    else:
        raise ValueError("SSH bindings ignored a missing policy file")
    print(
        f"Verified ansible-pylibssh {version('ansible-pylibssh')} with native libssh {pylibsshext.__libssh_version__}"
    )


if __name__ == "__main__":
    main()
