#!/usr/bin/env python3
"""Install checksum-pinned validation binaries in the ignored repository cache."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    pins = json.loads((root / "tools/native-tools.json").read_text())
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    target = f"{platform.system().lower()}-{machine}"
    destination = root / ".cache/validation/bin"
    destination.mkdir(parents=True, exist_ok=True)
    for name, pin in pins.items():
        if target not in pin["assets"]:
            raise SystemExit(f"Unsupported validation platform: {target}")
        asset, checksum = pin["assets"][target]
        url = f"https://github.com/{pin['repository']}/releases/download/v{pin['version']}/{asset}"
        with urllib.request.urlopen(url, timeout=60) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("Validation binary download left HTTPS")
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != checksum:
            raise ValueError(f"Validation binary checksum mismatch: {name}")
        if asset.endswith(".tar.gz"):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                member = archive.getmember(name)
                if not member.isfile() or member.size > 64 * 1024 * 1024:
                    raise ValueError(f"Unexpected validation archive member: {name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"Missing validation binary: {name}")
                data = stream.read()
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.chmod(0o755)
        temporary.replace(destination / name)
        print(f"Installed {name} {pin['version']} for {target}")


if __name__ == "__main__":
    main()
