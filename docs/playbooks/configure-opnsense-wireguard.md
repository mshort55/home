# Local HOME WireGuard administration

The `opnsense_wireguard` role owns one WireGuard instance, one Mac peer, an assigned `WG_ADMIN` interface, named firewall rules and one DNS ACL. OXL manages supported WireGuard, firewall and Unbound resources. The native OPNsense helper handles interface assignment, protected ownership records, backups and runtime verification.

The required `opnsense_wireguard_options.task_action` choices are `prepare`, `configure` and `verify`; named entry points supply those actions. There is no default action. Define `opnsense_wireguard` on the guest as shown in [inventory.example.yml](../../inventory.example.yml). Its fields are documented in the [role contract](../../roles/opnsense_wireguard/meta/argument_specs.yml).

## Scope and prerequisites

Complete the installed management and HOME pilots. Run infrastructure commands with the controller on wired MGMT. The HOME endpoint and named MGMT addresses must match inventory; the tunnel uses a distinct private /24. The server peer's AllowedIPs contains only the laptop's /32. The Mac routes only MGMT and the firewall's tunnel /32.

Policy permits the laptop to reach firewall SSH/HTTPS/DNS/NTP/ICMP, Proxmox SSH/UI/ICMP and switch SSH/ICMP. All other tunnel traffic is blocked. HOME gains only a UDP handshake allowance to its firewall gateway. MGMT also permits ICMP from the named switch to its firewall gateway, allowing the gateway workflow to verify reachability. Existing HOME internet and isolation remain in place. DEV and BMC routing, WAN ingress, full tunneling, allocation changes and key rotation require separate workflows.

## Enroll and prepare

Enrollment adds `page-wireguard-config` to the restricted account's existing privileges, preserving its API key and certificate:

```bash
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01 --check
ansible-playbook playbooks/prepare-wireguard-client.yml --limit opnsense01 --check
ansible-playbook playbooks/prepare-wireguard-client.yml --limit opnsense01
ansible-playbook playbooks/prepare-wireguard-client.yml --limit opnsense01 --check
```

The controller action plugin generates two independent X25519 pairs once. It encrypts `.cache/wireguard/opnsense01/keys.vault.yml` using the Vault secret Ansible already unlocked, and renders `.cache/wireguard/opnsense01/home-admin.conf`. The directory is mode 0700 and files mode 0600. The client file contains its private key and is a secret. The server private key stays in the encrypted store and OPNsense configuration, outside the client file. Artifacts are Git-ignored.

Preview creates no keys or files. Repeats keep the original keys; an existing client with missing encrypted keys fails rather than replacing its identity. Keep a protected recovery copy of the encrypted store and its unlock password separately. Configuration and verification use the same unlocked Vault credentials. When using another checkout, securely transfer the artifacts with their required permissions; reconciliation refuses a different recorded identity.

`wireguard_key_directory` optionally selects another absolute protected controller directory. `wireguard_mtu` defaults to 1420 and accepts 1280–1500. The plugin uses the pinned Ansible/cryptography environment.

## Configure, repeat and verify

```bash
ansible-playbook playbooks/configure-opnsense-wireguard.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-wireguard.yml --limit opnsense01
ansible-playbook playbooks/configure-opnsense-wireguard.yml --limit opnsense01 --check
ansible-playbook playbooks/verify-opnsense-wireguard.yml --limit opnsense01
```

Preview reads identity, validates vendor models and previews supported OXL resources without writes. Before the assigned interface exists, rule preview uses the vendor model because OXL's selector cannot select a missing interface. Prerequisite failures stop before device writes.

Apply preserves the original configuration in `/conf/ansible-wireguard/before-*.xml`, records a pending transaction, assigns the interface, merges supported resources and verifies loaded state before completing. A protected controller copy is exported under `backups/<guest>-wireguard-*/before.xml`. An interrupted run retains the original backup and reconciles the pending transaction. Matching repeats save and reload nothing. Other instances/peers, conflicting assignments, keys and recorded allocations are refused.

The assigned interface uses empty IPv4/IPv6 modes, matching the GUI's **None** setting; WireGuard owns its tunnel address. After reload, the workflow restores a missing address through the vendor's start action scoped to the verified instance. This runs only when that address is absent and the running key, port and peer match. DNS verification uses `unbound-checkconf` to resolve ACLs from the main configuration and its included files. Verification failures identify the saved settings or runtime checks that still need reconciliation.

Existing management, HOME and maintenance workflows preserve only the exact WireGuard objects in the protected ownership record. Missing or changed owned objects and unrelated policy are rejected. Their SSH source checks accept the original wired administrators or the single peer in the completed WireGuard record. The verification entry reads saved models, loaded rules, the DNS ACL, live tunnel address/key/port and exact peer /32. OXL reports handshake status; a handshake is not required before the Mac connects.

## Switch return route

Set `switch_management.default_gateway` to the installed firewall on MGMT. The [switch gateway workflow](configure-switch-gateway.md) provides replies to routed tunnel clients:

```bash
ansible-playbook playbooks/configure-switch-gateway.yml --check
ansible-playbook playbooks/configure-switch-gateway.yml
ansible-playbook playbooks/configure-switch-gateway.yml --check
```

## Mac import and acceptance

Import the checkout's private `home-admin.conf` into the native [WireGuard Mac app](https://www.wireguard.com/install/). Import and activation are manual; Ansible prepares the full configuration. Keep the tunnel disabled until the Mac is on HOME DHCP.

Use the actual private addresses for the example tests below. With Wi-Fi/VPN off and the tunnel disabled, management SSH/UI and native management ping must time out. Enable this tunnel and run in native macOS Terminal:

```bash
ping -c 4 10.77.99.1
ping -c 4 10.77.10.10
nc -vz -G 3 10.77.10.10 22
nc -vz -G 3 10.77.10.10 8006
nc -vz -G 3 10.77.10.254 443
nc -vz -G 3 10.77.10.2 22
dig @10.77.10.254 pve01.lab.home.arpa
curl --connect-timeout 5 --max-time 15 -I https://example.com
```

Use trusted host keys/certificates for actual logins. DNS should return Proxmox's address; general internet stays on HOME. Ubuntu uses `nc -w 3` rather than macOS `-G 3`. Run ICMP acceptance in native macOS because container networking can give results that do not reflect native client reachability. Disable the tunnel and confirm management is blocked again. A recent handshake plus native tests establish end-to-end access; device verification alone does not prove it.

Return to wired MGMT, then run verification and both pilot previews:

```bash
ansible-playbook playbooks/verify-opnsense-wireguard.yml --limit opnsense01
ansible-playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
ansible-playbook playbooks/configure-opnsense-management.yml --limit pve01 --check
```

References: [OXL WireGuard modules](https://ansible-opnsense.oxl.app/modules/wireguard.html), [OPNsense client-to-site configuration](https://docs.opnsense.org/manual/how-tos/wireguard-client.html).
