import base64
import json
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_new_bootstrap_uses_native_policy_and_shared_startup_guards(load_module):
    allocation = {
        "name": "unifi01",
        "domain": "test.home.arpa",
        "username": "admin",
        "gateway": "10.77.10.254",
        "tunnel_address": "10.77.99.2",
        "recovery_address": "10.77.10.250",
        "ssh_public_key_files": ["/fake/admin.pub"],
    }
    settings = {key: allocation[key] for key in ("gateway", "tunnel_address", "recovery_address")}
    settings["hostname"] = allocation["name"]
    document = load_module("scripts/unifi-isolation.py").document(settings)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)  # noqa: S701 -- Cloud-init YAML, not HTML.
    env.filters.update(to_json=json.dumps, b64encode=lambda value: base64.b64encode(value.encode()).decode())

    def lookup(kind, name, **_):
        if kind.endswith(".file"):
            return "synthetic-test-key"
        if name == "isolation.json.j2":
            return json.dumps(settings)
        return Path(name).read_text()

    context = {
        "unifi_vm_allocation": allocation,
        "unifi_seed_directory": "/fake",
        "role_path": str(ROOT / "roles/unifi_vm"),
        "unifi_bootstrap_policy": {"stdout": json.dumps(document)},
        "lookup": lookup,
    }
    rendered = env.from_string((ROOT / "roles/unifi_vm/templates/user-data.yml.j2").read_text()).render(**context)
    cloud = yaml.safe_load(rendered)
    boot = cloud["bootcmd"][0][-1]
    compile(boot, "<cloud-init bootcmd>", "exec")
    assert "unifi-isolation.py" not in rendered
    # Inspect the literal bootcmd payloads without executing writes or nftables.
    import ast

    tree = ast.parse(boot)
    loop = next(node for node in tree.body if isinstance(node, ast.For))
    artifacts = {name: (base64.b64decode(encoded), mode) for name, encoded, mode in ast.literal_eval(loop.iter)}
    assert json.loads(artifacts["/etc/home-automation/unifi-policy.nft.json"][0]) == document
    assert artifacts["/etc/home-automation/unifi-policy.nft.json"][1] == 0o600
    assert json.loads(artifacts["/etc/home-automation/unifi-isolation.json"][0]) == settings
    files = {item["path"]: item for item in cloud["write_files"]}
    for vendor in ("uosserver", "uosserver-updater"):
        guard = files[f"/etc/systemd/system/{vendor}.service.d/10-home-isolation.conf"]
        assert (
            base64.b64decode(guard["content"]).decode()
            == (ROOT / "roles/unifi_firewall/templates/guard.conf.j2").read_text()
        )
    unit = files["/etc/systemd/system/home-unifi-isolation.service"]
    assert (
        base64.b64decode(unit["content"]).decode()
        == (ROOT / "roles/unifi_firewall/templates/isolation.service.j2").read_text()
    )
