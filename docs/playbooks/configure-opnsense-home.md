# Configure an isolated HOME pilot

`playbooks/configure-opnsense-home.yml` extends the installed management pilot with one HOME network on the existing VLAN-20 guest NIC. It uses OXL for firewall, Unbound and Kea DHCP configuration, and the vendor configuration model for the assigned interface and NTP bindings. The existing household router continues providing the pilot WAN.

## Inventory and prerequisites

Complete installation, both API enrollments and the management pilot first. Keep the controller on MGMT while running infrastructure playbooks. Define the allocation on the OPNsense guest:

```yaml
opnsense_home_pilot:
  address: 10.77.200.254
  subnet: 10.77.200.0/24
  pool_start: 10.77.200.100
  pool_end: 10.77.200.199
  lease_seconds: 3600
```

Use actual addresses from the private inventory. HOME must be a private 10/8 /24 distinct from MGMT and the pilot WAN, and its gateway must sit outside the DHCP pool. On the switch, define a dedicated access-VLAN-20 port with role `home_pilot`; keep server LAN trunk VLAN 20 available. The example inventory uses port 36; physical port numbers come from your inventory.

Rerun API enrollment to add Kea DHCPv4 access to the existing owned API account. It preserves the key and certificate, and this privilege update needs no GUI restart:

```bash
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01
ansible-playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
ansible-playbook playbooks/configure-opnsense-home.yml --limit pve01
ansible-playbook playbooks/configure-switch-home-pilot-port.yml --check
ansible-playbook playbooks/configure-switch-home-pilot-port.yml
```

Review each preview before applying. The HOME entry point reuses management and VM verification, validates candidate vendor models without saving, and checks the required DHCP privilege before OXL access. Apply saves a protected backup and pending transaction, merges the API objects, configures only the HOME interface, reloads services and checks the saved and loaded policy. It verifies HOME addressing, Unbound, the running Kea service and its generated interface, subnet, pool, lease lifetime and gateway/DNS/NTP options, plus automatic outbound NAT. It also verifies existing MGMT and WAN connectivity. It does not start an installation or reboot the server.

## Client policy

Kea serves only HOME. Clients receive the configured pool, gateway, firewall DNS and NTP addresses, and the firewall's local domain. IPv6, DEV and BMC guest interfaces remain disabled. Unbound keeps the existing pinned forwarding resolvers and adds a HOME listener and access list.

HOME clients can use gateway ICMP, DNS and NTP, then reach external destinations through automatic NAT. Rules block firewall administration, MGMT, BMC, the existing private household LAN, other RFC1918 destinations, link-local and carrier NAT networks. Direct external TCP/UDP DNS on port 53 is blocked; this does not restrict encrypted DNS carried over other ports. The original management rules and their IDs are preserved. Standard Kea-generated DHCP rules permit address acquisition only on HOME.

## Test with one Mac

After both infrastructure applies succeed, move the Mac's Ethernet from its MGMT recovery port to the `home_pilot` port. In macOS network settings, select DHCP for Ethernet and disable Wi-Fi and VPN so test traffic uses HOME. The address must fall inside the configured pool, with the configured gateway and DNS server.

Use the actual private addresses when testing. For the example allocation:

```bash
route -n get 10.77.200.254
ping -c 4 10.77.200.254
dig @10.77.200.254 pve01.lab.home.arpa
dig @10.77.200.254 example.com
curl --connect-timeout 5 --max-time 15 -I https://example.com
```

The route must use Ethernet, ping and both DNS queries must succeed, and HTTPS must succeed. These tests should fail or time out:

```bash
nc -vz -G 3 10.77.10.10 22
nc -vz -G 3 10.77.10.254 443
nc -vz -G 3 10.77.40.10 443
nc -vz -G 3 10.77.55.254 443
dig +time=2 +tries=1 @1.1.1.1 example.com
dig +tcp +time=2 +tries=1 @1.1.1.1 example.com
```

MGMT playbooks cannot run through this isolated HOME connection. Return Ethernet to the MGMT recovery port and restore its static administrator address and /24 mask, with no router or DNS. Wi-Fi can then be restored. Repeat both infrastructure previews; they should report zero changes:

```bash
ansible-playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
ansible-playbook playbooks/configure-switch-home-pilot-port.yml --check
```

## Repeated and interrupted runs

The protected management transaction record also stores the owned HOME allocation. Management and boot-verification workflows consume that record, preserving HOME even when their inputs omit it. Reruns preserve API object IDs and reload nothing when saved and runtime settings already match. A pending transaction retains its original backup and reapplies services before verification. An existing HOME allocation cannot be changed through routine reruns; that requires a separate migration. Unowned DHCP services, subnets or enabled optional interfaces require review before proceeding.

References: [OXL DHCP modules](https://ansible-opnsense.oxl.app/modules/dhcp.html), [OPNsense Kea DHCP](https://docs.opnsense.org/manual/kea.html), [Kea API](https://docs.opnsense.org/development/api/core/kea.html).
