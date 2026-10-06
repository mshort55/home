import configparser
from pathlib import Path

import pytest


@pytest.fixture
def checks(load_module):
    return load_module("tools/repository_checks.py")


@pytest.fixture
def runner(checks, load_module, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "repository_checks", checks)
    return load_module("tools/validate.py")


@pytest.mark.parametrize(
    "name",
    [
        "inventory.private.yml",
        "secrets/credentials.yml",
        "backups/config.xml",
        ".cache/key.json",
        ".venv-macos/bin/python",
        ".venv-validation/bin/python",
        "client.unf",
        "client.pem",
        ".env",
        ".vault-pass",
        ".ssh/id_ed25519",
    ],
)
def test_private_source_paths_are_rejected(checks, name):
    assert checks.private_path(Path(name))


@pytest.mark.parametrize(
    "name",
    [
        "inventory.example.yml",
        ".env.example",
        "files/opnsense/26.7.pub",
        "files/ubuntu-cloud-image-signing-key.asc",
        "tests/test_wireguard_keys.py",
    ],
)
def test_public_examples_signing_keys_and_tests_are_allowed(checks, name):
    assert not checks.private_path(Path(name))


def test_duplicate_yaml_keys_are_not_silently_discarded(checks, tmp_path):
    fixture = tmp_path / "duplicate.yml"
    fixture.write_text("all:\n  hosts: {}\n  hosts: {other: {}}\n")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        checks.load_yaml(fixture)


def test_operator_overrides_cannot_redirect_validation(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("ANSIBLE_CONFIG", "/private/operator-config")
    monkeypatch.setenv("ANSIBLE_INVENTORY", "/private/inventory")
    monkeypatch.setenv("ANSIBLE_VAULT_PASSWORD_FILE", "/private/password")
    monkeypatch.setenv("ANSIBLE_CALLBACK_PLUGINS", "/private/callbacks")
    monkeypatch.setenv("GITLEAKS_CONFIG", "/private/disabled-rules")
    monkeypatch.setenv("HADOLINT_NOFAIL", "1")
    monkeypatch.setenv("HADOLINT_IGNORE", "DL3008")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--no-cov")
    monkeypatch.setenv("COVERAGE_RCFILE", "/private/disabled-coverage")
    monkeypatch.setenv("RUFF_OUTPUT_FORMAT", "json")
    env = runner.validation_environment(tmp_path)
    assert "ANSIBLE_INVENTORY" not in env and "ANSIBLE_VAULT_PASSWORD_FILE" not in env
    assert "ANSIBLE_CALLBACK_PLUGINS" not in env and "GITLEAKS_CONFIG" not in env
    assert not any(
        name in env
        for name in ("HADOLINT_NOFAIL", "HADOLINT_IGNORE", "PYTEST_ADDOPTS", "COVERAGE_RCFILE", "RUFF_OUTPUT_FORMAT")
    )
    config = configparser.ConfigParser()
    config.read(env["ANSIBLE_CONFIG"])
    assert config["defaults"]["inventory"].endswith("/inventory.example.yml")
    assert config.getboolean("defaults", "ask_vault_pass") is False
    assert Path(env["HOME_VALIDATION_VAULT"]).read_text() == "vault_devices: {}\n"


@pytest.mark.parametrize("name", ["secrets/credentials.yml", "inventory.private.yml", "../outside", "/absolute/source"])
def test_secret_scanner_refuses_unsafe_input_before_copy(runner, tmp_path, name):
    with pytest.raises(ValueError, match="Refusing to scan"):
        runner.secret_checks([Path(name)], {}, tmp_path)
    assert not (tmp_path / "public-source").exists()


def test_safe_yaml_loader_rejects_python_object_constructors(checks, tmp_path):
    import yaml

    fixture = tmp_path / "object.yml"
    fixture.write_text("value: !!python/object/apply:builtins.eval ['1 + 1']\n")
    with pytest.raises(yaml.constructor.ConstructorError):
        checks.load_yaml(fixture)


def test_root_nested_and_variant_dockerfiles_are_discovered(checks):
    paths = [
        Path(name) for name in ["Dockerfile", "deep/nested/Dockerfile", "Dockerfile.test", "build/tool.Dockerfile"]
    ]
    assert checks.dockerfiles([*paths, Path("README.md")]) == sorted(paths)


@pytest.mark.parametrize("image", ["debian:trixie-slim", "debian:latest", "${BASE}", "debian@sha256:bad"])
def test_mutable_or_invalid_container_base_is_rejected(checks, tmp_path, image):
    path = tmp_path / "Dockerfile"
    path.write_text(f"FROM {image}\n")
    assert checks.container_errors(tmp_path, [Path(path.name)])


def test_pinned_multistage_and_scratch_images_are_allowed(checks, tmp_path):
    path = tmp_path / "Dockerfile"
    path.write_text(
        f"FROM --platform=linux/amd64 debian@sha256:{'a' * 64} AS builder\nFROM builder AS runtime\nFROM scratch\n"
    )
    assert checks.container_errors(tmp_path, [Path(path.name)]) == []


def test_container_validation_does_not_read_private_symlink_or_deleted_files(checks, tmp_path):
    private = tmp_path / "private/Dockerfile"
    private.parent.mkdir()
    private.write_bytes(b"\xff")  # Reading this as source would fail decoding.
    linked = tmp_path / "Dockerfile.linked"
    linked.symlink_to(private)
    assert checks.container_errors(tmp_path, [Path("private/Dockerfile"), Path(linked.name), Path("Dockerfile")]) == []


@pytest.fixture
def coverage_fixture(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.home_validation.coverage]\nfocused_fail_under = 85\n"
        '[tool.home_validation.coverage.minimum_per_file]\n"scripts/critical.py" = 80\n'
    )
    report = {
        "files": {
            "scripts/critical.py": {
                "summary": {
                    "percent_covered": 90,
                    "covered_lines": 90,
                    "covered_branches": 0,
                    "num_statements": 100,
                    "num_branches": 0,
                }
            }
        }
    }
    return report, [Path("scripts/critical.py")]


def test_unmeasured_production_code_cannot_disappear_from_coverage(runner, coverage_fixture):
    report, files = coverage_fixture
    with pytest.raises(ValueError, match="missing from coverage report"):
        runner.coverage_checks(report, [*files, Path("scripts/untested.py")])


def test_deleted_critical_file_cannot_remove_its_coverage_gate(runner, coverage_fixture):
    report, _ = coverage_fixture
    report["files"] = {}
    with pytest.raises(ValueError, match="Critical coverage file is missing"):
        runner.coverage_checks(report, [])


def test_individual_critical_file_floor_is_enforced(runner, coverage_fixture):
    report, files = coverage_fixture
    report["files"][files[0].as_posix()]["summary"].update(percent_covered=79, covered_lines=79)
    with pytest.raises(ValueError, match="requires 80%"):
        runner.coverage_checks(report, files)


def test_focused_floor_counts_branch_edges_as_well_as_lines(runner, coverage_fixture):
    report, files = coverage_fixture
    report["files"][files[0].as_posix()]["summary"].update(num_branches=100, covered_branches=78, percent_covered=84)
    with pytest.raises(ValueError, match=r"Focused coverage is 84\.00%"):
        runner.coverage_checks(report, files)


def test_test_files_do_not_inflate_production_coverage(runner, coverage_fixture):
    report, files = coverage_fixture
    runner.coverage_checks(report, [*files, Path("tests/test_example.py")])
