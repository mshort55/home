#!/usr/bin/env python3
"""Prepare runtime and validation dependencies without accessing infrastructure."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APT_PACKAGES = ["cmake", "build-essential", "libssl-dev", "python3-dev", "python3-venv", "php-cli", "php-xml"]


def run(
    argv: list[str], *, capture: bool = False, check: bool = True, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=ROOT, text=True, capture_output=capture, check=check, env=env, timeout=1800)  # noqa: S603 -- Fixed setup commands with argv, never a shell.


def system_dependencies(system: str) -> None:
    if system == "Linux":
        if platform.freedesktop_os_release().get("ID") not in {"ubuntu", "debian"}:
            raise ValueError("Automatic Linux setup supports Ubuntu and Debian.")
        missing = []
        for package in APT_PACKAGES:
            result = run(["dpkg-query", "-W", "-f=${Status}", package], capture=True, check=False)
            if result.returncode or result.stdout.strip() != "install ok installed":
                missing.append(package)
        if missing:
            privilege = [] if os.geteuid() == 0 else ["sudo"]
            print("Installing missing system dependencies (sudo may request your password).", flush=True)
            run([*privilege, "apt-get", "update"])
            run([*privilege, "apt-get", "install", "--yes", "--no-install-recommends", *missing])
    else:
        if not shutil.which("brew"):
            raise ValueError(
                "Install Homebrew, then rerun setup. Homebrew installation is not performed automatically."
            )
        if run(["xcode-select", "-p"], capture=True, check=False).returncode:
            raise ValueError("Install Apple command-line tools with xcode-select --install, then rerun setup.")
        for package in ["cmake", "openssl@3", "php"]:
            if run(["brew", "list", "--versions", package], capture=True, check=False).returncode:
                run(["brew", "install", package])
    run(["bash", str(ROOT / "tools/install-php.sh")])


def prepare_environment(path: Path, requirements: str) -> Path:
    python = path / "bin/python"
    if not python.is_file():
        run([sys.executable, "-m", "venv", str(path)])
    probe = run(
        [str(python), "-c", "import json,sys; print(json.dumps([sys.prefix, list(sys.version_info[:2])]))"],
        capture=True,
    )
    prefix, version = json.loads(probe.stdout)
    if Path(prefix).resolve() != path.resolve() or tuple(version) < (3, 12):
        raise ValueError(f"{path} must be a native Python 3.12+ virtual environment; move it aside and rerun setup.")
    # The custom SSH binding must be installed before pip sees its lock entry.
    run([str(python), str(ROOT / "tools/install-ssh.py")])
    run([str(python), "-m", "pip", "install", "-r", str(ROOT / requirements)])
    run([str(python), "-m", "pip", "check"])
    run([str(python), str(ROOT / "tools/check-ssh.py")])
    return python


def native_tools_ready() -> bool:
    pins = json.loads((ROOT / "tools/native-tools.json").read_text())
    for name, pin in pins.items():
        binary = ROOT / ".cache/validation/bin" / name
        if not binary.is_file():
            return False
        try:
            result = run([str(binary), "version" if name == "gitleaks" else "--version"], capture=True, check=False)
        except OSError:
            return False
        if result.returncode or pin["version"] not in result.stdout.split():
            return False
    return True


def main() -> None:
    system = platform.system()
    if system not in {"Linux", "Darwin"} or sys.version_info < (3, 12):
        raise ValueError("Use Python 3.12+ on Ubuntu/Debian or macOS.")
    system_dependencies(system)
    suffix = "-macos" if system == "Darwin" else ""
    prepare_environment(ROOT / (".venv" + suffix), "requirements.txt")
    validation = prepare_environment(ROOT / (".venv-validation" + suffix), "requirements-dev.txt")
    # Collection setup must not load the operator's inventory, Vault configuration,
    # or inherited Ansible connection settings.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")}
    with tempfile.TemporaryDirectory(prefix="home-setup-") as directory:
        config = Path(directory) / "ansible.cfg"
        config.write_text(f"[defaults]\ncollections_path = {ROOT / '.collections'}\n")
        env["ANSIBLE_CONFIG"] = str(config)
        run(
            [
                str(validation.parent / "ansible-galaxy"),
                "collection",
                "install",
                "-r",
                str(ROOT / "collections/requirements.yml"),
                "-p",
                str(ROOT / ".collections"),
            ],
            env=env,
        )
    if not native_tools_ready():
        run([str(validation), str(ROOT / "tools/install-validation-tools.py")])
    if not native_tools_ready():
        raise ValueError("Native validation tools did not match their pins after installation.")
    for environment in [ROOT / (".venv" + suffix), ROOT / (".venv-validation" + suffix)]:
        link = environment / "bin/just"
        target = ROOT / ".cache/validation/bin/just"
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise ValueError(f"Cannot install the Just command over an existing file: {link}")
        link.symlink_to(target)
    print("Repository setup complete. Run python3 tools/run-validation.py to validate.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Repository setup failed: {error}") from None
