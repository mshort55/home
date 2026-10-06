"""Verify the pinned Ubuntu image and official UniFi installer on the controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

IMAGE = "ubuntu-24.04-server-cloudimg-amd64.img"
IMAGE_SHA256 = "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2"
IMAGE_ORIGIN = "https://cloud-images.ubuntu.com/releases/noble/release-20260926/"
SIGNER = "D2EB44626FDDC30B513D5BB71A5D6C4C7DB87C81"
INSTALLER = "uosserver-5.1.42-x64"
INSTALLER_SHA256 = "f6111e9396a42c74016f5dde9b01fbef486a6fe69efe137935e6e38b7c22f94d"
INSTALLER_URL = "https://fw-download.ubnt.com/data/unifi-os-server/5172-linux-x64-5.1.42-12e9e3cf-8f8b-4e54-928c-76b80a10c8a4.42-x64"


def protect(path: Path, directory: bool = False) -> None:
    if path.is_symlink():
        raise ValueError("Symlink controller artifact")
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o777 != (0o700 if directory else 0o600):
            raise ValueError("Unowned or unprotected controller artifact")
        if (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError("Unexpected controller artifact type")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, path: Path) -> bool:
    protect(path)
    if path.exists():
        return False
    descriptor, name = tempfile.mkstemp(prefix=".download-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        # Resume interrupted large transfers within the private temporary file.
        for attempt in range(8):
            result = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "--max-time",
                    "240",
                    "--continue-at",
                    "-",
                    "--output",
                    name,
                    url,
                ],
                timeout=250,
            )
            if result.returncode == 0:
                break
            if result.returncode not in [18, 28, 56] or attempt == 7:
                raise subprocess.CalledProcessError(result.returncode, result.args)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["plan", "apply"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("signing_key", type=Path)
    arguments = parser.parse_args()
    directory: Path = arguments.directory
    if not directory.is_absolute():
        raise ValueError("Use an absolute artifact directory")
    protect(directory, True)
    required = [directory / name for name in [IMAGE, INSTALLER, "SHA256SUMS", "SHA256SUMS.gpg"]]
    manifest = directory / "completion.json"
    for path in [*required, manifest]:
        protect(path)
    if arguments.operation == "plan" and not all(path.exists() for path in required):
        print(json.dumps({"changed": True, "verified": False, "ubuntu": "24.04-20260926", "unifi": "5.1.42"}))
        return
    changed = False
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
        changed = True
    if arguments.operation == "apply":
        for name in ["SHA256SUMS", "SHA256SUMS.gpg"]:
            changed = download(IMAGE_ORIGIN + name, directory / name) or changed
    with tempfile.TemporaryDirectory(prefix="unifi-gpg-") as home:
        keyring = Path(home) / "cloudimage.gpg"
        subprocess.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--homedir",
                home,
                "--dearmor",
                "--output",
                str(keyring),
                str(arguments.signing_key),
            ],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            [
                "gpgv",
                "--homedir",
                home,
                "--status-fd",
                "1",
                "--keyring",
                str(keyring),
                str(directory / "SHA256SUMS.gpg"),
                str(directory / "SHA256SUMS"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    if not any(line.startswith("[GNUPG:] VALIDSIG " + SIGNER + " ") for line in result.stdout.splitlines()):
        raise ValueError("Ubuntu checksum does not have the pinned cloud-image signature")
    checksum = (directory / "SHA256SUMS").read_text()
    if re.findall(r"^([0-9a-f]{64}) [ *]" + re.escape(IMAGE) + r"$", checksum, re.MULTILINE) != [IMAGE_SHA256]:
        raise ValueError("Signed Ubuntu checksum differs from the pinned release")
    if arguments.operation == "apply":
        for url, name in [(IMAGE_ORIGIN + IMAGE, IMAGE), (INSTALLER_URL, INSTALLER)]:
            changed = download(url, directory / name) or changed
    for name, expected in [(IMAGE, IMAGE_SHA256), (INSTALLER, INSTALLER_SHA256)]:
        if digest(directory / name) != expected:
            raise ValueError("Artifact checksum differs: " + name + "; automatic replacement refused")
    value: dict[str, Any] = {
        "version": 1,
        "ubuntu_release": "20260926",
        "signer": SIGNER,
        "image_sha256": IMAGE_SHA256,
        "installer_sha256": INSTALLER_SHA256,
        "unifi_os": "5.1.42",
        "network": "10.5.67",
    }
    encoded = json.dumps(value, indent=2) + "\n"
    if not manifest.exists() or manifest.read_text() != encoded:
        changed = True
        if arguments.operation == "apply":
            descriptor, name = tempfile.mkstemp(prefix=".completion-", dir=directory)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(encoded)
            Path(name).replace(manifest)
    print(json.dumps({"changed": changed, "verified": True, **value}))


if __name__ == "__main__":
    main()
