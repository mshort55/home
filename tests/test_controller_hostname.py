"""Controller hostname recovery must preserve trusted identities and unrelated entries."""

import socket

import pytest


@pytest.fixture
def planner(load_module, monkeypatch):
    module = load_module("scripts/controller-hostname.py")

    def missing(*args):
        raise socket.gaierror(socket.EAI_NONAME, "not found")

    monkeypatch.setattr(module.socket, "getaddrinfo", missing)
    return module


def answers(planner, monkeypatch, addresses):
    monkeypatch.setattr(
        planner.socket,
        "getaddrinfo",
        lambda *args: [(socket.AF_INET, 0, 0, "", (address, 0)) for address in addresses],
    )


def test_fresh_controller_plans_only_the_missing_mapping(planner):
    hosts = "127.0.0.1 localhost\n192.0.2.99 other.example.test # device.example.test\n"
    assert planner.inspect("device.example.test", "192.0.2.10", hosts) == {"needs_change": True, "addresses": []}


@pytest.mark.parametrize("hosts", ["", "192.0.2.10 DEVICE.example.test # reviewed\n"])
def test_matching_dns_or_existing_mapping_needs_no_sudo(planner, monkeypatch, hosts):
    answers(planner, monkeypatch, ["192.0.2.10", "192.0.2.10"])
    assert planner.inspect("device.example.test", "192.0.2.10", hosts, verify=True)["needs_change"] is False


@pytest.mark.parametrize(
    "hosts",
    [
        "192.0.2.11 device.example.test\n",
        "192.0.2.10 device.example.test alias\n",
        "192.0.2.10 alias DEVICE.example.test\n",
        "192.0.2.10 device.example.test\n192.0.2.10 DEVICE.example.test\n",
    ],
)
def test_conflicting_shared_or_duplicate_hosts_entries_are_refused(planner, hosts):
    with pytest.raises(ValueError, match="Duplicate, shared-alias or conflicting"):
        planner.inspect("device.example.test", "192.0.2.10", hosts)


@pytest.mark.parametrize("addresses", [["192.0.2.11"], ["192.0.2.10", "192.0.2.11"]])
def test_conflicting_dns_is_not_overridden(planner, monkeypatch, addresses):
    answers(planner, monkeypatch, addresses)
    with pytest.raises(ValueError, match="resolves to"):
        planner.inspect("device.example.test", "192.0.2.10", "")


def test_existing_but_ineffective_mapping_is_not_duplicated(planner):
    with pytest.raises(ValueError, match="does not resolve"):
        planner.inspect("device.example.test", "192.0.2.10", "192.0.2.10 device.example.test\n")


def test_post_write_verification_requires_actual_resolution(planner):
    with pytest.raises(ValueError, match="does not resolve"):
        planner.inspect("device.example.test", "192.0.2.10", "", verify=True)


@pytest.mark.parametrize(
    "hostname,address",
    [
        ("device.example.test\ninjected", "192.0.2.10"),
        ("*.example.test", "192.0.2.10"),
        ("device.example.test", "127.0.0.1"),
        ("device.example.test", "0.0.0.0"),  # noqa: S104 -- Invalid endpoint fixture, no listener.
        ("device.example.test", "224.0.0.1"),
        ("device.example.test", "192.0.2.999"),
    ],
)
def test_invalid_endpoint_is_rejected_before_resolution(planner, hostname, address):
    with pytest.raises(ValueError):
        planner.inspect(hostname, address, "")


def test_temporary_dns_failure_can_use_the_reviewed_static_mapping(planner, monkeypatch):
    def unavailable(*args):
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    monkeypatch.setattr(planner.socket, "getaddrinfo", unavailable)
    assert planner.inspect("device.example.test", "192.0.2.10", "")["needs_change"] is True


def test_unexpected_resolver_failure_is_not_hidden(planner, monkeypatch):
    def broken(*args):
        raise socket.gaierror(socket.EAI_FAIL, "resolver failure")

    monkeypatch.setattr(planner.socket, "getaddrinfo", broken)
    with pytest.raises(socket.gaierror):
        planner.inspect("device.example.test", "192.0.2.10", "")
