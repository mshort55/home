"""Permanent pool safety without network or device writes."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "home_dhcp", Path(__file__).resolve().parents[1] / "scripts/validate-home-dhcp.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def config():
    return {
        "subnet": "192.0.2.0/24",
        "gateway": "192.0.2.254",
        "primary_ranges": [
            {"start": "192.0.2.20", "end": "192.0.2.115"},
            {"start": "192.0.2.117", "end": "192.0.2.134"},
        ],
        "standby_ranges": [{"start": "192.0.2.135", "end": "192.0.2.248"}],
        "reservations": [{"name": "printer", "address": "192.0.2.116", "mac": "02:00:00:00:00:01"}],
        "excluded_addresses": ["192.0.2.249", "192.0.2.250", "192.0.2.251", "192.0.2.252"],
        "known_static_addresses": ["192.0.2.250", "192.0.2.251"],
    }


def test_equal_pools(config):
    result = MODULE.validate(config)
    assert result["primary"]["capacity"] == result["standby"]["capacity"] == 114
    assert result["status"] == "valid"
    assert "legacy_max_lease_seconds" not in result


@pytest.mark.parametrize(
    "field,value",
    [
        ("known_static_addresses", ["192.0.2.21"]),
        ("gateway", "192.0.2.20"),
        ("standby_ranges", [{"start": "192.0.2.134", "end": "192.0.2.247"}]),
        (
            "primary_ranges",
            [{"start": "192.0.2.20", "end": "192.0.2.116"}, {"start": "192.0.2.118", "end": "192.0.2.134"}],
        ),
    ],
)
def test_invalid_or_conflicting_allocations_fail(config, field, value):
    config[field] = value
    with pytest.raises(ValueError):
        MODULE.validate(config)


def test_output_is_private_and_replaces_atomically(tmp_path, config):
    path = tmp_path / "private" / "plan.json"
    result = MODULE.validate(config)
    MODULE.write_private(path, result)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    first = path.read_bytes()
    MODULE.write_private(path, result)
    assert path.read_bytes() == first


def test_output_does_not_follow_symlinks(tmp_path):
    target = tmp_path / "inventory.yml"
    target.write_text("untouched")
    link = tmp_path / "plan.json"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        MODULE.write_private(link, {})
    assert target.read_text() == "untouched"
