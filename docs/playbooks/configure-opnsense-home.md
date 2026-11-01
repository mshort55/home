# Configure the owned HOME network

The `configure-opnsense-home.yml` entry point selects the `home` action of [opnsense_services](configure-opnsense-services.md). It validates the existing VM, enrolled API and ownership records before reconciling HOME addressing, DHCP, Unbound DNS and firewall policy.

```bash
./just playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
./just playbook playbooks/configure-opnsense-home.yml --limit pve01
./just playbook playbooks/configure-opnsense-home.yml --limit pve01 --check
```

Only the operator runs apply. The `opnsense_home` inventory dictionary currently requires `address`, `subnet`, `pool_start`, `pool_end` and `lease_seconds`. Existing allocation ownership checks intentionally refuse an unapproved network reassignment. Check mode is a read-only preview; it does not issue a DHCP lease or test a client renewal.

This entry point still manages the existing single-range Kea configuration. Dnsmasq support for the permanent `home_dhcp` allocation is a separate pending implementation. Do not use this entry point to perform the household migration.
