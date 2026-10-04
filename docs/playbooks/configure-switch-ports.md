# Configure switch ports from inventory

The normal inventory owns desired switch ports in `switch_ports`. [configure-switch-ports.yml](../../playbooks/configure-switch-ports.yml) configures selected access ports and static 802.1Q trunks through the pinned Cisco resource modules. [The management workflow](configure-switch-management.md) creates VLAN objects first.

## Inputs

Every port has a unique `role` and interface `name`, a `description`, and Boolean `enabled`. Access ports omit `mode` or set `mode: access`, and specify an integer `access_vlan`. Trunks use this schema; the port number below is synthetic:

```yaml
- role: server_lan
  name: GigabitEthernet1/0/32
  description: PVE-LAN
  mode: trunk
  native_vlan: 999
  allowed_vlans: [10, 20, 30, 40]
  allow_mode_change: true
  enabled: true
```

Trunks always use `dot1q` encapsulation and disable DTP with `switchport nonegotiate`. The allowed VLAN list is exact: previously allowed VLANs outside inventory are removed. Native VLAN 999 is deliberately excluded from this server trunk's allowed list so it provides no untagged data path. The native and allowed VLAN objects must all exist and be active before a port preview or apply.

`allow_mode_change` defaults to false. Set it explicitly for a reviewed access/trunk conversion, such as initial server-LAN preparation. The playbook refuses voice/private VLAN features, named access VLAN assignments, routed ports, aggregation members, interface services and interface ACLs. Existing layer-two settings outside the owned trunk fields are retained, including spanning-tree and pruning settings. Access configuration merges its mode and VLAN; it does not remove inactive trunk settings during a deliberate trunk-to-access conversion.

Actual assignments live in Git-ignored private inventory. `inventory.example.yml` uses synthetic addresses and port numbers. For staged migrations, set each role's VLANs in inventory and select only the roles being changed. This workflow changes no endpoint IPs, SVIs, routing, PoE or physical cables.

## Run

Run from `/Repos/home`; Vault prompts locally. Preview or apply all inventory ports:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-all-ports.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-all-ports.yml
```

Prefer explicit role selection during a staged migration. For server preparation, first preview and apply the VLAN workflow with MGMT/BMC/HOME/DEV/UNUSED in `switch_vlans`, then select only the three server roles:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml
.venv/bin/ansible-playbook playbooks/configure-switch-server-ports.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-server-ports.yml
```

Review each preview before its apply. A VLAN check-mode run does not create VLANs and cannot satisfy the port playbook's prerequisite. Inspect the selected physical jacks for unexpected attachments before applying. Prepare server ports with their cables disconnected; connect and identify server NICs by permanent MAC afterward. Pilot WAN is an access port on the existing household network; the ISP handoff remains attached to the current firewall. A direct ISP connection requires a separate cable move and compatible firewall WAN configuration.

The named recovery entry point selects only `recovery_mgmt` and `recovery_bmc`:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-recovery-ports.yml --check
```

`configure-switch-server-ports.yml` selects `server_mgmt`, `server_lan` and `pilot_wan`. `configure-switch-home-pilot-port.yml` selects only `home_pilot`. `configure-switch-idrac-port.yml` selects only `idrac`; `configure-switch-all-ports.yml` explicitly selects every inventory role. These entry points invoke the `cisco_switch` role with `task_action: ports`, retaining its backups, checks, read-back and save behavior. Interface numbers and VLANs still come from inventory. For custom role groups, use `configure-switch-ports.yml` with `cisco_switch_options: {task_action: ports}` and `switch_port_roles`. This selector is required and must be a nonempty list of unique, known role strings. Its role contract and initial scope assertion validate the selection before collecting a backup; missing scope never selects all ports implicitly.

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-home-pilot-port.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-home-pilot-port.yml
```

## Verification and failure handling

After validating the explicit role scope, normal runs invoke the existing switch backup workflow, then refuse unrelated running/startup differences beyond the known certificate-storage representation. Fresh interface/VLAN facts and selected raw interface configuration must pass the preflight guards before any write.

Access settings use `state: merged`. Selected trunks use `state: replaced` with current non-owned layer-two settings copied into their input. This is necessary because a merge would union the allowed VLAN lists. Descriptions and administrative state use `ios_interfaces` with `state: merged`.

IOS may omit its default access VLAN 1 from resource facts. If inventory requests VLAN 1 and the current numeric access VLAN is already 1 or absent, the access input omits that redundant assignment. A port on a nondefault VLAN still receives an explicit command to return to VLAN 1. Mode changes and nondefault VLAN assignments remain managed normally. Named access VLANs are refused because an absent numeric VLAN in that case cannot establish the default. Read-back continues to verify the actual numeric VLAN, treating an ordinary absent assignment as VLAN 1.

After applying, fresh facts must match each selected description, enabled state and access VLAN or exact trunk configuration, including disabled negotiation. VLAN ranges are expanded before comparison. Only verified actual changes are saved to startup. A successful repeat should propose no device changes while still creating a local backup. Check mode reads the device, reports proposed commands, and skips backup creation, post-write verification and saving. It cannot prove physical connectivity.

A failed or interrupted apply is not automatically rolled back. Use the backup and console recovery to inspect partial changes and reconcile running/startup deliberately before rerunning. Configuration read-back does not prove an endpoint works after its cable move. Keep a separate management path when changing the port carrying the administration session.
