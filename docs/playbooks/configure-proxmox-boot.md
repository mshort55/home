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

The pilot collection guard preserves completed WireGuard, private-WAN Wi-Fi, DEV/BMC and UniFi policies. UniFi's version-1 `/conf/ansible-unifi/state.json` records the allocation rather than rule UUIDs. The guard requires protected ownership/backup artifacts, the matching installation seed, a completed transaction and matching MGMT/domain/WireGuard identities. It reconstructs the same four bounded rules and DNS host used by the UniFi network adapter, requires one exact match for every managed field, and preserves each existing UUID and vendor fields. A description prefix alone grants no ownership. Missing, duplicate, drifted or unrelated entries still fail; unrelated-entry errors now identify the description/identity and UUID. `verify-opnsense-unifi.yml` separately verifies loaded controller rules and DNS.

After normal execution, it verifies unchanged host network/storage hashes, Debian sources, repositories, default route and VM hardware, plus the running firewall and recovered management policy and outbound connectivity. A performed reboot must activate the newest installed kernel, clear the reboot requirement and change the boot ID. The report includes kernel, reboot status, WAN address and NTP synchronization; NTP may take additional time to synchronize after boot.

If a reboot or recovery check fails, inspect the console and preserve the reported pre-change VM backup. The workflow does not roll back startup or force-stop the guest. Correct boot or service failures through the appropriate Ansible workflow before retrying. A rerun after a successful kernel boot skips a second reboot and repeats the health checks; an unreachable host still needs console recovery. The first actual reboot is the test of automatic guest startup and shutdown behavior.

The maintenance preflight also accepts the completed owned Fedora VM 200 after checking its protected allocation and exact hardware. Startup verification permits it to be running. Before an explicit host reboot, stop it with `stop-fedora-dev-vm.yml`; it remains stopped after host boot because DEV has manual startup policy. The preflight also accepts completed owned UniFi VM 110, with its exact allocation and automatic startup order 2 verified through the controller guard. Incomplete controller installations and other additional guests still require a separate maintenance workflow. Verify the isolated controller service again after host boot; its startup delay is not an application health check.

## Isolated startup and recovery rehearsal

Perform this manually during Phase 3, before household gateway cutover or AP migration. Retain trusted SSH access, VGA/iDRAC console and both wired recovery ports. Keep the staged household WLAN disabled and production ports unchanged. Use private inventory and existing protected artifacts; enter the Vault password locally when prompted.

First inspect VM 200; invoke its stop playbook only if it is running. Then pass startup check/apply/verification and the reboot check:

```bash
ssh root@10.55.10.10 'qm status 200'
# Only if running:
ansible-playbook playbooks/stop-fedora-dev-vm.yml --limit pve01
ssh root@10.55.10.10 'qm status 200'
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01 --check
ansible-playbook playbooks/reboot-proxmox-host.yml --limit pve01 --check
```

Stop on a failed gate. Startup apply verifies the current configuration even when `onboot` is already enabled. Review `reboot_needed`: when false, the reboot playbook's apply performs checks without rebooting. An actual rehearsal needs a separately deliberate operator reboot.

In native macOS, turn off WireGuard and Wi-Fi, connect Ethernet `en8` to recovery port 4, and set `10.55.10.250/24` with no router or DNS. Confirm direct Proxmox/switch access and console availability. Record the current host boot ID, then explicitly initiate the rehearsal reboot:

```bash
ssh root@10.55.10.10 'cat /proc/sys/kernel/random/boot_id'
ssh root@10.55.10.10 'systemctl reboot'
```

Wait through the console for recovery. Confirm a changed boot ID, inspect this boot's `pve-guests` journal for VM 100 starting before 110, and require VM 200 still stopped:

```bash
ssh root@10.55.10.10 'cat /proc/sys/kernel/random/boot_id; journalctl -b -u pve-guests --no-pager; qm status 100; qm status 110; qm status 200'
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01 --check
ansible-playbook playbooks/verify-opnsense-unifi.yml --limit opnsense01
ansible-playbook playbooks/verify-unifi-vm.yml --limit pve01
ansible-playbook playbooks/verify-unifi-host.yml --limit unifi01
ansible-playbook playbooks/verify-unifi-site.yml --limit unifi01
```

Use console evidence if the journal lacks individual guest-start events. Settings `order=1`/`order=2` alone do not establish observed startup order. Verify UniFi application/isolation readiness after boot; a startup delay is not a health check.

With direct MGMT established, gracefully shut down only OPNsense:

```bash
ssh root@10.55.10.10 'qm shutdown 100 --timeout 120'
ssh root@10.55.10.10 'qm status 100'
```

Require `stopped`; investigate a timeout through the console without forcing the VM off. In native macOS Terminal, verify Proxmox SSH/UI and switch SSH while OPNsense is stopped:

```bash
nc -vz -G 3 10.55.10.10 22
nc -vz -G 3 10.55.10.10 8006
nc -vz -G 3 10.55.10.2 22
```

Move Ethernet to recovery port 5, set `10.55.40.250/24` with no router/DNS, and verify native `ping -c 4 10.55.40.10`, TCP 443 and trusted iDRAC web/console access. Return to port 4 and `10.55.10.250/24` before restoring OPNsense:

```bash
ssh root@10.55.10.10 'qm start 100'
ansible-playbook playbooks/configure-proxmox-firewall-startup.yml --limit pve01 --check
ansible-playbook playbooks/verify-opnsense-wireguard.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-wireguard-wifi.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-bmc.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-dev.yml --limit opnsense01
```

Test physical port 8 with Ethernet DHCP on the HOME pilot: tunnel off denies management, only the wired `home-admin` tunnel permits approved services, then tunnel off denies again. Repeat on Wi-Fi `en0` with Ethernet disconnected and only `home-admin-wifi` active. Use native macOS Terminal/browser for all positive/negative acceptance; container ICMP is insufficient. Follow the [WireGuard acceptance tests](configure-opnsense-wireguard.md#mac-import-and-acceptance), [Wi-Fi transport runbook](configure-opnsense-wireguard-wifi.md) and private DEV/BMC plan with actual inventory addresses. Never activate both tunnel profiles together.

Finally restart Fedora through its existing workflow and verify recovered infrastructure:

```bash
ansible-playbook playbooks/start-fedora-dev-vm.yml --limit pve01
ansible-playbook playbooks/verify-fedora-dev-vm.yml --limit pve01
ansible-playbook playbooks/verify-fedora-dev-host.yml --limit dev01
ansible-playbook playbooks/verify-fedora-dev-connectivity.yml --limit dev01
ansible-playbook playbooks/verify-opnsense-unifi.yml --limit opnsense01
ansible-playbook playbooks/verify-unifi-vm.yml --limit pve01
ansible-playbook playbooks/verify-unifi-host.yml --limit unifi01
ansible-playbook playbooks/verify-unifi-site.yml --limit unifi01
```

Record native recovery/isolation results and observed boot order before accepting the Phase 3 gate. Household gateway cutover and AP adoption remain separate milestones.
