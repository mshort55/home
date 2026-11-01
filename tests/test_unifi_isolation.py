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


def test_bounded_transaction(isolation, settings):
    commands = isolation.document(settings)["nftables"]
    table = {"table": {"family": "inet", "name": "home_unifi"}}
    assert commands[:2] == [{"add": table}, {"delete": table}]
    assert commands[2:] == [{"add": item} for item in isolation.rules(settings)]


@pytest.mark.parametrize(
    "key,value", [("gateway", "8.8.8.8"), ("gateway", "::1"), ("gateway", "bad"), ("tunnel_address", "10.77.10.254")]
)
def test_invalid_inputs(isolation, settings, key, value):
    settings[key] = value
    with pytest.raises(ValueError):
        isolation.document(settings)


def test_unknown_settings_rejected(isolation, settings):
    settings["extra"] = True
    with pytest.raises(ValueError):
        isolation.document(settings)
