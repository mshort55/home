# Configure OPNsense management and its private WAN pilot

`playbooks/configure-opnsense-pilot.yml` configures an installed, owned OPNsense 26.7 VM using `oxlorg.opnsense` over verified HTTPS. OXL owns firewall rules, Unbound listeners, ACLs and host records. The pinned SSH helper validates guest identity and loaded policy, and saves the settings outside OXL's API coverage: system resolvers, NTP, WAN flags, anti-lockout, automatic outbound NAT, system-DNS forwarding and default DNS ACL action. Guest Python is unnecessary.

This stage enables management DNS/NTP and outbound HTTP/HTTPS for explicitly named infrastructure hosts. Before a HOME pilot is enrolled, HOME, DEV and BMC remain assigned but disabled and no DHCP server is enabled. Later runs preserve the recorded [HOME pilot](configure-opnsense-home.md). WireGuard, port forwards and household gateway migration use separate workflows. IPv6 forwarding remains disabled. API account and GUI certificate trust are provisioned by [OPNsense API enrollment](configure-opnsense-api.md); interactive GUI accounts, host updates and other zone policies use separate workflows.

## Prerequisites and inventory

Complete [installation](install-opnsense.md), then [OPNsense API enrollment](configure-opnsense-api.md) on this controller. [Proxmox API enrollment](configure-proxmox-api.md) must also be available for VM operations. Keep the existing household router active, with the server's WAN bridge connected to the existing household LAN through its pilot switch port. Do not attach the ISP cable during this workflow. The WAN pilot gateway must belong to a different private 10/8 /24 from management.

Keep VM MACs, bridges, tags and hardware unchanged. Set `opnsense_vm.wan_connected: true` on the Proxmox host; the pilot playbook applies this desired link state only after the guest's configuration and loaded policy pass verification. Keep `onboot: false` through initial installation and pilot setup; [configure-proxmox-boot.yml](configure-proxmox-boot.md) enables it afterward. Pilot repeat runs also support that enabled setting. A first or incomplete installation requires disconnected WAN; completed running installations can also be verified after WAN attachment. Use this pilot entry point to verify management services and connectivity.

Define `opnsense_pilot` on the **guest**, using your actual private addresses:

```yaml
opnsense_pilot:
  admin_addresses: [10.77.10.250]
  update_addresses: [10.77.10.10]
  wan_gateway: 10.77.55.254
  dns_servers: [192.0.2.53, 198.51.100.53]  # Replace these documentation addresses.
  ntp_servers:
    - 0.opnsense.pool.ntp.org
    - 1.opnsense.pool.ntp.org
    - 2.opnsense.pool.ntp.org
    - 3.opnsense.pool.ntp.org
  dns_hosts:
    - {hostname: opnsense01, address: 10.77.10.254}
    - {hostname: pve01, address: 10.77.10.10}
    - {hostname: switch01, address: 10.77.10.2}
```

Administration and update hosts must be ordinary addresses on the installed management /24. The current SSH controller's observed source address must appear in `admin_addresses`; this check occurs before removing broad bootstrap access. Local DNS records use the installed firewall domain. Configure the Proxmox host's existing management gateway and resolver to use the firewall, as established during its installation.

## Preview, apply and repeat

```bash
ansible-playbook playbooks/configure-opnsense-pilot.yml --limit pve01 --check
ansible-playbook playbooks/configure-opnsense-pilot.yml --limit pve01
ansible-playbook playbooks/configure-opnsense-pilot.yml --limit pve01
```

The target is the Proxmox host. Guest operations delegate to its declared `opnsense_guest`. Check mode reads installed identity, hardware and configuration, builds candidate models in memory, performs native validation, runs OXL in check mode and reports differences. It makes no configuration, trust-file, service or WAN-link writes. It does not prove runtime or internet access; normal runs perform those checks.

The normal workflow backs up the configuration, saves unsupported native settings, merges the owned API policy, loads rules and services, verifies runtime state, and then connects the owned WAN vNIC. It requires the resulting WAN DHCP /24 and default gateway to match the private pilot. An HTTPS request from Proxmox verifies management DNS, routing, NAT and certificate validation. The final report includes WAN address and NTP synchronization status; a running NTP service may need time to select an upstream after WAN first becomes available.

## Managed policy

| Source | Destination | Permitted traffic |
|---|---|---|
| Explicit administrator addresses | Firewall itself | TCP 22/443 and ICMP |
| Management /24 | Firewall itself | TCP/UDP DNS 53 and UDP NTP 123 |
| Explicit update hosts | External destinations | TCP 80/443 |
| Management /24 | Private, link-local and carrier NAT networks | Block after local service allowances |
| Remaining management traffic | Any | Block |
| Unsolicited WAN traffic | Any | Block; normal WAN DHCP and established replies retain vendor handling |

The broad bootstrap management rule and automatic anti-lockout rules are replaced by explicit rules. No WAN management allowance is added. Standard automatic outbound NAT is enabled. Private-address and bogon WAN blocking are removed for this private DHCP pilot; final ISP attachment needs a separate policy review. Initially only management traffic participates because the optional interfaces stay disabled. The separate [HOME pilot entry point](configure-opnsense-home.md) can enable HOME afterward. This playbook then consumes the recorded HOME allocation and preserves its interface, policy, DNS and DHCP configuration; DEV and BMC remain disabled.

Before HOME enrollment, Unbound listens on management and loopback, permits those client networks, forwards to the two pinned system resolvers, and disables WAN DHCP resolver overrides. No additional forwarding rules or recursive fallback are introduced. NTP uses the standard [OPNsense pool](https://docs.opnsense.org/manual/ntpd.html); it binds management and WAN for upstream operation, while firewall policy exposes the service only on management. [Vendor service actions](https://docs.opnsense.org/development/backend/configd.html) apply the saved configuration.

## Backups, conflicts and interrupted runs

Before a configuration transaction, a root-owned mode-0600 `before-*.xml` is kept beneath the mode-0700 `/conf/ansible-pilot` directory. The controller also exports it into a unique private `backups/<guest>-pilot-*/before.xml` directory without displaying credentials or configuration contents. Treat these files as secrets. `/conf/ansible-pilot/state.json` binds the record to the installed seed and tracks pending versus completed service application.

A repeated run with matching configuration and a completed record makes no save, backup, reload or WAN change. It still checks loaded policy, local DNS/time services, WAN addressing and Proxmox HTTPS access. A pending run reapplies services and retains its original pre-change backup before completing verification. If WAN attachment succeeded but connectivity verification failed, repeat after correcting that external dependency; no VM reinstall or disk operation occurs.

Unowned rules, NAT/port forwards, unrelated DNS entries, unowned enabled optional interfaces/DHCP, mismatched MACs, an unlisted controller, missing private backups or conflicting VM hardware cause failure. This workflow matches owned rules by unique description, ACLs by name, and host records by hostname/domain/type, preserving existing IDs and deliberately refuses to overwrite unrelated configuration. It changes no switch ports, physical cables, household router configuration, VM disks or host networking.

## Collection compatibility

The pinned OXL release is tested upstream against OPNsense 26.1.11, while this workflow uses 26.7. API incompatibilities fail the run; the pending transaction and original backup remain available for a corrected rerun. Writes are scoped to named objects; no purge or full configuration import occurs. Individual API modules use `reload: false`, followed by one explicit reload of firewall and Unbound (and Kea when HOME is enrolled). A pending record forces reload on a resumed run even when the API configuration already matches.

References: [OXL firewall rules](https://ansible-opnsense.oxl.app/modules/rule.html), [Unbound general settings](https://ansible-opnsense.oxl.app/modules/unbound_general.html), [OXL 26.1.11](https://github.com/O-X-L/ansible-opnsense/releases/tag/26.1.11).
