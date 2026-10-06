"""Offline repository contracts, source parsing, documentation and privacy checks."""

from __future__ import annotations

import ast
import configparser
import re
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parent.parent


def source_files(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return sorted({Path(name.decode()) for name in result.stdout.split(b"\0") if name})


def private_path(path: Path) -> bool:
    private_dirs = {"secrets", "backups", "private", "rendered", ".cache", ".collections", ".ssh", "node_modules"}
    return (
        any(part in private_dirs or part.startswith(".venv") for part in path.parts)
        or ".private." in path.name
        or path.name.startswith((".env", ".vault-pass", "vault_password"))
        and path.name != ".env.example"
        or path.suffix in {".unf", ".key", ".pem", ".p12", ".pfx"}
        or path.name in {"vault.yml", "vault.yaml"}
    )


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently dropping their values."""


def unique_mapping(loader: UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    keys = [key.value for key, _ in node.value]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate YAML key at line {node.start_mark.line + 1}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path: Path):
    return yaml.load(path.read_text(), Loader=UniqueLoader)


def walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def role_actions(root: Path = ROOT) -> dict[str, list[str]]:
    result = {}
    for role in sorted(path for path in (root / "roles").iterdir() if path.is_dir() and not path.name.startswith(".")):
        specs = load_yaml(role / "meta/argument_specs.yml")["argument_specs"]
        options = specs["main"]["options"][f"{role.name}_options"]
        action = options["options"]["task_action"]
        if not options.get("required") or not action.get("required") or "default" in action or "default" in options:
            raise ValueError(f"{role.name}: action must be explicitly required without a default")
        choices = action["choices"]
        public = {p.stem for p in (role / "tasks").glob("*.yml") if p.stem != "main" and not p.stem.startswith("_")}
        if set(choices) != public or len(choices) != len(set(choices)):
            raise ValueError(f"{role.name}: action choices and public task files differ")
        defaults = load_yaml(role / "defaults/main.yml") or {}
        if f"{role.name}_options" in defaults:
            raise ValueError(f"{role.name}: action dictionary must not be defaulted")
        for spec in specs.values():
            for key, field in spec.get("options", {}).items():
                if "default" in field and key in defaults and field["default"] != defaults[key]:
                    raise ValueError(f"{role.name}: argument/default mismatch for {key}")
        result[role.name] = choices
    return result


def documentation_tables(root: Path = ROOT) -> dict[tuple[str, str], str]:
    actions = role_actions(root)
    entries = ["| Entry point | Inventory group | Role | Action |", "|---|---|---|---|"]
    for path in sorted((root / "playbooks").glob("*.yml")):
        for play in load_yaml(path):
            for item in play["roles"]:
                role = item if isinstance(item, str) else item["role"]
                action = None if isinstance(item, str) else item.get(f"{role}_options", {}).get("task_action")
                if role not in actions or action is not None and action not in actions[role]:
                    raise ValueError(f"{path.name}: unknown role or action")
                selected = f"`{action}`" if action else "Required explicit `task_action`"
                entries.append(
                    f"| [{path.name}](../../playbooks/{path.name}) | `{play['hosts']}` | "
                    f"[{role}](../../roles/{role}/tasks/main.yml) | {selected} |"
                )
    contracts = ["| Role | Public actions | Optional defaults | Argument contracts |", "|---|---|---|---|"]
    choices = ["| Parameter dictionary | Allowed `task_action` values |", "|---|---|"]
    for role, public in actions.items():
        names = ", ".join(f"`{name}`" for name in public)
        contracts.append(
            f"| [{role}](../roles/{role}/tasks/main.yml) | {names} | "
            f"[defaults](../roles/{role}/defaults/main.yml) | [schema](../roles/{role}/meta/argument_specs.yml) |"
        )
        choices.append(f"| `{role}_options` | {names} |")
    return {
        ("docs/roles.md", "Roles and contracts"): "\n".join(contracts),
        ("docs/playbooks/entry-points.md", "Entry-point mapping"): "\n".join(entries),
        ("docs/playbooks/entry-points.md", "Role action choices"): "\n".join(choices),
    }


def table_region(text: str, heading: str) -> tuple[int, int]:
    start = text.index("\n|", text.index(f"## {heading}\n")) + 1
    end = text.index("\n\n", start)
    return start, end


def refresh_documentation(root: Path = ROOT) -> None:
    for (name, heading), table in documentation_tables(root).items():
        path = root / name
        text = path.read_text()
        start, end = table_region(text, heading)
        path.write_text(text[:start] + table + text[end:])


def check_repository(root: Path = ROOT) -> list[str]:
    errors = []
    files = source_files(root)
    environment = Environment()
    for relative in files:
        path = root / relative
        if private_path(relative):
            errors.append(f"forbidden source artifact: {relative}")
            continue
        if not path.exists():
            continue  # A tracked deletion is allowed.
        if path.is_symlink():
            errors.append(f"source symlink requires explicit handling: {relative}")
            continue
        if path.suffix not in {".py", ".yml", ".yaml", ".j2", ".md", ".sh", ".php", ".toml", ".in", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if not text.endswith("\n") or "\r" in text or any(line.rstrip() != line for line in text.splitlines()):
                errors.append(f"whitespace/newline violation: {relative}")
            if re.search(r"^(?:<{7}|={7}|>{7})(?: |$)", text, flags=re.MULTILINE):
                errors.append(f"merge conflict marker: {relative}")
            if path.suffix == ".py":
                ast.parse(text, filename=str(relative))
            if path.suffix == ".j2":
                environment.parse(text)
            if path.suffix in {".yml", ".yaml"}:
                data = load_yaml(path)
                for value in walk_strings(data):
                    if "\n" in value and re.match(r"(?:from \S+ import |import )", value):
                        ast.parse(value, filename=f"{relative}: inline Python")
            if path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", text):
                    target = target.split("#")[0]
                    if target and ":" not in target and not (path.parent / target).exists():
                        errors.append(f"missing local documentation link: {relative}: {target}")
        except (ValueError, SyntaxError, yaml.YAMLError) as error:
            errors.append(f"invalid source {relative}: {error}")
    try:
        for (name, heading), expected in documentation_tables(root).items():
            text = (root / name).read_text()
            start, end = table_region(text, heading)
            if set(text[start:end].splitlines()) != set(expected.splitlines()):
                errors.append(f"outdated documentation table: {name}: {heading}; run tools/update-validation-docs.py")
    except (KeyError, ValueError, FileNotFoundError) as error:
        errors.append(f"role/entry-point contract: {error}")
    ignored = [
        ".venv-macos/bin/python",
        ".venv-validation/bin/python",
        "inventory.private.yml",
        "secrets/credentials.yml",
        "backups/example/config.xml",
        ".cache/example.json",
        "reports/junit.xml",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=root,
        input="\n".join(ignored) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    errors.extend(
        f"private/generated path is not ignored: {name}" for name in set(ignored) - set(result.stdout.splitlines())
    )
    config = configparser.ConfigParser()
    config.read(root / "ansible.cfg")
    for section, key, expected in [
        ("defaults", "host_key_checking", True),
        ("defaults", "private_role_vars", True),
        ("defaults", "display_args_to_stdout", False),
        ("persistent_connection", "log_messages", False),
        ("paramiko_connection", "host_key_auto_add", False),
    ]:
        if config.getboolean(section, key) != expected:
            errors.append(f"Ansible trust/privacy configuration changed: {section}.{key}")
    return errors
