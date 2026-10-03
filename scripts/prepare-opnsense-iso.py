#!/usr/bin/env python3
"""Verify an OPNsense archive/signature and atomically prepare its local ISO."""

from __future__ import annotations

import argparse
import base64
import bz2
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import TypedDict


class Manifest(TypedDict):
    schema_version: int
    version: str
    filename: str
    archive_sha256: str
    public_key_sha256: str
    iso_sha256: str
    iso_size: int
    signature_verified: bool


def regular_file(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular file, not a symlink: {path}")


def sha256(path: Path) -> str:
    regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify(image: Path, public_key: Path, signature: Path, openssl: str) -> None:
    regular_file(image)
    result = subprocess.run(
        [openssl, "dgst", "-sha256", "-verify", str(public_key),
         "-signature", str(signature), str(image)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError("OPNsense ISO signature verification failed")


def prepare(
    directory: Path, filename: str, version: str, archive_sha256: str,
    public_key: Path, public_key_sha256: str, openssl: str,
) -> tuple[Manifest, bool]:
    if Path(filename).name != filename or not filename.endswith(".iso"):
        raise ValueError("Use a single ISO filename without path components")
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("The cache must be an existing nonsymlink directory")
    archive = directory / f"{filename}.bz2"
    signature_text = directory / f"{filename}.sig"
    image = directory / filename
    manifest_path = directory / "completion.json"
    if sha256(archive) != archive_sha256:
        raise ValueError("Compressed ISO SHA-256 does not match the pinned release")
    if sha256(public_key) != public_key_sha256:
        raise ValueError("Public key SHA-256 does not match the pinned release")
    regular_file(signature_text)
    signature_bytes = base64.b64decode(b"".join(signature_text.read_bytes().split()), validate=True)
    if not signature_bytes:
        raise ValueError("Empty ISO signature")
    changed = False
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=directory) as workspace:
        signature = Path(workspace) / "signature.bin"
        signature.write_bytes(signature_bytes)
        reusable = False
        if image.exists() or image.is_symlink():
            regular_file(image)
            try:
                verify(image, public_key, signature, openssl)
                reusable = True
            except ValueError:
                reusable = False
        if not reusable:
            temporary_image = Path(workspace) / filename
            with bz2.open(archive, "rb") as source, temporary_image.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            verify(temporary_image, public_key, signature, openssl)
            temporary_image.chmod(0o600)
            os.replace(temporary_image, image)
            changed = True
        if stat.S_IMODE(image.stat().st_mode) != 0o600:
            image.chmod(0o600)
            changed = True
        manifest: Manifest = {
            "schema_version": 1, "version": version, "filename": filename,
            "archive_sha256": archive_sha256, "public_key_sha256": public_key_sha256,
            "iso_sha256": sha256(image), "iso_size": image.stat().st_size,
            "signature_verified": True,
        }
        encoded_manifest = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        if manifest_path.exists() or manifest_path.is_symlink():
            regular_file(manifest_path)
        if not manifest_path.exists() or manifest_path.read_text() != encoded_manifest:
            temporary_manifest = Path(workspace) / "completion.json"
            temporary_manifest.write_text(encoded_manifest)
            temporary_manifest.chmod(0o600)
            os.replace(temporary_manifest, manifest_path)
            changed = True
        elif stat.S_IMODE(manifest_path.stat().st_mode) != 0o600:
            manifest_path.chmod(0o600)
            changed = True
    return manifest, changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--public-key-sha256", required=True)
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args()
    manifest, changed = prepare(
        args.directory, args.filename, args.version, args.archive_sha256,
        args.public_key, args.public_key_sha256, args.openssl,
    )
    print(json.dumps({"changed": changed, "manifest": manifest}, sort_keys=True))


if __name__ == "__main__":
    main()
