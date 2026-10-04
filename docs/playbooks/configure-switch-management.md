# Prepare switch management and recovery VLANs

[configure-switch-management.yml](../../playbooks/configure-switch-management.yml) creates the inventory-owned VLAN objects, disables switch IPv4 routing, and adds/enables the management SVI. The legacy management SVI/address remains available during transition. This workflow owns VLAN/SVI/routing configuration; [the existing switch role](configure-switch-ports.md) owns access ports and static trunks, including recovery and server ports.

## Scope and prerequisites

`switch_vlans` lists managed VLAN IDs, names and active state. `switch_management` specifies the new VLAN/address/description and the legacy interface/address that must be preserved. Public inventory uses synthetic values; actual values stay in private inventory. This bounded implementation accepts /24 addresses and VLAN IDs 2–1001. The inventory list can include MGMT, BMC, HOME, DEV and UNUSED VLANs. Only the management VLAN receives a new SVI; other VLAN objects do not receive routing, addresses or DHCP. The playbook does not configure a management default gateway.

Run from the repository root with the pinned environment. Vault prompts locally. Verify console recovery access before applying changes, and keep it available during the run. Verify that the recovery jacks are physically available before changing their access VLANs. The current administration session must use the legacy network; this stage keeps its same-subnet switch address.

Before a write, fresh running/startup configuration must agree apart from the known certificate representation. The workflow refuses configured routing protocols/static routes/policy routing/relay configuration and IPv6 routing. When IPv4 routing is enabled, live checks require only the legacy SVI to be up/up, no default/via route, connected routes only through that SVI, and no learned ARP peers in other VLANs. Inactive networks without observed peers are evidence about current operation, not proof that sleeping clients never use them. Stop for any known legacy dependency.

Existing VLAN names/special features and SVI addresses must be compatible with the inventory; conflicts stop before writes. This stage preserves old inactive SVIs. It changes no production access port, AP configuration, iDRAC address, gateway service, trunk, VTY/ACL, or shutdown policy.

## Preview, apply, then configure recovery ports

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml
```

Normal runs first use the existing switch-backup playbook. Check mode reads the live device and previews modules, skipping backups, post-write verification and saves. It cannot prove connectivity. Inspect the reported commands before applying; keep secret-bearing verbose/diff output disabled.

The workflow merges VLANs, disables routing, verifies routing is off, then adds the management SVI/address and administrative enablement. Read-back must confirm all managed VLANs, the new SVI and the preserved legacy address before saving actual changes to startup. A repeat run should report no device changes while still creating a backup.

Resource facts are accessed through `ansible_facts['network_resources']`; repository configuration disables deprecated top-level fact injection explicitly. The pinned `ios_config` module emits a generic idempotency reminder whenever it proposes/applies configuration lines, including `no ip routing`. This is not a deprecation or a failed diff. The routing task runs only when fresh configuration shows routing enabled, and normal apply verifies routing is disabled before adding the SVI. Keep warnings enabled.

After a successful management apply, preview/apply only the two recovery roles through the switch role:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-recovery-ports.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-recovery-ports.yml
```

The port workflow requires real VLANs to exist; a management check-mode preview does not create them. A new SVI can remain protocol-down until a member port has link. Configure the MGMT recovery laptop with its reserved static /24 address and no gateway/DNS, disable Wi-Fi/tunnels/bridging for the recovery test, and connect to its designated MGMT jack. Verify ICMP and authenticated SSH to the new switch address using trusted host-key verification. Verify household service again. Restore the laptop's normal network settings after testing.

BMC recovery requires the coordinated iDRAC address/VLAN move as well as the switch ports. Keep automation's switch connection on the legacy address until authenticated management through the new address passes. Retiring legacy SVIs, changing the management default gateway, and restricting VTY access are separate later changes.

## Failure and rollback

No automatic rollback occurs. If the run fails, use the retained legacy address or console, inspect any partial changes, and reconcile running/startup before retrying. Do not save unrelated partial changes merely to bypass the guard.

For a deliberate reversal, first restore the recovery ports to their captured prior access VLAN/descriptions/admin state, then remove the newly added management SVI through the console. Restore `ip routing` only after the new SVI is removed and the reviewed original routing state is confirmed; this order prevents a temporary inter-VLAN route. Leave production ports/cables and the legacy address intact. Newly created VLAN objects may remain inert; remove them only after confirming no ports depend on them. Reconcile inventory and pause management applies until the rollback state is understood. Save only after legacy access and household service pass.

The existing configuration backup exports running/startup text; it does not export the separate VLAN database. VLAN objects are reproducible from inventory, and their current state is verified through VLAN resource facts. Keep the original baseline and backup artifacts private.

Reference: [Ansible 13 fact-injection migration guidance](https://docs.ansible.com/projects/ansible/latest/porting_guides/porting_guide_13.html).
