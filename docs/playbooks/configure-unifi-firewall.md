# Manage the UniFi guest firewall

The guest firewall is a declarative native nftables policy. Ansible derives it from the existing `unifi_vm_allocation` gateway, tunnel and recovery addresses; no new inventory fields are needed.

For an existing guest using the legacy Python bootstrap helper:

```sh
ansible-playbook playbooks/configure-unifi-firewall.yml --limit unifi01 --check
ansible-playbook playbooks/configure-unifi-firewall.yml --limit unifi01
ansible-playbook playbooks/verify-unifi-vm.yml playbooks/verify-unifi-config-ready.yml --limit 'pve01,unifi01'
```

Configuration first checks the guest identity and requires the legacy live rules to match the inventory policy. It validates the replacement with nftables, writes `/etc/home-automation/unifi-policy.nft.json` and the managed systemd units, then atomically replaces only `inet home_unifi`. It verifies the result independently and removes the obsolete guest Python helper. Failed configuration restores backed-up files and the prior owned table. UniFi is not restarted and the VM is not rebooted. Check mode previews changes without writing files or loading rules.

`configure-unifi-host.yml` also performs firewall configuration. Subsequent configuration repairs managed policy drift. Verification remains read-only: it checks the saved policy, kernel rules, permissions, and effective systemd startup commands. Whitespace, key ordering and kernel rule handles do not affect policy equality; extra rules, changed verdicts and reordered rules do. The verification code is supplied by the controller each time, rather than trusting a guest helper to report its own correctness.

The boot service loads the saved native policy before networking. Both UniFi services require that service and validate and reapply the saved policy before starting. An invalid policy blocks startup. The distribution's global-flush nftables service stays masked, and unrelated tables are preserved. Future cloud-init seeds use the same native policy and startup templates. Existing seed bytes, SSH keys and completed Proxmox VM intent are preserved.

The traffic permissions remain those documented in the [UniFi runbook](unifi-controller.md#configuration-isolation). This migration does not adopt access points or broaden network access. To change the allowed traffic later, review the policy generator and independent traffic acceptance tests, then run configuration followed by verification.
