import copy
import json
from pathlib import Path

import pytest


@pytest.fixture
def inspector(load_module):
    return load_module("scripts/inspect-unifi-firewall.py")


@pytest.fixture
def policy(load_module):
    return load_module("scripts/unifi-isolation.py").document(
        {
            "hostname": "unifi01",
            "gateway": "10.77.10.254",
            "tunnel_address": "10.77.99.2",
            "recovery_address": "10.77.10.250",
        }
    )


def test_handles_and_metadata_do_not_change_policy(inspector, policy):
    expected = inspector.desired_objects(policy)
    observed = copy.deepcopy(expected)
    for item in observed:
        next(iter(item.values()))["handle"] = 123
    observed.insert(0, {"metainfo": {"version": "different"}})
    assert inspector.normalize(observed) == expected
    observed[-1]["rule"]["expr"] = [{"accept": None}]
    assert inspector.normalize(observed) != expected


@pytest.mark.parametrize(
    "item",
    [
        {"set": {"family": "inet", "table": "home_unifi", "name": "unexpected"}},
        {"table": {"family": "inet", "name": "foreign"}},
        {"table": {"family": "ip", "name": "home_unifi"}},
    ],
)
def test_unexpected_objects_rejected(inspector, item):
    with pytest.raises(ValueError):
        inspector.normalize([item])


def test_rule_order_matters(inspector, policy):
    expected = inspector.desired_objects(policy)
    changed = copy.deepcopy(expected)
    rules = [i for i, item in enumerate(changed) if item.get("rule", {}).get("chain") == "input"]
    changed[rules[0]], changed[rules[-1]] = changed[rules[-1]], changed[rules[0]]
    assert inspector.normalize(changed) != expected


@pytest.mark.parametrize("change", ["flush", "outside", "delete"])
def test_saved_document_must_be_bounded(inspector, policy, change):
    if change == "flush":
        policy["nftables"].insert(0, {"flush": {"ruleset": None}})
    elif change == "outside":
        policy["nftables"].append({"add": {"table": {"family": "inet", "name": "other"}}})
    else:
        policy["nftables"].append({"delete": {"table": inspector.TABLE}})
    with pytest.raises(ValueError):
        inspector.desired_objects(policy)


@pytest.mark.parametrize(
    "value", ["", "{ argv[]=/bin/true ; ignore_errors=no }", "{ argv[]=/usr/sbin/nft ; ignore_errors=yes }"]
)
def test_effective_command_override_rejected(inspector, monkeypatch, value):
    monkeypatch.setattr(inspector, "property_value", lambda *_: value)
    with pytest.raises(ValueError):
        inspector.require_commands("unit", "ExecStartPre", ["/usr/sbin/nft"])


def test_effective_commands(inspector, monkeypatch):
    monkeypatch.setattr(
        inspector,
        "property_value",
        lambda *_: "{ path=/usr/sbin/nft ; argv[]=/usr/sbin/nft ; ignore_errors=no ; pid=0 }",
    )
    inspector.require_commands("unit", "ExecStart", ["/usr/sbin/nft"])


@pytest.fixture
def inspection_environment(inspector, policy, monkeypatch):
    settings = {
        "hostname": "unifi01",
        "gateway": "10.77.10.254",
        "tunnel_address": "10.77.99.2",
        "recovery_address": "10.77.10.250",
    }
    state = {"saved": policy, "observed": inspector.desired_objects(policy), "missing": set(), "units": 0}
    monkeypatch.setattr(inspector.os, "geteuid", lambda: 0)
    monkeypatch.setattr(inspector.socket, "gethostname", lambda: "unifi01")
    monkeypatch.setattr(inspector, "protected", lambda path, *_, **__: path not in state["missing"])
    monkeypatch.setattr(inspector.Path, "resolve", lambda _: Path("/dev/null"))
    monkeypatch.setattr(
        inspector.Path,
        "read_text",
        lambda path: json.dumps(state["saved"] if str(path) == inspector.POLICY else settings),
    )
    calls = []

    def read(*args):
        calls.append(args)
        if args == ("/usr/sbin/nft", "-j", "list", "tables"):
            return json.dumps({"nftables": [item for item in state["observed"] if "table" in item]})
        assert args == ("/usr/sbin/nft", "-j", "list", "table", "inet", "home_unifi")
        return json.dumps({"nftables": state["observed"]})

    monkeypatch.setattr(inspector, "read", read)

    def units():
        state["units"] += 1

    monkeypatch.setattr(inspector, "verify_units", units)
    return {"mode": "verify", "settings": settings, "policy": policy}, state, calls


def test_inspection_read_only_and_independent(inspector, inspection_environment):
    payload, state, calls = inspection_environment
    assert inspector.inspect(payload)["live_policy"] == "verified"
    assert state["units"] == 1 and len(calls) == 2


@pytest.mark.parametrize("location", ["saved", "observed"])
def test_policy_drift_rejected(inspector, inspection_environment, location):
    payload, state, _ = inspection_environment
    if location == "saved":
        state["saved"] = copy.deepcopy(state["saved"])
        state["saved"]["nftables"][-1]["add"]["rule"]["expr"] = [{"accept": None}]
    else:
        state["observed"][-1]["rule"]["expr"] = [{"accept": None}]
    with pytest.raises(ValueError, match="policy differs"):
        inspector.inspect(payload)


def test_migration_requires_matching_live_policy(inspector, inspection_environment):
    payload, state, _ = inspection_environment
    state["missing"] = {inspector.POLICY}
    payload["mode"] = "plan"
    plan = inspector.inspect(payload)
    assert plan["migration"] and plan["live_matches"]
    assert inspector.desired_objects(plan["rollback_policy"]) == state["observed"]
    state["observed"][-1]["rule"]["expr"] = [{"accept": None}]
    with pytest.raises(ValueError, match="Legacy migration"):
        inspector.inspect(payload)


def test_verify_never_migrates(inspector, inspection_environment):
    payload, state, _ = inspection_environment
    state["missing"] = {inspector.POLICY}
    with pytest.raises(ValueError, match="configure-unifi-firewall"):
        inspector.inspect(payload)


def test_missing_guard_rejected(inspector, inspection_environment):
    payload, state, _ = inspection_environment
    state["missing"] = {inspector.GUARDS[0]}
    with pytest.raises(ValueError, match="Missing managed"):
        inspector.inspect(payload)


def test_wrong_host_rejected(inspector, inspection_environment, monkeypatch):
    payload, _, calls = inspection_environment
    monkeypatch.setattr(inspector.socket, "gethostname", lambda: "another-vm")
    with pytest.raises(ValueError, match="Wrong firewall host"):
        inspector.inspect(payload)
    assert not calls


def test_protected_rejects_symlinks_and_permissions(inspector, tmp_path):
    path = tmp_path / "policy"
    assert not inspector.protected(str(path), 0o600, optional=True)
    path.write_text("{}")
    path.chmod(0o666)
    with pytest.raises(ValueError, match="Unprotected"):
        inspector.protected(str(path), 0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="Unprotected"):
        inspector.protected(str(link), 0o600)


@pytest.fixture
def unit_environment(inspector, monkeypatch):
    own = "home-unifi-isolation.service"

    def commands(values):
        return " ".join("{ path=/usr/sbin/nft ; argv[]=" + value + " ; ignore_errors=no ; pid=0 }" for value in values)

    properties = {
        own: {
            "FragmentPath": inspector.UNIT,
            "DropInPaths": "",
            "Type": "oneshot",
            "RemainAfterExit": "yes",
            "DefaultDependencies": "no",
            "User": "",
            "NeedDaemonReload": "no",
            "ActiveState": "active",
            "Before": "network-pre.target uosserver.service uosserver-updater.service",
            "ExecStartPre": commands([inspector.CHECK]),
            "ExecStart": commands([inspector.LOAD]),
            "ExecReload": commands([inspector.LOAD]),
            "ExecStop": "",
            "ExecStopPost": "",
            "ExecStartPost": "",
        },
    }
    for vendor in ("uosserver.service", "uosserver-updater.service"):
        properties[vendor] = {
            "LoadState": "loaded",
            "FragmentPath": "/etc/systemd/system/" + vendor,
            "Requires": own,
            "After": own,
            "NeedDaemonReload": "no",
            "ExecStartPre": commands([inspector.CHECK, inspector.LOAD]),
        }
    monkeypatch.setattr(inspector, "property_value", lambda unit, name: properties[unit][name])
    monkeypatch.setattr(inspector, "read", lambda *_: "enabled")
    monkeypatch.setattr(
        inspector.Path,
        "read_text",
        lambda _: "\n".join(
            [
                "[Unit]",
                "Requires=" + own,
                "After=" + own,
                "[Service]",
                "ExecStartPre=+" + inspector.CHECK,
                "ExecStartPre=+" + inspector.LOAD,
            ]
        ),
    )
    return properties


def test_effective_startup_contract(inspector, unit_environment):
    inspector.verify_units()


def test_preinstallation_guards(inspector, unit_environment):
    for vendor in ("uosserver.service", "uosserver-updater.service"):
        unit_environment[vendor] = {"LoadState": "not-found", "FragmentPath": ""}
    inspector.verify_units()


@pytest.mark.parametrize(
    "unit,key,value",
    [
        ("home-unifi-isolation.service", "DropInPaths", "/unexpected.conf"),
        ("home-unifi-isolation.service", "Before", ""),
        ("home-unifi-isolation.service", "NeedDaemonReload", "yes"),
        ("home-unifi-isolation.service", "ExecStop", "{ argv[]=/usr/sbin/nft flush ruleset ; ignore_errors=no }"),
        ("uosserver.service", "Requires", ""),
        ("uosserver-updater.service", "After", ""),
        ("uosserver-updater.service", "NeedDaemonReload", "yes"),
        ("uosserver-updater.service", "ExecStartPre", ""),
    ],
)
def test_effective_startup_drift(inspector, unit_environment, unit, key, value):
    unit_environment[unit][key] = value
    with pytest.raises(ValueError):
        inspector.verify_units()


def test_saved_guard_drift(inspector, unit_environment, monkeypatch):
    monkeypatch.setattr(inspector.Path, "read_text", lambda _: "[Service]\nExecStartPre=/bin/true")
    with pytest.raises(ValueError, match="Saved vendor"):
        inspector.verify_units()


def test_missing_managed_table_can_be_repaired(inspector, inspection_environment):
    payload, state, _ = inspection_environment
    state["observed"] = []
    payload["mode"] = "plan"
    plan = inspector.inspect(payload)
    assert not plan["migration"] and not plan["live_matches"]
    assert plan["rollback_policy"]["nftables"] == [
        {"add": {"table": inspector.TABLE}},
        {"delete": {"table": inspector.TABLE}},
    ]
    payload["mode"] = "verify"
    with pytest.raises(ValueError, match="Loaded firewall policy differs"):
        inspector.inspect(payload)
