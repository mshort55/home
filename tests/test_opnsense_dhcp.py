"""Validate permanent DHCP declarations and deterministic native model plans."""

import copy
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def planner(load_module):
    return load_module("scripts/plan-opnsense-dhcp.py")


@pytest.fixture
def allocation():
    return yaml.safe_load((ROOT / "inventory.example.yml").read_text())["all"]["vars"]["home_dhcp"]


@pytest.fixture
def settings():
    return {"interface": "opt1", "domain": "lab.home.arpa", "lease_seconds": 3600}


def test_primary_only_and_reserved_printer(planner, allocation, settings):
    result = planner.plan(allocation, settings)
    model = result["model"]
    assert model["port"] == "0" and model["interface"] == "opt1"
    assert model["dhcp"]["enable_ra"] == "0"
    assert model["dhcp"]["lease_max"] == "115"
    assert [(r["start_addr"], r["end_addr"]) for r in model["dhcp_ranges"].values()] == [
        ("10.77.55.20", "10.77.55.115"),
        ("10.77.55.117", "10.77.55.134"),
    ]
    host = next(iter(model["hosts"].values()))
    assert host["ip"] == "10.77.55.116" and host["client_id"] == "*"
    assert {o["option"]: o["value"] for o in model["dhcp_options"].values()} == {
        "3": "10.77.55.254",
        "6": "10.77.55.254",
        "15": "lab.home.arpa",
        "42": "10.77.55.254",
        "119": "lab.home.arpa",
    }


def test_stable_identity_and_no_input_mutation(planner, allocation, settings):
    original = copy.deepcopy(allocation)
    first = planner.plan(allocation, settings)
    assert allocation == original
    allocation["primary_ranges"].reverse()
    assert planner.plan(allocation, settings) == first
    assert first == planner.plan(original, settings)


@pytest.mark.parametrize(
    "field,value",
    [
        ("interface", "wan"),
        ("domain", "bad\nport=53"),
        ("domain", "-bad.test"),
        ("domain", "a..test"),
        ("domain", "a" * 64 + ".test"),
        ("lease_seconds", True),
        ("lease_seconds", 599),
        ("lease_seconds", 86401),
    ],
)
def test_invalid_service_fields(planner, allocation, settings, field, value):
    settings[field] = value
    with pytest.raises(ValueError):
        planner.plan(allocation, settings)


@pytest.mark.parametrize(
    "field,value",
    [("mac", "01:00:00:00:00:01"), ("mac", "00:00:00:00:00:00"), ("name", "bad,name"), ("address", "10.77.55.254")],
)
def test_invalid_reservations(planner, allocation, settings, field, value):
    allocation["reservations"][0][field] = value
    with pytest.raises(ValueError):
        planner.plan(allocation, settings)


def test_conflicting_dynamic_pool_rejected(planner, allocation, settings):
    allocation["primary_ranges"][1]["end"] = "10.77.55.135"
    with pytest.raises(ValueError):
        planner.plan(allocation, settings)


def test_fixture_matches_real_planner(planner):
    fixture = json.loads((ROOT / "tests/fixtures/opnsense-dhcp.json").read_text())
    allocation = {
        "subnet": fixture["subnet"],
        "gateway": fixture["gateway"],
        "primary_ranges": fixture["allocation"]["primary"]["ranges"],
        "standby_ranges": fixture["allocation"]["standby"]["ranges"],
        "reservations": fixture["allocation"]["reservations"],
        "excluded_addresses": [],
        "known_static_addresses": [],
    }
    assert planner.plan(allocation, fixture["settings"]) == fixture


def test_desired_subset_stays_within_primary(planner, allocation, settings):
    settings["ranges"] = [{"start": "10.77.55.20", "end": "10.77.55.109"}]
    result = planner.plan(allocation, settings)
    assert result["allocation"]["primary"]["capacity"] == 90
    assert result["model"]["dhcp"]["lease_max"] == "91"
    settings["ranges"][0]["end"] = "10.77.55.116"
    with pytest.raises(ValueError, match="approved primary"):
        planner.plan(allocation, settings)
