# Configure permanent HOME DHCP

`opnsense_dhcp` manages DHCP-only Dnsmasq on the enrolled OPNsense HOME interface. Unbound continues serving DNS on port 53; Dnsmasq uses `port=0`. No DHCPv6 or router advertisements are configured. See the [OPNsense Dnsmasq documentation](https://docs.opnsense.org/manual/dnsmasq.html).

`opnsense_home` declares the HOME address/subnet with `dhcp_backend: dnsmasq`; the service role does not need legacy Kea pool fields for this backend. Existing allocation ownership still prevents implicit network reassignment.

`home_dhcp` declares gateway, subnet, primary and standby pools, and reservations. The approved primary pool is `.20–115` plus `.117–134` (114 addresses); standby is `.135–248` (114). The printer owns `.116`. Only primary ranges are activated by this role.

`opnsense_dhcp` requires `interface: opt1`, `domain`, and `lease_seconds` (600–86400). Optional `ranges` restricts the active pool to a nonempty subset of the approved primary allocation. Omit it for normal full-pool operation. Router, DNS and NTP options point to the HOME gateway; domain and search options use the declared domain. DHCP hostnames do not automatically create Unbound records; manage DNS records separately.

## Preview and operate

Run from the repository:

```bash
./just playbook playbooks/configure-opnsense-dhcp.yml --limit opnsense01 --check
```

This reads the firewall and validates its native model without saving or restarting anything. A predicted `changed=1` is a proposed change. Review `apply_ready` and every blocker. Activation requires the intended HOME address, a nonoverlapping WAN, Unbound serving HOME, and competing DHCP services disabled and stopped. Foreign Dnsmasq configuration, custom snippets and ownership drift are refused.

**During migration, use the external transition workflow.** It restricts initial leases and enforces the legacy lease hold. This permanent role deliberately contains no migration clock or old-router orchestration. Do not run the full-pool apply before that hold is satisfied.

Once final network prerequisites and the legacy lease hold are satisfied, the operator runs:

```bash
./just playbook playbooks/configure-opnsense-dhcp.yml --limit opnsense01
./just playbook playbooks/verify-opnsense-dhcp.yml --limit opnsense01
./just playbook playbooks/configure-opnsense-dhcp.yml --limit opnsense01 --check
```

Verification checks saved intent, rendered configuration, daemon and sockets, HOME address, Unbound and lease boundaries. The repeat preview should converge without proposed changes. Existing HOME and startup workflows recognize the completed owned Dnsmasq service and do not re-enable Kea.

The helper uses pinned root SSH and OPNsense's native validated model in one locked configuration save. Stable row IDs and a protected `/conf/ansible-dhcp/state.json` record establish ownership. It backs up the previous configuration locally, records pending work before saving, and marks completion only after runtime verification. It never restores a backup automatically. A failed operation requires inspection before retrying the same desired intent; do not delete ownership records to bypass drift checks.

## Client acceptance

After the operator activates the service, renew a controlled HOME client and inspect its address, DHCP server, router, DNS and domain options. Confirm public DNS and internet access, printer `.116`, and Wi-Fi operation. Test the permanent HOME WireGuard profile from Wi-Fi and confirm ordinary clients cannot initiate MGMT access. Read-only configuration verification cannot prove these client paths.

## Local tests

```bash
./just validate
```

See [isolated packet testing](../../tests/integration/README.md) for real Dnsmasq packet tests. Native model previews are tested against the enrolled firewall; actual OPNsense service activation and client acceptance remain operator-run checks.
