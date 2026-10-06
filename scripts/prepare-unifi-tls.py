"""Prepare stable private GUI TLS inputs for the supported manual certificate upload."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=60).stdout


def main() -> None:
    operation, directory_name, address, fqdn = sys.argv[1:]
    if operation not in ["plan", "apply"] or not re.fullmatch(r"[a-z0-9.-]+", fqdn):
        raise ValueError("Use explicit TLS preparation and a bounded hostname")
    ipaddress.IPv4Address(address)
    directory = Path(directory_name)
    if directory.is_symlink() or not directory.is_absolute():
        raise ValueError("Use a private absolute TLS directory")
    certificate, key = directory / "gui-cert.pem", directory / "gui-key.pem"
    for path in [certificate, key]:
        if (
            path.is_symlink()
            or path.exists()
            and (not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600)
        ):
            raise ValueError("Unprotected GUI TLS artifact")
    if certificate.exists() != key.exists():
        raise ValueError("Incomplete GUI TLS allocation; refusing automatic key replacement")
    changed = not certificate.exists()
    if changed and operation == "apply":
        if not directory.is_dir() or directory.stat().st_mode & 0o777 != 0o700:
            raise ValueError("Prepare the protected seed directory first")
        with tempfile.TemporaryDirectory(prefix=".gui-tls-", dir=directory) as temporary:
            private = Path(temporary) / "key.pem"
            public = Path(temporary) / "cert.pem"
            run(
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-sha256",
                "-days",
                "825",
                "-subj",
                "/CN=" + fqdn,
                "-addext",
                "subjectAltName=DNS:" + fqdn + ",IP:" + address,
                "-addext",
                "basicConstraints=critical,CA:FALSE",
                "-addext",
                "extendedKeyUsage=serverAuth",
                "-keyout",
                str(private),
                "-out",
                str(public),
            )
            private.chmod(0o600)
            public.chmod(0o600)
            private.replace(key)
            public.replace(certificate)
    if certificate.exists():
        if "does match certificate" not in run(
            "openssl", "x509", "-in", str(certificate), "-noout", "-checkip", address
        ):
            raise ValueError("GUI certificate address differs")
        if "does match certificate" not in run(
            "openssl", "x509", "-in", str(certificate), "-noout", "-checkhost", fqdn
        ):
            raise ValueError("GUI certificate hostname differs")
        run("openssl", "x509", "-in", str(certificate), "-noout", "-checkend", "86400")
        if run("openssl", "x509", "-in", str(certificate), "-pubkey", "-noout") != run(
            "openssl", "pkey", "-in", str(key), "-pubout"
        ):
            raise ValueError("GUI certificate does not match its recorded private key")
    print(json.dumps({"changed": changed, "certificate": str(certificate), "private_key": str(key)}))


if __name__ == "__main__":
    main()
