# WireGuard from the existing household Wi-Fi

The `opnsense_wireguard_wifi` role adds one temporary UDP handshake rule on OPNsense's private pilot WAN. It uses the existing WireGuard instance, laptop key and management permissions. The HOME endpoint and wired pilot port remain available. No direct WAN SSH/HTTPS allowance, Fortinet internet port forward or additional tunnel network is created.

The required `opnsense_wireguard_wifi_options.task_action` choices are `inspect`, `configure`, `verify`, `remove` and `verify_absent`. Named entry points supply each action. The [role contract](../../roles/opnsense_wireguard_wifi/meta/argument_specs.yml) documents controller paths and the Fortinet inventory identity; there is no default action.

## Addresses and prerequisites

Complete [HOME WireGuard](configure-opnsense-wireguard.md). Keep Ethernet on the management recovery port with its static administrator address and Wi-Fi connected to the existing household network while configuring this workflow. The controller must reach both the enrolled OPNsense management endpoint and Fortinet's trusted HTTPS endpoint. Disable WireGuard during configuration/removal so administration does not depend on the transport being changed.

Inspect OPNsense without modifying anything:

```bash
ansible-playbook playbooks/inspect-opnsense-wireguard-wifi.yml --limit opnsense01
```

In native macOS Terminal, identify the active Wi-Fi device, IP and MAC:

```bash
networksetup -listallhardwareports
ipconfig getifaddr en0
ifconfig en0 | awk '/ether/{print $2}'
```

Use the active DHCP MAC. Private Wi-Fi Address must be stable for this SSID; rotating addresses invalidate the reservation. The source IPv4 restriction reduces exposure but does not authenticate the laptop; WireGuard's existing key remains the identity boundary.

Define `opnsense_wireguard_wifi` on the guest and the two `fortigate_pilot_dhcp` reservations on Fortinet as shown in [inventory.example.yml](../../inventory.example.yml). The WAN MAC must match the owned Proxmox WAN vNIC. The addresses must be distinct ordinary hosts on the reviewed private /24, separate from HOME, MGMT and the tunnel. The gateway must match the installed Fortinet pilot. The Wi-Fi workflow verifies both reservations through Fortinet before permitting ingress.

Configure/verify entries load the existing Vault file (`secrets/vault.yml`, or `vault_file`) and use `vault_devices[wireguard_wifi_fortigate_host].username/password` for the delegated Fortinet check. `wireguard_wifi_fortigate_host` defaults to `fortigate01`. Its connection variables remain scoped to that role; subsequent guest tasks retain their SSH context. Inspection, removal and absence verification do not require a Fortinet connection.

## Reserve the current leases

Prepare the certificate hostname on each Ansible controller before its first Fortinet request:

```bash
ansible-playbook playbooks/prepare-fortigate-controller.yml --limit fortigate01 --ask-become-pass
```

Run this inside the container when using container Ansible, and separately in native Terminal when using native Ansible. It manages only the dedicated `/etc/hosts` entry declared by `fortigate_controller_endpoint` in inventory. The become password is that controller's local sudo password, not the Vault/device password. Passwordless sudo controllers can omit `--ask-become-pass`. Check mode previews the mapping without changing it; a normal run is needed before the reservation preview. Matching repeats make no changes. Duplicate, shared-alias or conflicting entries are refused.

The URL retains the device's certificate hostname. An IP without a matching certificate subject alternative name cannot replace it while preserving verification. Reservation and backup workflows check local resolution before authenticating, and continue to validate TLS using the existing trust file. Container recreation may discard the mapping; rerun preparation on the recreated controller. The file task permits Ansible's non-atomic fallback for container bind-mounted hosts files.

`fortigate_pilot_dhcp` uses `fortinet.fortios` over certificate-verified HTTPAPI. Its explicit actions are `configure` and `verify`; its [contract](../../roles/fortigate_pilot_dhcp/meta/argument_specs.yml) declares the existing server, interface, subnet and exactly two reservations (`pilot_wan`, `wifi_admin`). `fortigate_pilot_vdom` defaults to `root`.

Choose unused, explicit reservation IDs. New reservations must match current DHCP leases inside the existing pool. Existing printer/other reservations are retained. Conflicting IDs, IPs/MACs, leases, incomplete responses or unsupported reservation fields are refused. The workflow exports the global configuration before changes, rechecks for concurrent changes, writes only the merged reservation collection, and verifies that the remaining server fields are unchanged. It does not renew clients, change the DHCP pool, gateway or DNS, or restart the firewall.

If the pre-write server comparison fails, no reservations are written. The workflow reports only differing field names and saves mode-0600 `dhcp-before.json` and `dhcp-recheck.json` beside the protected pre-change backup. These private responses support investigation without displaying server values in terminal output.

FortiOS can return different encrypted `ddns-key` ciphertext for unchanged configuration. Before writing, the workflow requires an unchanged nonempty CMDB revision, identical field sets and identical values for every other server field. Read-back compares all fields outside the reservation collection except this ciphertext; the submitted payload never includes `ddns_key`. Reservation read-back requires the exact planned IDs and values, preserving every existing field while allowing supported firmware defaults on new MAC reservations. See [Fortinet's explanation of varying encrypted configuration values](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Constant-changing-of-password-and-encrypted/ta-p/258874).

```bash
ansible-playbook playbooks/configure-fortigate-pilot-reservations.yml --limit fortigate01 --check
ansible-playbook playbooks/configure-fortigate-pilot-reservations.yml --limit fortigate01
ansible-playbook playbooks/configure-fortigate-pilot-reservations.yml --limit fortigate01 --check
ansible-playbook playbooks/verify-fortigate-pilot-reservations.yml --limit fortigate01
```

## Configure and verify

```bash
ansible-playbook playbooks/configure-opnsense-wireguard-wifi.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-wireguard-wifi.yml --limit opnsense01
ansible-playbook playbooks/configure-opnsense-wireguard-wifi.yml --limit opnsense01 --check
ansible-playbook playbooks/verify-opnsense-wireguard-wifi.yml --limit opnsense01
```

OXL manages the named WAN rule. It permits only the reserved Wi-Fi source /32 to the exact private WAN destination /32 on the existing WireGuard UDP port, before WAN default deny. Reply-to is disabled on this rule so replies to the same-subnet client use the connected route. The native helper validates installed identity, live WAN IP/MAC/gateway, the completed HOME/WireGuard records and exact saved/loaded rule fields. Other WAN pass rules require separate review.

Before a device write, the workflow validates the existing encrypted keys and additional import-file path. The protected `/conf/ansible-wireguard-wifi/state.json` records pending/completed intent, the rule UUID and the original backup. A controller copy is exported under `backups/<guest>-wireguard-wifi-*/before.xml`. Interrupted configuration resumes against the same allocation and backup; changing the transport allocation requires removing the previous exception first. Matching repeats save and reload nothing. Management/HOME reconciliation preserves only the exact completed Wi-Fi rule and refuses an incomplete transaction.

The additional mode-0600 `.cache/wireguard/opnsense01/home-admin-wifi.conf` uses the original peer identity and changes the endpoint to the reserved private WAN IP. The original `home-admin.conf` still targets HOME. Activate only one profile at a time. `wireguard_wifi_key_directory` defaults to the existing key directory, honoring `wireguard_key_directory` when set. The profile uses the installed tunnel's recorded MTU.

Import the Wi-Fi profile into the native WireGuard app. Disconnect Ethernet and test on normal Wi-Fi in native macOS Terminal, with other VPNs off:

1. With both profiles inactive, management SSH/HTTPS and native management ping must fail.
2. Activate the Wi-Fi profile; check a recent handshake, management routes through `utun`, named management services, tunnel DNS and ordinary internet access.
3. Deactivate it; management must be blocked again. Direct WAN SSH/HTTPS must remain blocked throughout.
4. Test the original profile from the wired HOME pilot with Wi-Fi off to confirm both ingress paths independently. Container ICMP is unsuitable for isolation acceptance; use native macOS.

Read-only device verification proves policy/runtime configuration; the native client tests prove actual tunnel access.

## Remove before ISP attachment

Return to direct wired MGMT and deactivate the tunnel before removal:

```bash
ansible-playbook playbooks/remove-opnsense-wireguard-wifi.yml --limit opnsense01 --check
ansible-playbook playbooks/remove-opnsense-wireguard-wifi.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-wireguard-wifi-absent.yml --limit opnsense01
```

Removal uses the protected ownership record and remains available if the old WAN lease/gateway changes or disappears. OXL deletes only the named owned rule; the helper clears only PF states associated with that rule's label, verifies saved/loaded absence and records completion. The controller Wi-Fi import file is removed; delete/deactivate its imported Mac app profile manually. Existing keys, the HOME profile and tunnel management rules are retained. Matching repeated removal does not reload the firewall.

The absence playbook is a required ISP-cutover preflight. Run it immediately before physical ISP attachment; do not treat an old successful result as proof after another configuration change. After cutover, normal Wi-Fi and the wired HOME port use the final HOME WireGuard endpoint. The future Fortinet standby workflow must reconcile its temporary pilot reservations with the final standby allocation.

References: [OPNsense WireGuard ingress and tunnel policy](https://docs.opnsense.org/manual/how-tos/wireguard-client.html), [FortiOS DHCP server module](https://docs.ansible.com/ansible/latest/collections/fortinet/fortios/fortios_system_dhcp_server_module.html), [scoped PF state removal](https://man.freebsd.org/cgi/man.cgi?query=pfctl&sektion=8).
