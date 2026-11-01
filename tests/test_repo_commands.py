"""Exercise command routing with synthetic executables; never invoke live Ansible."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_POPEN = subprocess.Popen


@pytest.mark.parametrize("system,environment", [("Linux", ".venv"), ("Darwin", ".venv-macos")])
def test_playbook_runner_preserves_arguments(load_module, tmp_path, monkeypatch, system, environment):
    runner = load_module("tools/run-playbook.py")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.platform, "system", lambda: system)
    executable = tmp_path / environment / "bin/ansible-playbook"
    executable.parent.mkdir(parents=True)
    executable.touch()
    args = ["playbooks/test.yml", "--extra-vars", "value=with spaces; $(not-a-command)"]
    monkeypatch.setattr(runner.sys, "argv", ["runner", *args])
    monkeypatch.setattr(runner.os, "chdir", lambda path: None)
    calls = []
    monkeypatch.setattr(runner.os, "execv", lambda path, argv: calls.append((path, argv)))
    runner.main()
    assert calls == [(str(executable), [str(executable), *args])]


def test_playbook_runner_requires_setup(load_module, tmp_path, monkeypatch):
    runner = load_module("tools/run-playbook.py")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match=r"setup\.py"):
        runner.main()


@pytest.fixture
def just_stub(tmp_path, monkeypatch):
    # Restore subprocess only for the pinned local runner and a fake Python.
    # Recipes cannot invoke actual setup, validation, or infrastructure code.
    monkeypatch.setattr(subprocess, "Popen", LOCAL_POPEN)
    stub = tmp_path / "python3"
    stub.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    stub.chmod(0o700)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"])

    def run(*args):
        result = subprocess.run(  # noqa: S603 -- Local pinned runner with fake Python, no device operations.
            [str(ROOT / "just"), *args],
            env=env,
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        )
        return result.stdout

    return run


@pytest.mark.parametrize(
    "recipe,base",
    [
        ("validate", ["tools/run-validation.py"]),
        ("playbook", ["tools/run-playbook.py"]),
    ],
)
def test_recipes_forward_literal_arguments(just_stub, recipe, base):
    args = ["--extra-vars", "value=with spaces; $(false)", "*", "pve01,unifi01"]
    assert json.loads(just_stub(recipe, *args)) == [*base, *args]


def test_default_only_lists_commands(just_stub):
    output = just_stub()
    assert "Available recipes:" in output and "playbook" in output
    assert "tools/setup.py" not in output
