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

`allow_mode_change` defaults to false. Set it explicitly for a reviewed access/trunk conversion, such as initial server-LAN preparation. The playbook refuses voice/private VLAN features, routed ports, aggregation members, interface services and interface ACLs. Existing layer-two settings outside the owned trunk fields are retained, including spanning-tree and pruning settings. Access configuration merges its mode and VLAN; it does not remove inactive trunk settings during a deliberate trunk-to-access conversion.

Actual assignments live in Git-ignored private inventory. `inventory.example.yml` uses synthetic addresses and port numbers. Update inventory as each stage advances. The household/AP roles still use the legacy network during server preparation; the accepted iDRAC role uses BMC. This workflow changes no endpoint IPs, SVIs, routing, PoE or physical cables.

## Run

Run from `/Repos/home`; Vault prompts locally. Preview or apply all inventory ports:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml
```

Prefer explicit role selection during a staged migration. For server preparation, first preview and apply the VLAN workflow with MGMT/BMC/HOME/DEV/UNUSED in `switch_vlans`, then select only the three server roles:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["server_mgmt","server_lan","pilot_wan"]}' --check
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["server_mgmt","server_lan","pilot_wan"]}'
```

Review each preview before its apply. A VLAN check-mode run does not create VLANs and cannot satisfy the port playbook's prerequisite. Inspect the selected physical jacks for unexpected attachments before applying. Prepare server ports with their cables disconnected; connect and identify server NICs by permanent MAC afterward. Pilot WAN is an access port on the existing household network; the ISP handoff remains attached to the current firewall. Follow the private cabling plan for the later direct ISP connection.

Recovery roles remain selectable through the same entry point:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["recovery_mgmt","recovery_bmc"]}' --check
```

## Verification and failure handling

Normal runs first invoke the existing switch backup workflow, then refuse unrelated running/startup differences beyond the known certificate-storage representation. Fresh interface/VLAN facts and selected raw interface configuration must pass the preflight guards before any write.

Access settings use `state: merged`. Selected trunks use `state: replaced` with current non-owned layer-two settings copied into their input. This is necessary because a merge would union the allowed VLAN lists. Descriptions and administrative state use `ios_interfaces` with `state: merged`.

After applying, fresh facts must match each selected description, enabled state and access VLAN or exact trunk configuration, including disabled negotiation. VLAN ranges are expanded before comparison. Only verified actual changes are saved to startup. A successful repeat should propose no device changes while still creating a local backup. Check mode reads the device, reports proposed commands, and skips backup creation, post-write verification and saving. It cannot prove physical connectivity.

A failed or interrupted apply is not automatically rolled back. Use the backup and console recovery to inspect partial changes and reconcile running/startup deliberately before rerunning. Configuration read-back does not prove an endpoint works after its cable move. Keep a separate management path when changing the port carrying the administration session.

## Validation record

The owner previously applied household and recovery access-port stages. Independent private backups verified their descriptions, VLANs, enabled state and startup persistence. Direct wired MGMT ICMP passed. The owner subsequently completed the iDRAC address/VLAN migration and confirmed BMC ICMP and import-task success.

The owner applied the VLAN stage, successfully previewed the three server roles, then applied them and collected a post-apply backup. Independent checks confirm all ten managed port definitions in both running and startup, with only the three selected server interfaces changed from the pre-apply backup. File checksums, sizes and private permissions passed. Running/startup match after normalization of the known certificate-storage representation; other configuration is unchanged. Server cabling/link acceptance and a live no-change rerun remain pending.

Offline checks use the pinned resource parser and command generator, plus actual playbook assertions with fact injection disabled. They cover initial conversion, exact allowed-VLAN removal, preservation of other layer-two settings, no-change trunk repetition, invalid inputs/dependencies and fresh read-back. Temporary fixtures are removed after validation; no permanent Python tests are retained.

Resource facts use `ansible_facts['network_resources']`; shared Ansible configuration disables deprecated top-level fact injection. The owner-provided live server-port preview completed without deprecation warnings.
