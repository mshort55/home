"""Verify a pinned Fedora cloud image and its release signature on the controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FILENAME = "Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2"
SHA256 = "28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f"
SIGNER = "36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6"
ORIGIN = "https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/"
CHECKSUM = "Fedora-Cloud-44-1.7-x86_64-CHECKSUM"


def protect(path: Path, directory: bool = False) -> None:
    if path.is_symlink():
        raise ValueError("Symlink Fedora artifact")
    if path.exists():
        stat = path.stat()
        if (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError("Unexpected Fedora artifact type")
        if stat.st_uid != os.getuid() or stat.st_mode & 0o777 != (0o700 if directory else 0o600):
            raise ValueError("Unowned or unprotected Fedora artifact")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, destination: Path) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Fedora downloads require an HTTPS URL without credentials")
    protect(destination)
    if destination.exists():
        return False
    descriptor, name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    temporary = Path(name)
    try:
        with (
            os.fdopen(descriptor, "wb") as output,
            urllib.request.urlopen(url, timeout=60) as response,  # noqa: S310 -- HTTPS is required above.
        ):
            if not response.geturl().startswith("https://"):
                raise ValueError("Fedora download redirected outside HTTPS")
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["plan", "apply"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory: Path = args.directory
    if not directory.is_absolute():
        raise ValueError("Use an absolute Fedora cache directory")
    protect(directory, directory=True)
    image = directory / FILENAME
    checksum = directory / CHECKSUM
    keyring = directory / "fedora.gpg"
    manifest = directory / "completion.json"
    for path in [image, checksum, keyring, manifest]:
        protect(path)
    missing = not all(path.is_file() for path in [image, checksum, keyring])
    if args.operation == "plan" and missing:
        print(json.dumps({"changed": True, "verified": False, "filename": FILENAME}))
        return
    changed = False
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
        changed = True
    if args.operation == "apply":
        for url, destination in [(ORIGIN + CHECKSUM, checksum), ("https://fedoraproject.org/fedora.gpg", keyring)]:
            changed = download(url, destination) or changed
    # No import into the user's GPG keyring; verify against a dedicated downloaded keyring.
    with tempfile.TemporaryDirectory(prefix="fedora-gpg-") as home:
        result = subprocess.run(  # noqa: S603 -- Reviewed administrative argv; no shell.
            ["gpgv", "--homedir", home, "--status-fd", "1", "--keyring", str(keyring), str(checksum)],  # noqa: S607 -- Executable uses the trusted host/container PATH.
            check=True,
            capture_output=True,
            text=True,
        )
    if not any(line.startswith("[GNUPG:] VALIDSIG " + SIGNER + " ") for line in result.stdout.splitlines()):
        raise ValueError("Checksum was not signed by the pinned Fedora 44 release key")
    if re.findall(
        r"^SHA256 \(" + re.escape(FILENAME) + r"\) = ([0-9a-f]{64})$", checksum.read_text(), re.MULTILINE
    ) != [SHA256]:
        raise ValueError("Signed checksum differs from the pinned Fedora image")
    if args.operation == "apply":
        changed = download(ORIGIN + FILENAME, image) or changed
    if digest(image) != SHA256:
        raise ValueError("Cached Fedora image checksum differs; refusing to replace it automatically")
    content: dict[str, Any] = {
        "version": 1,
        "filename": FILENAME,
        "sha256": SHA256,
        "signer": SIGNER,
        "size": image.stat().st_size,
    }
    encoded = json.dumps(content, indent=2) + "\n"
    if not manifest.exists() or manifest.read_text() != encoded:
        changed = True
        if args.operation == "apply":
            descriptor, name = tempfile.mkstemp(prefix=".manifest-", dir=directory)
            with os.fdopen(descriptor, "w") as output:
                output.write(encoded)
            Path(name).replace(manifest)
    print(json.dumps({"changed": changed, "verified": True, **content}))


if __name__ == "__main__":
    main()
