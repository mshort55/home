import hashlib
import os
import subprocess
import sys
import zipfile

import pytest

LOCAL_POPEN = subprocess.Popen


@pytest.fixture
def checks(load_module):
    return load_module("tools/repository_checks.py")


def test_multiline_hashes_preserve_requirement(checks, tmp_path):
    lock = tmp_path / "lock.txt"
    lock.write_text(
        "# generated\n--no-binary ansible-pylibssh\nexample==1.2 \\\n    --hash=sha256:"
        + "a" * 64
        + " \\\n    --hash=sha256:"
        + "b" * 64
        + "\n    # via parent\n"
    )
    assert checks.hashed_requirements(lock) == ["example==1.2"]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# comments only\n",
        "example==1.0\n",
        "example==1.0 --hash=md5:" + "a" * 32,
        "example==1.0 --hash=sha256:bad",
        "example>=1.0 --hash=sha256:" + "a" * 64,
        "example==1.* --hash=sha256:" + "a" * 64,
        "--index-url https://unexpected.example\n",
        "example==1.0 --hash=sha256:" + "a" * 64 + " --trusted-host unexpected.example",
        "example==1.0 --hash=sha256:" + "a" * 64 + "\nother==1.0\n",
        ("example==1.0 --hash=sha256:" + "a" * 64 + "\n") * 2,
    ],
)
def test_incomplete_or_unpinned_lock_rejected(checks, tmp_path, content):
    lock = tmp_path / "lock.txt"
    lock.write_text(content)
    with pytest.raises(ValueError):
        checks.hashed_requirements(lock)


def test_pip_accepts_pinned_wheel_and_rejects_changed_bytes(tmp_path, monkeypatch):
    # Only synthetic local wheels and an isolated target; no package index or
    # repository environments are accessed by this subprocess test.
    monkeypatch.setattr(subprocess, "Popen", LOCAL_POPEN)
    wheel = tmp_path / "hash_fixture-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("hash_fixture/__init__.py", "VALUE = 1\n")
        archive.writestr(
            "hash_fixture-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: hash-fixture\nVersion: 1.0\n"
        )
        archive.writestr(
            "hash_fixture-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("hash_fixture-1.0.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = tmp_path / "lock.txt"
    lock.write_text(f"{wheel.as_uri()} --hash=sha256:{digest}\n")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1")

    def install(target):
        return subprocess.run(  # noqa: S603 -- Synthetic offline wheel installation into a disposable target.
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--no-cache-dir",
                "--require-hashes",
                "--target",
                str(target),
                "-r",
                str(lock),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    result = install(tmp_path / "good")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "good/hash_fixture/__init__.py").is_file()
    with wheel.open("ab") as stream:
        stream.write(b"changed bytes")
    result = install(tmp_path / "bad")
    assert result.returncode != 0 and "DO NOT MATCH THE HASHES" in result.stderr
    assert not (tmp_path / "bad/hash_fixture").exists()
