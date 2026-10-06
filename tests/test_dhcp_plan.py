from copy import deepcopy

import pytest
from ansible.errors import AnsibleActionFail


@pytest.fixture
def dhcp(load_module):
    return load_module("plugins/action/fortigate_dhcp_plan.py")


@pytest.fixture
def inputs():
    server = {
        "id": 1,
        "interface": "lan",
        "netmask": "255.255.255.0",
        "default-gateway": "10.77.55.254",
        "ip-range": [{"start-ip": "10.77.55.100", "end-ip": "10.77.55.199"}],
        "reserved-address": [
            {
                "id": 7,
                "ip": "10.77.55.150",
                "mac": "02:77:00:00:00:07",
                "action": "reserved",
                "description": "Unrelated",
                "circuit-id": "keep-me",
            }
        ],
    }
    settings = {
        "server_id": 1,
        "interface": "lan",
        "subnet": "10.77.55.0/24",
        "gateway": "10.77.55.254",
        "reservations": [
            {"role": "pilot_wan", "id": 9001, "address": "10.77.55.132", "mac": "02:77:00:00:64:00"},
            {"role": "wifi_admin", "id": 9002, "address": "10.77.55.128", "mac": "02:77:00:00:00:80"},
        ],
    }
    leases = [{"ip": item["address"], "mac": item["mac"]} for item in settings["reservations"]]
    return server, settings, leases


def test_preserves_unrelated_reservations_and_inputs(dhcp, inputs):
    before = deepcopy(inputs)
    result = dhcp.plan(*inputs)
    assert inputs == before
    assert result["changed"] is False and result["needs_change"] is True
    assert result["reservations"][0]["circuit_id"] == "keep-me"
    server, settings, _ = inputs
    server["reserved-address"] = [
        {key.replace("_", "-"): value for key, value in item.items()} for item in result["reservations"]
    ]
    assert dhcp.plan(server, settings, [])["needs_change"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 2),
        ("interface", "wan"),
        ("status", "disable"),
        ("netmask", "255.255.0.0"),
        ("default-gateway", "10.77.55.1"),
    ],
)
def test_rejects_wrong_server(dhcp, inputs, field, value):
    inputs[0][field] = value
    with pytest.raises(AnsibleActionFail, match="Wrong DHCP server"):
        dhcp.plan(*inputs)


@pytest.mark.parametrize("address", ["10.77.55.0", "10.77.55.255", "10.77.55.254", "10.77.56.132", "10.77.55.50"])
def test_rejects_invalid_allocation(dhcp, inputs, address):
    inputs[1]["reservations"][0]["address"] = address
    with pytest.raises(AnsibleActionFail):
        dhcp.plan(*inputs)


@pytest.mark.parametrize("field", ["id", "address", "mac"])
def test_rejects_duplicate_identity(dhcp, inputs, field):
    inputs[1]["reservations"][1][field] = inputs[1]["reservations"][0][field]
    with pytest.raises(AnsibleActionFail, match="Duplicate reservation identity"):
        dhcp.plan(*inputs)


@pytest.mark.parametrize("mac", ["00:00:00:00:00:00", "01:77:00:00:00:01", "not-a-mac", None])
def test_rejects_non_unicast_or_invalid_mac(dhcp, mac):
    with pytest.raises(AnsibleActionFail):
        dhcp.mac(mac)


def test_normalizes_mac(dhcp):
    assert dhcp.mac("02:AA:BB:CC:DD:EE") == "02:aa:bb:cc:dd:ee"


@pytest.mark.parametrize(
    "kind", ["foreign_id", "foreign_ip", "foreign_mac", "wrong_lease", "missing_lease", "unknown_field", "duplicate_id"]
)
def test_refuses_lossy_or_conflicting_merge(dhcp, inputs, kind):
    server, settings, leases = inputs
    original = server["reserved-address"][0]
    if kind == "foreign_id":
        original["id"] = 9001
    elif kind == "foreign_ip":
        original["ip"] = settings["reservations"][0]["address"]
    elif kind == "foreign_mac":
        original["mac"] = settings["reservations"][0]["mac"]
    elif kind == "wrong_lease":
        leases[0]["mac"] = "02:77:00:00:00:ff"
    elif kind == "missing_lease":
        leases.clear()
    elif kind == "unknown_field":
        original["vendor-field"] = "cannot-discard"
    else:
        server["reserved-address"].append(deepcopy(original))
    with pytest.raises(AnsibleActionFail):
        dhcp.plan(*inputs)


@pytest.mark.parametrize("bad", [None, {}, "truncated"])
def test_rejects_incomplete_reservations(dhcp, bad):
    with pytest.raises(AnsibleActionFail):
        dhcp.reservations({"reserved-address": bad})


@pytest.mark.parametrize("subnet", ["10.77.55.0/25", "192.168.1.0/24", "10.77.55.1/24"])
def test_rejects_unsupported_network(dhcp, inputs, subnet):
    inputs[1]["subnet"] = subnet
    with pytest.raises(AnsibleActionFail):
        dhcp.plan(*inputs)


def test_requires_exact_roles(dhcp, inputs):
    inputs[1]["reservations"][0]["role"] = "unreviewed"
    with pytest.raises(AnsibleActionFail):
        dhcp.plan(*inputs)


def test_action_rejects_incomplete_arguments(dhcp, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(dhcp.ActionBase, "run", lambda *args: {})
    action = object.__new__(dhcp.ActionModule)
    action._task = SimpleNamespace(args={"server": {}})
    with pytest.raises(AnsibleActionFail, match="Supply complete"):
        action.run()
