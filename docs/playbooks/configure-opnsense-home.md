# Configure the owned HOME network

The `configure-opnsense-home.yml` entry point selects the `home` action of [opnsense_services](configure-opnsense-services.md). It validates the existing VM, enrolled API and ownership records before reconciling HOME addressing, DHCP, Unbound DNS and firewall policy.

```bash
./just playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
./just playbook playbooks/configure-opnsense-home.yml --limit pve01
./just playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
```

Only the operator runs apply. For Dnsmasq, `opnsense_home` contains only `address`, `subnet` and `dhcp_backend: dnsmasq`; the dedicated DHCP role owns lease ranges and reservations. Existing Kea declarations retain `address`, `subnet`, `pool_start`, `pool_end` and `lease_seconds`. Selecting Dnsmasq refuses enabled Kea and never provisions Kea. DHCP must be configured separately before the complete HOME runtime verification can pass. Existing allocation ownership checks intentionally refuse an unapproved network reassignment. Check mode is a read-only preview; it does not issue a DHCP lease or test a client renewal.

This entry point preserves the existing single-range Kea configuration until conversion. After conversion it recognizes the completed owned Dnsmasq service. The [dedicated DHCP role](configure-opnsense-dhcp.md) manages the permanent `home_dhcp` allocation. Do not use this entry point to perform the household migration.
