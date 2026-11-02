# Configure OPNsense services

The `opnsense_services` role reconciles management DNS/NTP, firewall policy and owned HOME services. Declare `opnsense_services` and `opnsense_home` on the firewall inventory host. The existing VM and its WAN link must already match inventory; this role does not change VM hardware.

```bash
./just playbook playbooks/configure-opnsense-management.yml --limit pve01 --check
./just playbook playbooks/configure-opnsense-management.yml --limit pve01
./just playbook playbooks/configure-opnsense-management.yml --limit pve01 --check
```

Only the operator runs the apply command. Check mode validates ownership and previews vendor models without saving device configuration. Management configuration preserves the enrolled HOME network. Use [HOME configuration](configure-opnsense-home.md) to reconcile its allocation explicitly. The generic `configure-opnsense-services.yml` requires `opnsense_services_options.task_action` (`management` or `home`).

`wan_gateway` is an optional expected DHCP gateway. Optional Boolean `wan_block_private` and `wan_block_bogons` explicitly select WAN filtering; omission preserves the existing setting. Private upstream networks are not assumed. DNS servers, NTP servers, administration sources and update sources remain explicit inventory declarations.

Existing `/conf/ansible-pilot` records, `home_pilot` payload fields and rule identity salts are retained for compatibility with enrolled devices. Renaming them would lose ownership continuity. Temporary Fortinet reservations, private-WAN Wi-Fi access and WAN attachment sequencing are maintained outside this repository.

Before conversion this role preserves the enrolled single-pool Kea configuration. After conversion it recognizes and verifies the completed owned Dnsmasq service without re-enabling Kea. The [dedicated DHCP role](configure-opnsense-dhcp.md) consumes `home_dhcp` and manages permanent split pools.
