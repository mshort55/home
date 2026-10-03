# Configure switch ports from inventory

The normal inventory owns the current desired switch-port configuration in `switch_ports`. [configure-switch-ports.yml](../../playbooks/configure-switch-ports.yml) applies all listed ports, including the iDRAC switch port.

The five household/infrastructure ports remain on VLAN 1. Inventory also prepares two permanently enabled recovery access ports: MGMT VLAN 10 and BMC VLAN 40. First create their VLANs with [the management workflow](configure-switch-management.md); this port playbook requires selected VLANs to exist. It sets descriptions, access mode/VLAN and administrative enablement and leaves original source ports available for cable-return rollback. It does not move cables or alter device addresses, routing, SVIs, trunks, spanning tree, PoE settings or ACLs.

## Run

Preview all managed ports using live device reads and Ansible check mode:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml --check
```

Apply and verify all managed ports:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml
```

Or select a role while moving one endpoint at a time:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["ap1"]}'
```

Vault prompts locally. Configuration stays in the inventory, not temporary variable files. The real inventory remains Git-ignored; `inventory.example.yml` demonstrates the schema with synthetic port numbers; replace them with your own assignments in the private inventory. Run from `/Repos/home`.

For the prepared recovery stage, after the management workflow succeeds:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["recovery_mgmt","recovery_bmc"]}' --check
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["recovery_mgmt","recovery_bmc"]}'
```

Inspect the recovery jacks for unexpected physical attachments before applying. Check mode of the management workflow does not create VLANs, so it cannot satisfy this playbook's existing-VLAN prerequisite. Until management is applied, scope any port run to the five existing VLAN-1 roles.

## Behavior and limits

Normal runs first invoke the existing switch backup playbook. Before writes, they refuse running/startup differences beyond the known certificate-storage representation so saving does not silently persist unrelated unsaved work. Selected interfaces must exist as access ports, without configured trunk/voice features, and desired VLANs must already exist. This is deliberately an access-port implementation; future trunk configuration needs the corresponding implementation before adding such roles.

The pinned Cisco resource modules merge interface and layer-two settings and compare current state rather than blindly replaying commands. After application, fresh resource facts must match the selected descriptions, enabled state and VLANs before saving to startup. Saving occurs only when port configuration changed. Repeating a successful run should leave device configuration unchanged, though it creates another local backup. Check mode performs live reads and module previews, skips backups and startup saves, and cannot prove post-change endpoint connectivity.

A failed or interrupted apply is not automatically rolled back. Use the saved backup and console recovery to review any partial changes. If running/startup differ after interruption, reconcile them deliberately before rerunning. Keep an alternate management path when changing the port carrying the administration session. Device configuration read-back does not prove the endpoint works after a physical move.

As migration advances, update the inventory to the accepted current state and extend the appropriate configuration workflow. Do not keep an old VLAN-1 playbook to replay after migration: these entry points share one current source of desired state. Management VLANs/SVIs, trunks, access controls and later snooping/ARP inspection will be added and verified as their stages arrive. This is not yet a complete rebuild of the final switch design.

## Validation

Offline syntax checks and resource parsing/rendering are run against the saved baseline. Live application succeeded: an independently collected post-apply backup verified all five desired port descriptions, access VLANs and enabled states in both running and startup configurations. The only changes from the pre-apply baseline were the five intended descriptions; configuration outside managed ports was unchanged. Backup checksums, sizes and private permissions passed. Running/startup differences were limited to certificate storage representation. A no-change rerun remains unverified. This workflow manages switch ports only; the iDRAC IP/VLAN transition will be coordinated with BMC recovery later.

Reference: [Cisco IOS resource modules](https://docs.ansible.com/projects/ansible/latest/collections/cisco/ios/index.html).

2026-10-01 modernization: resource facts now use `ansible_facts['network_resources']`, with top-level injection disabled in shared configuration. Offline checks exercise this workflow's pre-apply and read-back assertions using real Ansible fact normalization and synthetic facts. Syntax validation passed. Updated live apply/repeat behavior is still pending.
