# Permanent DEV and BMC access

This workflow brings permanent DEV/BMC routing online while household Wi-Fi still uses Fortinet. Both Wi-Fi and port 8 use the existing WireGuard peer. No direct Wi-Fi-to-lab route or Fortinet port forward is created. Inventory defines each zone's `address`, `subnet`, `target`, and `hostname` under `opnsense_lab`. The installed seed's MAC-to-role mapping selects each interface. DEV starts with a static guest; BMC has no DHCP.

## Apply and verify

Run from a controller that can reach the installed firewall through MGMT or authenticated WireGuard. Keep wired MGMT/BMC recovery available. Preview before normal apply:

```bash
ansible-playbook playbooks/configure-opnsense-bmc.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-bmc.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-bmc.yml --limit opnsense01

ansible-playbook playbooks/configure-opnsense-dev.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-dev.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-dev.yml --limit opnsense01

ansible-playbook playbooks/prepare-wireguard-clients.yml --limit opnsense01
```

Re-import `.cache/wireguard/opnsense01/home-admin.conf` and `home-admin-wifi.conf` in the Mac app. Only one may be active. Client routes come from completed enabled zone records, separate from immutable key allocation. Server peer AllowedIPs remain the single laptop /32.

With the updated Wi-Fi profile active, verify the actual iDRAC return route:

```bash
ansible-playbook playbooks/verify-idrac-bmc-route.yml --limit idrac01
```

This reads dedicated NIC identity, address, mask and gateway through trusted Redfish without an old import job. The certificate hostname must resolve to the BMC address on this controller, using the existing trusted iDRAC setup. A mismatch requires the reviewed iDRAC network workflow; this verifier does not replace addresses.

## Policy and ownership

OXL merges named lab firewall rules, DNS ACLs and the DEV host record. The SSH PHP adapter validates the installed identity, records intent and updates the native interface/NTP listeners. Before routing activates, it requires exact saved rules and loaded tunnel rules. OPNsense omits native rules for disabled interfaces, so their loaded state is checked after activation and a subsequent firewall reload, which also refreshes interface addresses and automatic outbound NAT. Completion checks saved configuration and loaded interfaces, rules, DNS and services.

The laptop peer may reach iDRAC TCP 443/ICMP and all IPv4 DEV workload ports. A firewall-address block precedes broad DEV access. DEV may use gateway DNS/NTP and public internet; private, link-local, CGNAT, loopback, multicast, reserved networks and external port-53 DNS are blocked. BMC may initiate only gateway DNS/NTP. IPv6 stays disabled. Guest firewalls still govern services. Console port 5900 is not enabled initially.

Protected `/conf/ansible-lab/{bmc,dev}.json` records retain allocation, seed identity, interface and exact owned objects. Pending transactions block unrelated workflows and resume through the owning zone's configure/disable entry point. Earlier MGMT/HOME/WireGuard verification preserves completed lab objects and listeners. Allocation changes require a separate migration. Reruns do not rotate keys or reinstall guests.

The original configuration is stored privately on the guest and exported to `backups/opnsense01-lab-{bmc,dev}/before.xml`. It can contain credentials.

## Disable a zone

```bash
ansible-playbook playbooks/disable-opnsense-dev.yml --limit opnsense01 --check
ansible-playbook playbooks/disable-opnsense-dev.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-dev-disabled.yml --limit opnsense01
ansible-playbook playbooks/disable-opnsense-bmc.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-bmc-disabled.yml --limit opnsense01
ansible-playbook playbooks/prepare-wireguard-clients.yml --limit opnsense01
```

Disable removes the gateway/listener, disables owned rules/ACLs and clears their connection states. It retains ownership for later configure and preserves guest disks and other zones. Re-import profiles after refreshing routes. Physical recovery remains available.

## Native Mac acceptance

With WireGuard off, DEV/BMC connections must fail. With it on, routes use `utun…`:

```bash
route -n get 10.55.30.10
route -n get 10.55.40.10
nc -vz -G 3 10.55.40.10 443
nc -vz -G 3 10.55.40.10 22
nc -vz -G 3 10.55.30.254 443
dig @10.55.10.254 dev01.shortnet.home.arpa
```

iDRAC HTTPS succeeds; unapproved iDRAC SSH and DEV-gateway GUI access time out. After [Fedora provisioning](fedora-dev.md), Fedora SSH succeeds. Repeat tunnel off/on/off and existing MGMT tests, then test the wired profile through port 8. Container ICMP is insufficient evidence of network isolation.
