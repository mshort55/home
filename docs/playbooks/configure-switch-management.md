# Prepare switch management and recovery VLANs

[configure-switch-management.yml](../../playbooks/configure-switch-management.yml) creates the inventory-owned VLAN objects, disables switch IPv4 routing, and adds/enables the management SVI. The legacy management SVI/address remains available during transition. This workflow owns VLAN/SVI/routing configuration; [the existing shared port playbook](configure-switch-ports.md) owns access ports and static trunks, including recovery and server ports.

## Scope and prerequisites

`switch_vlans` lists managed VLAN IDs, names and active state. `switch_management` specifies the new VLAN/address/description and the legacy interface/address that must be preserved. Public inventory uses synthetic values; actual values stay in private inventory. This bounded implementation accepts /24 addresses and VLAN IDs 2–1001. MGMT 10 and BMC 40 are already applied; server preparation adds HOME 20, DEV 30 and UNUSED 999 to the same inventory list. Only MGMT receives a new SVI: adding HOME/DEV/BMC VLAN objects does not configure routing, addresses or DHCP for those networks. No new management default gateway is configured while the future firewall is unavailable.

Run from the repository root with the pinned environment. Vault prompts locally. Keep the already-verified switch console recovery available during apply. Verify that the recovery jacks are physically available before changing their access VLANs. The current administration session must use the legacy network; this stage keeps its same-subnet switch address.

Before a write, fresh running/startup configuration must agree apart from the known certificate representation. The workflow refuses configured routing protocols/static routes/policy routing/relay configuration and IPv6 routing. When IPv4 routing is enabled, live checks require only the legacy SVI to be up/up, no default/via route, connected routes only through that SVI, and no learned ARP peers in other VLANs. Inactive networks without observed peers are evidence about current operation, not proof that sleeping clients never use them. Stop for any known legacy dependency.

Existing VLAN names/special features and SVI addresses must be compatible with the inventory; conflicts stop before writes. This stage preserves old inactive SVIs. It changes no production access port, AP configuration, iDRAC address, gateway service, trunk, VTY/ACL, or shutdown policy.

## Preview, apply, then configure recovery ports

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml --check
.venv/bin/ansible-playbook playbooks/configure-switch-management.yml
```

Normal runs first use the existing switch-backup playbook. Check mode reads the live device and previews modules, skipping backups, post-write verification and saves. It cannot prove connectivity. Inspect the reported commands before applying; keep secret-bearing verbose/diff output disabled.

The workflow merges VLANs, disables routing, verifies routing is off, then adds the management SVI/address and administrative enablement. Read-back must confirm all managed VLANs, the new SVI and the preserved legacy address before saving actual changes to startup. A repeat run should report no device changes while still creating a backup. Owner confirmed live check-mode and normal apply succeeded; a subsequent no-change normal rerun remains unverified.

Resource facts are accessed through `ansible_facts['network_resources']`; repository configuration disables deprecated top-level fact injection explicitly. The pinned `ios_config` module emits a generic idempotency reminder whenever it proposes/applies configuration lines, including `no ip routing`. This is not a deprecation or a failed diff. The routing task runs only when fresh configuration shows routing enabled, and normal apply verifies routing is disabled before adding the SVI. Keep warnings enabled.

After a successful management apply, preview/apply only the two recovery roles through the shared port playbook:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["recovery_mgmt","recovery_bmc"]}' --check
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["recovery_mgmt","recovery_bmc"]}'
```

The port workflow requires real VLANs to exist; a management check-mode preview does not create them. A new SVI can remain protocol-down until a member port has link. Configure the MGMT recovery laptop with its reserved static /24 address and no gateway/DNS, disable Wi-Fi/tunnels/bridging for the recovery test, and connect to its designated MGMT jack. Verify ICMP and authenticated SSH to the new switch address using trusted host-key verification. Verify household service again. Restore the laptop's normal network settings after testing.

BMC recovery requires the coordinated iDRAC address/VLAN move as well as the switch ports. The owner has completed that move and verified direct BMC ICMP and successful import-task completion. Keep automation's switch connection on the legacy address until authenticated management through the new address passes. Retiring legacy SVIs, changing the management default gateway, and restricting VTY access are separate later changes.

## Failure and rollback

No automatic rollback occurs. If the run fails, use the retained legacy address or console, inspect any partial changes, and reconcile running/startup before retrying. Do not save unrelated partial changes merely to bypass the guard.

For a deliberate reversal, first restore the recovery ports to their captured prior access VLAN/descriptions/admin state, then remove the newly added management SVI through the console. Restore `ip routing` only after the new SVI is removed and the reviewed original routing state is confirmed; this order prevents a temporary inter-VLAN route. Leave production ports/cables and the legacy address intact. Newly created VLAN objects may remain inert; remove them only after confirming no ports depend on them. Reconcile inventory and pause management applies until the rollback state is understood. Save only after legacy access and household service pass.

The existing configuration backup exports running/startup text; it does not export the separate VLAN database. VLAN objects are reproducible from inventory, and their current state is verified through VLAN resource facts. Keep the original baseline and backup artifacts private.

## Validation record

Prepared locally, followed by owner-confirmed successful management and recovery-port application. Both management and shared port playbooks passed syntax checks using empty temporary credentials. Temporary offline fixtures passed 16 management guard scenarios: current operation and already-applied state accepted; unsaved configuration, configured/active routing dependencies, IPv6 forwarding, relay/policy configuration, active old SVIs/peers, VLAN/address conflicts and invalid/overlapping addresses refused. Pinned Cisco module rendering for VLAN/SVI/admin commands and parsing of the legacy SVI passed. Offline module invocation bypasses only the VLAN module's device-type probe; it does not establish live platform support. The owner requested no permanent Python tests, so these fixtures were removed.

2026-10-01: operator live check mode succeeded with 15 successful tasks, four proposed changes and no failures/unreachable hosts. Commands were exactly MGMT/BMC VLAN creation, `no ip routing`, and the inventory-owned Vlan10 address/description/enablement. No configuration was applied. Deprecated fact references identified in that preview were replaced in both switch workflows; tests now exercise actual module-fact normalization and both workflows' read-back assertions with injection disabled. All seven repository playbooks passed offline syntax checks; source review and pinned metadata for 19 modules used across playbooks and the included iDRAC task file found no other deprecated usage. Other playbooks were not edited. Owner subsequently confirmed updated management check-mode and normal apply both succeeded. Recovery-port apply and physical wired-recovery tests remain pending.

Reference: [Ansible 13 fact-injection migration guidance](https://docs.ansible.com/projects/ansible/latest/porting_guides/porting_guide_13.html).

The pre-management backup was independently verified for completion, hashes, sizes, private permissions and running/startup equivalence outside certificate representation. It matches the post-repatch baseline and precedes management writes. The reported successful normal run completed the workflow's configured-state checks and save step; no post-apply backup or independent live read-back has yet been collected.

Subsequent progress: owner confirmed the shared recovery-port apply succeeded. An independently verified backup taken before that port apply confirms saved management-address configuration and disabled IPv4 routing. Initial direct recovery failed because the recovery jack had no Ethernet link. Connecting the test Mac cable to the designated MGMT recovery jack produced successful ICMP to the new switch address. Authenticated management through the new address, a post-recovery-port backup and no-change normal reruns remain pending.

Post-recovery verification: independent configuration-backup checks confirm hashes/sizes/private permissions, equivalent running/startup bodies outside certificate representation, saved management and retained legacy addresses, IPv4/IPv6 routing disabled and all seven then-managed access-port definitions in both exports. Only the two recovery interfaces changed relative to the pre-port-apply backup. Configured-state persistence and direct MGMT ICMP acceptance are complete. The BMC endpoint transition subsequently completed, including direct ICMP and owner-confirmed import-task success. New-address authenticated switch access and no-change normal reruns remain pending.

Server preparation subsequently passed: the owner applied the VLAN stage, then a live scoped port preview confirmed the required active VLANs existed, including HOME/DEV/UNUSED. Server-port application and startup persistence are independently verified from the post-apply configuration backup. The backup does not export the separate VLAN database; active VLAN availability is established by the live port-playbook checks. Server cabling/link acceptance remains next.
