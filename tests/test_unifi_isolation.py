import json
import subprocess

import pytest


@pytest.fixture
def isolation(load_module):
    return load_module("scripts/unifi-isolation.py")


@pytest.fixture
def settings():
    return {
        "hostname": "unifi01",
        "gateway": "10.77.10.254",
        "tunnel_address": "10.77.99.2",
        "recovery_address": "10.77.10.250",
    }


def verdict(
    isolation,
    settings,
    chain,
    destination=None,
    source=None,
    protocol="tcp",
    port=443,
    state="new",
    direction="original",
    interface="eth0",
    family="ipv4",
):
    """Evaluate the generated subset of nft expressions against independent policy cases."""
    import ipaddress

    for item in isolation.rules(settings):
        rule = item.get("rule", {})
        if rule.get("chain") != chain:
            continue
        matches = True
        for expression in rule["expr"]:
            if "match" not in expression:
                if matches:
                    return next(iter(expression))
                break
            match = expression["match"]
            left, right = match["left"], match["right"]
            if "meta" in left:
                actual = {"iifname": interface, "oifname": interface, "nfproto": family, "l4proto": protocol}[
                    left["meta"]["key"]
                ]
            elif "ct" in left:
                actual = {"state": state, "direction": direction}[left["ct"]["key"]]
            else:
                payload = left["payload"]
                if payload["protocol"] not in ["ip", protocol]:
                    matches = False
                    continue
                actual = {"daddr": destination, "saddr": source, "dport": port}[payload["field"]]
            if isinstance(right, dict) and "set" in right:
                matches &= actual in right["set"]
            elif isinstance(right, dict) and "prefix" in right:
                prefix = right["prefix"]
                matches &= actual is not None and ipaddress.ip_address(actual) in ipaddress.ip_network(
                    f"{prefix['addr']}/{prefix['len']}"
                )
            else:
                matches &= actual == right
    return "drop"


@pytest.mark.parametrize(
    "chain,traffic,expected",
    [
        ("input", {"source": "10.77.99.2", "port": 22}, "accept"),
        ("input", {"source": "10.77.10.250", "port": 22}, "accept"),
        ("input", {"source": "10.77.99.2", "port": 11443}, "accept"),
        ("input", {"source": "10.77.10.250", "port": 11443}, "drop"),
        ("input", {"source": "10.77.10.31", "port": 8080}, "drop"),
        ("input", {"source": "10.77.99.2", "port": 8080}, "drop"),
        ("output", {"destination": "10.77.10.254", "protocol": "udp", "port": 53}, "accept"),
        ("output", {"destination": "10.77.10.254", "protocol": "udp", "port": 123}, "accept"),
        ("output", {"destination": "10.77.10.254", "port": 53}, "accept"),
        ("output", {"destination": "10.77.10.254", "port": 443}, "drop"),
        ("output", {"destination": "10.77.10.10", "port": 22}, "drop"),
        ("output", {"destination": "10.77.40.10", "port": 443}, "drop"),
        ("output", {"destination": "192.168.1.31", "port": 443}, "drop"),
        ("output", {"destination": "100.64.0.1", "port": 443}, "drop"),
        ("output", {"destination": "1.1.1.1", "port": 443}, "accept"),
        ("output", {"destination": "1.1.1.1", "port": 80}, "accept"),
        ("output", {"destination": "1.1.1.1", "port": 22}, "drop"),
        ("output", {"destination": "10.77.10.10", "state": "established"}, "drop"),
        ("output", {"destination": "10.77.99.2", "state": "established", "direction": "reply"}, "accept"),
        ("output", {"destination": "10.77.99.2", "state": "established"}, "drop"),
        ("output", {"family": "ipv6", "state": "established"}, "drop"),
        ("forward", {"destination": "1.1.1.1"}, "drop"),
    ],
)
def test_policy_acceptance(isolation, settings, chain, traffic, expected):
    assert verdict(isolation, settings, chain, **traffic) == expected


def test_plan_and_verify_never_write(isolation, settings, monkeypatch):
    monkeypatch.setattr(isolation, "current", lambda: [])
    assert isolation.apply(settings, "plan") == {"changed": True, "isolated": False}
    with pytest.raises(ValueError, match="restore is blocked"):
        isolation.apply(settings, "verify")
    monkeypatch.setattr(isolation, "current", lambda: isolation.rules(settings))
    assert isolation.apply(settings, "verify") == {"changed": False, "isolated": True}
    assert isolation.apply(settings, "apply")["changed"] is False


@pytest.mark.parametrize("existing", [False, True])
def test_apply_checks_then_replaces_only_owned_table(isolation, settings, monkeypatch, existing):
    expected = isolation.rules(settings)
    observations = iter([[{"table": {"family": "inet", "name": isolation.TABLE}}] if existing else [], expected])
    monkeypatch.setattr(isolation, "current", lambda: next(observations))
    calls = []
    monkeypatch.setattr(isolation, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert isolation.apply(settings, "apply") == {"changed": True, "isolated": True}
    assert "--check" in calls[0][0] and "--check" not in calls[1][0]
    commands = json.loads(calls[1][1]["content"])["nftables"]
    if existing:
        assert commands[0] == {"delete": {"table": {"family": "inet", "name": "home_unifi"}}}
    assert all("flush" not in item for item in commands)
    assert calls[0][1]["content"] == calls[1][1]["content"]


def test_failed_check_does_not_apply(isolation, settings, monkeypatch):
    monkeypatch.setattr(isolation, "current", lambda: [])
    calls = []

    def reject(*args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(isolation, "run", reject)
    with pytest.raises(subprocess.CalledProcessError):
        isolation.apply(settings, "apply")
    assert len(calls) == 1 and "--check" in calls[0]


def test_failed_readback_does_not_claim_isolated(isolation, settings, monkeypatch):
    monkeypatch.setattr(isolation, "current", lambda: [])
    monkeypatch.setattr(isolation, "run", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="does not match"):
        isolation.apply(settings, "apply")


def test_normalization_preserves_rule_order(isolation):
    objects = [
        {"metainfo": {}},
        {"rule": {"chain": "output", "handle": 123, "expr": [{"drop": None}]}},
        {"table": {"name": "home_unifi", "handle": 1}},
        {"rule": {"chain": "output", "expr": [{"accept": None}]}},
    ]
    normalized = isolation.normalized(objects)
    assert normalized == [
        {"table": {"name": "home_unifi"}},
        {"rule": {"chain": "output", "expr": [{"drop": None}]}},
        {"rule": {"chain": "output", "expr": [{"accept": None}]}},
    ]


def test_current_reads_only_owned_table(isolation, monkeypatch):
    from types import SimpleNamespace

    calls = []

    def read(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({"nftables": [{"table": {"family": "inet", "name": "unrelated"}}]}))

    monkeypatch.setattr(isolation, "run", read)
    assert isolation.current() == []
    assert len(calls) == 1


def test_main_checks_identity_before_any_firewall_call(isolation, settings, tmp_path, monkeypatch):
    path = tmp_path / "isolation.json"
    path.write_text(json.dumps(settings))
    path.chmod(0o600)
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(isolation.socket, "gethostname", lambda: "wrong-host")
    monkeypatch.setattr(isolation.sys, "argv", ["guard", "apply", str(path)])
    # This test does not rely on the workstation UID.
    from types import SimpleNamespace

    original_stat = isolation.Path.stat
    monkeypatch.setattr(
        isolation.Path,
        "stat",
        lambda self, **kwargs: SimpleNamespace(st_uid=0, st_mode=original_stat(self, **kwargs).st_mode),
    )
    with pytest.raises(ValueError, match="identity"):
        isolation.main()
