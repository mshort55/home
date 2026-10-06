#!/usr/bin/env python3
"""Run offline validation; optionally audit online vulnerability data and Git history."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from repository_checks import ROOT, check_repository, private_path, source_files

CHECKS = ["repository", "python", "yaml", "ansible", "shell", "php", "containers", "secrets", "tests", "dependencies"]


def command(arguments: list[str], env: dict[str, str], *, timeout: int = 600) -> None:
    subprocess.run(arguments, cwd=ROOT, env=env, check=True, timeout=timeout)


def binary(name: str) -> str:
    if name in {"gitleaks", "hadolint"}:
        candidate = ROOT / ".cache/validation/bin" / name
    else:
        candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    installed = shutil.which(name)
    if installed:
        return installed
    raise ValueError(f"Missing {name}; follow docs/validation.md setup instructions")


def validation_environment(directory: Path) -> dict[str, str]:
    # Operator inventory, Vault sources, callback plugins and connection overrides
    # must never affect a validation run. Keep the infrastructure config unchanged.
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ANSIBLE_", "GITLEAKS_"))}
    fixture = directory / "credentials.yml"
    fixture.write_text("vault_devices: {}\n")
    config = configparser.ConfigParser()
    config.read(ROOT / "ansible.cfg")
    config["defaults"].update(
        {
            "ask_vault_pass": "False",
            "inventory": str(ROOT / "inventory.example.yml"),
            "collections_path": str(ROOT / ".collections"),
            "roles_path": str(ROOT / "roles"),
            "action_plugins": str(ROOT / "plugins/action"),
            "local_tmp": str(directory / "ansible-tmp"),
        }
    )
    path = directory / "ansible.cfg"
    with path.open("w") as stream:
        config.write(stream)
    env.update(
        ANSIBLE_CONFIG=str(path),
        ANSIBLE_NOCOLOR="1",
        HOME_VALIDATION_VAULT=str(fixture),
        PYTHONDONTWRITEBYTECODE="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def ansible_checks(env: dict[str, str], directory: Path) -> None:
    # Lint every task file, including dynamic actions. Additionally import all
    # task files in their own role context so end_role and relative includes stay
    # valid while Ansible resolves their real modules without executing anything.
    command([binary("ansible-lint"), "--offline", "playbooks", "roles"], env)
    harness = [
        {
            "name": "Validate every role task without execution",
            "hosts": "all",
            "gather_facts": False,
            "tasks": [
                {
                    "name": f"Parse {path.relative_to(ROOT)}",
                    "ansible.builtin.import_role": {
                        "name": path.parents[1].name,
                        "tasks_from": path.stem,
                        "rolespec_validate": False,
                    },
                }
                for path in sorted((ROOT / "roles").glob("*/tasks/*.yml"))
            ],
        }
    ]
    play = directory / "all-role-tasks.yml"
    play.write_text(yaml.safe_dump(harness, sort_keys=False))
    command([binary("ansible-playbook"), "--syntax-check", str(play)], env)
    print(f"Validated {len(list((ROOT / 'playbooks').glob('*.yml')))} entry points and all role task files", flush=True)


def secret_checks(files: list[Path], env: dict[str, str], directory: Path) -> None:
    # Scan only Git-visible source copies. Never recursively scan this working
    # directory: ignored private inventory/backups/keys live beside the code.
    public = directory / "public-source"
    for relative in files:
        source = ROOT / relative
        if relative.is_absolute() or ".." in relative.parts or private_path(relative) or source.is_symlink():
            raise ValueError(f"Refusing to scan private or unsafe source path: {relative}")
        if source.is_file():
            target = public / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    command([binary("gitleaks"), "dir", str(public), "--redact", "--no-banner"], env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checks", nargs="+", choices=CHECKS, help="Run selected checks (repository checks always run)"
    )
    parser.add_argument("--quick", action="store_true", help="Fast offline pre-commit checks; omits Ansible and tests")
    parser.add_argument(
        "--audit", action="store_true", help="Also audit locked dependencies online and all Git history"
    )
    args = parser.parse_args()
    selected = args.checks or ([name for name in CHECKS if name not in {"ansible", "tests"}] if args.quick else CHECKS)
    errors = check_repository()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    files = [path for path in source_files() if (ROOT / path).is_file()]
    with tempfile.TemporaryDirectory(prefix="home-validation-") as name:
        directory = Path(name)
        env = validation_environment(directory)
        for check in selected:
            print(f"\nChecking {check}...", flush=True)
            if check == "python":
                command([binary("ruff"), "check", "scripts", "plugins", "tools", "tests"], env)
                command(
                    [
                        binary("ruff"),
                        "check",
                        "--isolated",
                        "--select",
                        "E4,E7,E9,F",
                        "--ignore",
                        "F541",
                        "scripts/prepare-opnsense-bootstrap.py",
                    ],
                    env,
                )
                command([binary("ruff"), "format", "--check", "scripts", "plugins", "tools", "tests"], env)
            elif check == "yaml":
                paths = [str(path) for path in files if path.suffix in {".yml", ".yaml"}]
                command([binary("yamllint"), "-s", ".ansible-lint", *paths], env)
            elif check == "ansible":
                ansible_checks(env, directory)
            elif check == "shell":
                command(["sh", "-n", "scripts/opnsense-install.sh"], env)
                command([binary("shellcheck"), "scripts/opnsense-install.sh"], env)
            elif check == "php":
                for path in sorted((ROOT / "scripts").glob("*.php")):
                    command([binary("php"), "-l", str(path)], env)
                import ast

                tree = ast.parse((ROOT / "scripts/prepare-opnsense-bootstrap.py").read_text())
                for node in tree.body:
                    if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "INSPECT" for t in node.targets
                    ):
                        fixture = directory / "bootstrap-inspect.php"
                        fixture.write_text(ast.literal_eval(node.value))
                        command([binary("php"), "-l", str(fixture)], env)
            elif check == "containers":
                command([binary("hadolint"), *map(str, sorted((ROOT / "containers").glob("*/Dockerfile")))], env)
            elif check == "secrets":
                secret_checks(files, env, directory)
            elif check == "tests":
                command([sys.executable, "-m", "pytest", "--cov", "--cov-report=term-missing"], env)
            elif check == "dependencies":
                command([sys.executable, "-m", "pip", "check"], env)
                command([sys.executable, "tools/check-ssh.py"], env)
                from importlib.metadata import version

                from packaging.requirements import Requirement

                for filename in ["requirements.txt", "requirements-dev.txt"]:
                    locked = {}
                    for line in (ROOT / filename).read_text().splitlines():
                        if not line.strip() or line.lstrip().startswith(("#", "--")):
                            continue
                        pin = Requirement(line.strip())
                        locked[pin.name.lower().replace("_", "-")] = version(pin.name)
                        if version(pin.name) not in pin.specifier:
                            raise ValueError(f"Installed dependency differs from {filename}: {pin.name}")
                    inputs = "requirements.in" if filename == "requirements.txt" else "requirements-dev.in"
                    for line in (ROOT / inputs).read_text().splitlines():
                        if not line.strip() or line.lstrip().startswith(("#", "-")):
                            continue
                        direct = Requirement(line.strip())
                        resolved = locked.get(direct.name.lower().replace("_", "-"))
                        if resolved is None or resolved not in direct.specifier:
                            raise ValueError(f"Direct dependency differs from {filename}: {direct.name}")
                for name, pin in json.loads((ROOT / "tools/native-tools.json").read_text()).items():
                    result = subprocess.run(
                        [binary(name), "version" if name == "gitleaks" else "--version"],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=15,
                    )
                    if pin["version"] not in result.stdout.split():
                        raise ValueError(f"Installed native tool differs from its pin: {name}; rerun the installer")
                for pin in yaml.safe_load((ROOT / "collections/requirements.yml").read_text())["collections"]:
                    namespace, collection = pin["name"].split(".")
                    manifest = ROOT / ".collections/ansible_collections" / namespace / collection / "MANIFEST.json"
                    if json.loads(manifest.read_text())["collection_info"]["version"] != pin["version"]:
                        raise ValueError(f"Installed collection version differs: {pin['name']}")
        if args.audit:
            command([sys.executable, "tools/check-ssh.py"], env)
            # Run every audit even when one reports a finding; do not hide existing vulnerabilities.
            failures = []
            for filename in ["requirements.txt", "requirements-dev.txt", "tools/requirements-ssh-build.txt"]:
                try:
                    command([binary("pip-audit"), "--no-deps", "--disable-pip", "-r", filename], env)
                except subprocess.CalledProcessError:
                    failures.append(filename)
            try:
                command([binary("gitleaks"), "git", str(ROOT), "--redact", "--no-banner", "--log-opts=--all"], env)
            except subprocess.CalledProcessError:
                failures.append("Git history")
            if failures:
                raise ValueError("Security audit failed: " + ", ".join(failures))
    print("\nValidation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
