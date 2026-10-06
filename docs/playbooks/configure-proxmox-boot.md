# Configure firewall startup and controlled host reboot

`playbooks/configure-proxmox-boot.yml` enables automatic startup for the installed OPNsense VM through `community.proxmox.proxmox_kvm`. An optional `ansible.builtin.reboot` operation boots an updated Proxmox kernel, then verifies the recovered firewall and management services. `configure-proxmox-firewall-startup.yml` selects startup configuration without rebooting; `reboot-proxmox-host.yml` selects required maintenance reboot handling. Both invoke `proxmox_host` with the required `proxmox_host_options.task_action` set to `startup` or `reboot`, with no fallback action.

## Prerequisites

- Complete the OPNsense installation, API enrollment and connected management pilot. Its protected installation record must say `complete`, its DVD must be ejected, and the guest must be running with the expected MACs, bridges, VLANs and ownership marker.
- Configure Proxmox repositories with [configure-proxmox-host.yml](configure-proxmox-host.md). Complete package work before maintenance; unfinished dpkg transactions and package holds stop the workflow.
- Run from a controller with direct management access to Proxmox and OPNsense, trusted SSH keys, and enrolled Proxmox API credentials and CA. A directly connected recovery Ethernet path remains usable while the guest gateway is down. Keep VGA or iDRAC console access available for boot recovery.
- Select `opnsense_vm.onboot: true` in private inventory. Keep `onboot: false` during initial installation; this maintenance workflow changes the installed VM's setting after bootstrap. Existing installation and pilot playbooks accept enabled startup on a completed installation.

This workflow supports the standalone Proxmox 9 / Debian 13 host with the installed GRUB boot layout and only the owned firewall VM. Additional guests, HA membership, active Proxmox tasks, pinned or one-time GRUB selections, and managed ESP boot layouts require extending the maintenance workflow first. Guest startup service `pve-guests` must already be enabled and active. The preflight also verifies that GRUB selects the newest installed Proxmox kernel and that its kernel image and initramfs exist.

## Configure automatic startup

```bash
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01
```

The first apply saves the exact previous VM configuration into a fresh mode-0700 `/root/ansible-firewall-boot-*` directory with a mode-0600 `vm-config.json`. It changes only `onboot` to true, using the configuration digest to reject concurrent edits. Startup order remains `order=1,up=30,down=120`: start the firewall before higher-order guests, wait 30 seconds before starting the next guest, and allow 120 seconds for shutdown. Proxmox uses reverse startup order for shutdown. The playbook verifies all hardware is preserved and the firewall remains running. [Proxmox startup and shutdown ordering](https://pve.proxmox.com/pve-docs/chapter-qm.html#qm_startup_and_shutdown).

Check mode performs read-only host/API/firewall/network checks and reports the startup change without creating backups or changing the VM. The pinned KVM module does not support check mode, so the workflow supplies an explicit preview based on the verified current setting. A repeated startup-only apply reports no changes after convergence.

## Explicitly request a required reboot

After host updates, preview and apply startup plus a required reboot in the same workflow:

```bash
ansible-playbook playbooks/reboot-proxmox-host.yml --limit pve01 --check
ansible-playbook playbooks/reboot-proxmox-host.yml --limit pve01
```

`reboot-proxmox-host.yml` invokes the `proxmox_host` role with `task_action: reboot`. The reboot task runs only when a newer installed kernel or the Debian reboot marker indicates it is required. Once the running kernel matches and the marker is clear, repeating the command skips rebooting. There is no force-reboot option.

The host reboot follows the normal Proxmox service shutdown/startup sequence, including its guest ACPI shutdown timeout. Proxmox can force a guest off if it exceeds that timeout; the playbook sends no separate forced VM stop. The firewall gateway, DNS and management services are temporarily unavailable while the host and guest restart; the controller must retain its direct management path.

Ansible waits for the host's boot ID to change and its Proxmox/guest startup services to become active, with a 900-second timeout per reboot verification/test-command stage and a 30-second post-reboot delay. API and guest service checks have separate bounded retries. [Ansible reboot behavior](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/reboot_module.html).

## Verification and recovery

Before maintenance, the playbook verifies saved firewall policy and loaded rules, DNS records/listeners, the running time service and the intended pilot WAN lease/gateway. It also checks verified outbound HTTPS from Proxmox, exercising management DNS and NAT.

After normal execution, it verifies unchanged host network/storage hashes, Debian sources, repositories, default route and VM hardware, plus the running firewall and recovered management policy and outbound connectivity. A performed reboot must activate the newest installed kernel, clear the reboot requirement and change the boot ID. The report includes kernel, reboot status, WAN address and NTP synchronization; NTP may take additional time to synchronize after boot.

If a reboot or recovery check fails, inspect the console and preserve the reported pre-change VM backup. The workflow does not roll back startup or force-stop the guest. Correct boot or service failures through the appropriate Ansible workflow before retrying. A rerun after a successful kernel boot skips a second reboot and repeats the health checks; an unreachable host still needs console recovery. The first actual reboot is the test of automatic guest startup and shutdown behavior.

The maintenance preflight also accepts the completed owned Fedora VM 200 after checking its protected allocation and exact hardware. Startup verification permits it to be running. Before an explicit host reboot, stop it with `stop-fedora-dev-vm.yml`; it remains stopped after host boot because DEV has manual startup policy. The preflight also accepts completed owned UniFi VM 110, with its exact allocation and automatic startup order 2 verified through the controller guard. Incomplete controller installations and other additional guests still require a separate maintenance workflow. Verify the isolated controller service again after host boot; its startup delay is not an application health check.
