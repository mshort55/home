#!/usr/bin/env python3
"""Build checksum-pinned libssh into the Python bindings in the active virtual environment."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def extract_source(data: bytes, checksum: str, destination: Path) -> Path:
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("SSH source checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        if sum(member.size for member in members) > 128 * 1024 * 1024:
            raise ValueError("SSH source archive is too large")
        tops = {Path(member.name).parts[0] for member in members}
        if len(tops) != 1:
            raise ValueError("SSH source archive must have one root directory")
        archive.extractall(destination, filter="data")
    return destination / tops.pop()


def download_source(url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("SSH sources require an HTTPS URL without credentials")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 -- HTTPS is required above.
        if not response.geturl().startswith("https://"):
            raise ValueError("SSH source download left HTTPS")
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("SSH source download is too large")
    return data


def run(arguments: list[str], log: Path, env: dict[str, str] | None = None) -> None:
    with log.open("a") as stream:
        subprocess.run(arguments, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)  # noqa: S603 -- Reviewed administrative argv; no shell.


def enable_config_file(source: Path) -> None:
    # Upstream 1.4.0 ignores the config_file keyword that Ansible documents.
    # Add only that missing binding; keep every compatibility setting in the
    # repository file selected for this device, rather than global SSH defaults.
    changes = {
        "src/pylibsshext/includes/libssh.pxd": (
            "    int ssh_connect(ssh_session session)\n",
            "    int ssh_options_parse_config(ssh_session session, const char *filename)\n"
            "    int ssh_connect(ssh_session session)\n",
        ),
        "src/pylibsshext/session.pyx": (
            "        if libssh.ssh_connect(self._libssh_session) != libssh.SSH_OK:\n",
            "        if kwargs.get('config_file'):\n"
            "            from os.path import isfile\n"
            "            config_file = kwargs['config_file']\n"
            "            if not isfile(config_file):\n"
            "                raise LibsshSessionException('SSH config file does not exist')\n"
            "            if libssh.ssh_options_parse_config(self._libssh_session, config_file.encode()) != libssh.SSH_OK:\n"
            "                raise LibsshSessionException('SSH config file could not be parsed')\n"
            "        if libssh.ssh_connect(self._libssh_session) != libssh.SSH_OK:\n",
        ),
    }
    for name, (before, after) in changes.items():
        path = source / name
        text = path.read_text()
        if text.count(before) != 1:
            raise ValueError(f"Pinned SSH binding source changed unexpectedly: {name}")
        path.write_text(text.replace(before, after))


def verify() -> None:
    # Use a fresh interpreter: rebuilding must not leave a previously imported
    # native module in memory, or accidentally validate the build environment.
    subprocess.run([sys.executable, str(ROOT / "tools/check-ssh.py")], check=True, timeout=30)  # noqa: S603 -- Reviewed administrative argv; no shell.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild even if the installed native library matches")
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        raise ValueError("Run with the target virtual environment's Python")
    if not args.force:
        result = subprocess.run([sys.executable, str(ROOT / "tools/check-ssh.py")], capture_output=True, timeout=30)  # noqa: S603 -- Reviewed administrative argv; no shell.
        if result.returncode == 0:
            print(result.stdout.decode().strip())
            return
    if platform.system() not in {"Linux", "Darwin"}:
        raise ValueError("SSH source builds support Linux and macOS")
    for name in ("cmake", "cc", "make"):
        if not shutil.which(name):
            raise ValueError(f"Missing {name}; follow the SSH build prerequisites in README.md")
    pins = json.loads((ROOT / "tools/ssh-sources.json").read_text())
    target = f"{platform.system().lower()}-{platform.machine()}-py{sys.version_info.major}.{sys.version_info.minor}"
    work = ROOT / ".cache/ssh" / target
    work.mkdir(parents=True, exist_ok=True)
    log = work / "build.log"
    log.write_text("")
    sources = {}
    for name, pin in pins.items():
        print(f"Downloading verified {name} {pin['version']} source", flush=True)
        data = download_source(pin["url"])
        sources[name] = extract_source(data, pin["sha256"], work)
    prefix = work / "native"
    cmake = [
        "cmake",
        "-S",
        str(sources["libssh"]),
        "-B",
        str(work / "native-build"),
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DWITH_SERVER=OFF",
        "-DWITH_GSSAPI=OFF",
        "-DWITH_ZLIB=OFF",
        "-DWITH_EXAMPLES=OFF",
        "-DUNIT_TESTING=OFF",
    ]
    crypto_prefix = None
    if platform.system() == "Darwin":
        crypto_prefix = Path(subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True).strip())  # noqa: S607 -- Executable uses the trusted host/container PATH.
        cmake.append(f"-DOPENSSL_ROOT_DIR={crypto_prefix}")
    print("Building libssh without SSH server, GSSAPI or compression support", flush=True)
    run(cmake, log)
    run(["cmake", "--build", str(work / "native-build"), "--parallel", "4"], log)
    run(["cmake", "--install", str(work / "native-build")], log)
    build = work / "build-env"
    run([sys.executable, "-m", "venv", str(build)], log)
    build_python = str(build / "bin/python")
    run([build_python, "-m", "pip", "install", "-r", str(ROOT / "tools/requirements-ssh-build.txt")], log)
    # Statically embed libssh so wheels cannot accidentally load an older
    # system libssh or the upstream wheel's bundled copy. OpenSSL stays managed
    # by the distribution/Homebrew security updates.
    env = {key: value for key, value in os.environ.items() if key not in {"CFLAGS", "CPPFLAGS", "LDFLAGS"}}
    env["CFLAGS"] = f"-I{prefix}/include"
    env["LDFLAGS"] = f"-L{prefix}/lib"
    if crypto_prefix:
        env["CFLAGS"] += f" -I{crypto_prefix}/include"
        env["LDFLAGS"] += f" -L{crypto_prefix}/lib"
    else:
        env["LDFLAGS"] += " -Wl,--no-as-needed"
    env["LDFLAGS"] += " -lssh -lcrypto"
    enable_config_file(sources["ansible-pylibssh"])
    env["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ANSIBLE_PYLIBSSH"] = pins["ansible-pylibssh"]["installed_version"]
    wheels = work / "wheels"
    wheels.mkdir(exist_ok=True)
    print("Building Python SSH bindings against the verified native library", flush=True)
    run(
        [
            build_python,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--no-cache-dir",
            "--wheel-dir",
            str(wheels),
            str(sources["ansible-pylibssh"]),
        ],
        log,
        env,
    )
    candidates = list(wheels.glob(f"ansible_pylibssh-{pins['ansible-pylibssh']['installed_version']}-*.whl"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one SSH wheel; remove stale files in {wheels}")
    run([sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(candidates[0])], log)
    verify()
    print(f"SSH build log: {log}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"SSH installation failed: {error}; see .cache/ssh/<platform>/build.log") from None
