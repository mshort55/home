# Playbook entry points and role actions

Entry-point playbooks map inventory groups to roles, execution settings and explicit role parameters. They invoke no secondary playbooks. Named entry points supply a `task_action` inside `<role_name>_options`; generic entry points require that dictionary from inventory or extra variables. No role has a default action.

Role argument schemas validate the action and typed options before dispatch. The selected action contract then checks its required inputs before any device access or backup. Role defaults supply optional settings; action parameters remain private. See the [role architecture and complete file layout](../roles.md).

## Entry-point mapping

| Entry point | Inventory group | Role | Action |
|---|---|---|---|
| [apply-idrac-network.yml](../../playbooks/apply-idrac-network.yml) | `idracs` | [idrac_network](../../roles/idrac_network/tasks/main.yml) | `apply` |
| [backup-fortigate.yml](../../playbooks/backup-fortigate.yml) | `fortigates` | [fortigate_backup](../../roles/fortigate_backup/tasks/main.yml) | `backup` |
| [backup-idrac.yml](../../playbooks/backup-idrac.yml) | `idracs` | [idrac_backup](../../roles/idrac_backup/tasks/main.yml) | `export` |
| [backup-switch.yml](../../playbooks/backup-switch.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `backup` |
| [boot-idrac-iso.yml](../../playbooks/boot-idrac-iso.yml) | `idracs` | [idrac_boot](../../roles/idrac_boot/tasks/main.yml) | `boot` |
| [configure-idrac-network.yml](../../playbooks/configure-idrac-network.yml) | `idracs` | [idrac_network](../../roles/idrac_network/tasks/main.yml) | Required explicit `task_action` |
| [configure-opnsense-api.yml](../../playbooks/configure-opnsense-api.yml) | `opnsense_hosts` | [opnsense_api](../../roles/opnsense_api/tasks/main.yml) | `enroll` |
| [configure-opnsense-home.yml](../../playbooks/configure-opnsense-home.yml) | `proxmox_hosts` | [opnsense_pilot](../../roles/opnsense_pilot/tasks/main.yml) | `home` |
| [configure-opnsense-management.yml](../../playbooks/configure-opnsense-management.yml) | `proxmox_hosts` | [opnsense_pilot](../../roles/opnsense_pilot/tasks/main.yml) | `management` |
| [configure-opnsense-pilot.yml](../../playbooks/configure-opnsense-pilot.yml) | `proxmox_hosts` | [opnsense_pilot](../../roles/opnsense_pilot/tasks/main.yml) | Required explicit `task_action` |
| [configure-proxmox-api.yml](../../playbooks/configure-proxmox-api.yml) | `proxmox_hosts` | [proxmox_api](../../roles/proxmox_api/tasks/main.yml) | `enroll` |
| [configure-proxmox-boot.yml](../../playbooks/configure-proxmox-boot.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | Required explicit `task_action` |
| [configure-proxmox-bridges.yml](../../playbooks/configure-proxmox-bridges.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | `bridges` |
| [configure-proxmox-firewall-startup.yml](../../playbooks/configure-proxmox-firewall-startup.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | `startup` |
| [configure-proxmox-host.yml](../../playbooks/configure-proxmox-host.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | Required explicit `task_action` |
| [configure-proxmox-repositories.yml](../../playbooks/configure-proxmox-repositories.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | `repositories` |
| [configure-switch-all-ports.yml](../../playbooks/configure-switch-all-ports.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `ports` |
| [configure-switch-home-pilot-port.yml](../../playbooks/configure-switch-home-pilot-port.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `ports` |
| [configure-switch-idrac-port.yml](../../playbooks/configure-switch-idrac-port.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `ports` |
| [configure-switch-management.yml](../../playbooks/configure-switch-management.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `management` |
| [configure-switch-ports.yml](../../playbooks/configure-switch-ports.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | Required explicit `task_action` |
| [configure-switch-recovery-ports.yml](../../playbooks/configure-switch-recovery-ports.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `ports` |
| [configure-switch-server-ports.yml](../../playbooks/configure-switch-server-ports.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `ports` |
| [configure-opnsense-wireguard.yml](../../playbooks/configure-opnsense-wireguard.yml) | `opnsense_hosts` | [opnsense_wireguard](../../roles/opnsense_wireguard/tasks/main.yml) | `configure` |
| [configure-switch-gateway.yml](../../playbooks/configure-switch-gateway.yml) | `cisco_switches` | [cisco_switch](../../roles/cisco_switch/tasks/main.yml) | `gateway` |
| [prepare-wireguard-client.yml](../../playbooks/prepare-wireguard-client.yml) | `opnsense_hosts` | [opnsense_wireguard](../../roles/opnsense_wireguard/tasks/main.yml) | `prepare` |
| [verify-opnsense-wireguard.yml](../../playbooks/verify-opnsense-wireguard.yml) | `opnsense_hosts` | [opnsense_wireguard](../../roles/opnsense_wireguard/tasks/main.yml) | `verify` |
| [create-opnsense-vm.yml](../../playbooks/create-opnsense-vm.yml) | `proxmox_hosts` | [opnsense_vm](../../roles/opnsense_vm/tasks/main.yml) | `create` |
| [eject-idrac-iso.yml](../../playbooks/eject-idrac-iso.yml) | `idracs` | [idrac_iso](../../roles/idrac_iso/tasks/main.yml) | `eject` |
| [install-opnsense.yml](../../playbooks/install-opnsense.yml) | `proxmox_hosts` | [opnsense_install](../../roles/opnsense_install/tasks/main.yml) | `install` |
| [manage-idrac-iso-boot.yml](../../playbooks/manage-idrac-iso-boot.yml) | `idracs` | [idrac_boot](../../roles/idrac_boot/tasks/main.yml) | Required explicit `task_action` |
| [manage-idrac-iso.yml](../../playbooks/manage-idrac-iso.yml) | `idracs` | [idrac_iso](../../roles/idrac_iso/tasks/main.yml) | Required explicit `task_action` |
| [manage-opnsense-vm.yml](../../playbooks/manage-opnsense-vm.yml) | `proxmox_hosts` | [opnsense_vm](../../roles/opnsense_vm/tasks/main.yml) | Required explicit `task_action` |
| [mount-idrac-iso.yml](../../playbooks/mount-idrac-iso.yml) | `idracs` | [idrac_iso](../../roles/idrac_iso/tasks/main.yml) | `mount` |
| [prepare-opnsense-bootstrap.yml](../../playbooks/prepare-opnsense-bootstrap.yml) | `proxmox_hosts` | [opnsense_media](../../roles/opnsense_media/tasks/main.yml) | `bootstrap` |
| [prepare-opnsense-iso.yml](../../playbooks/prepare-opnsense-iso.yml) | `proxmox_hosts` | [opnsense_media](../../roles/opnsense_media/tasks/main.yml) | `download` |
| [prepare-proxmox-iso.yml](../../playbooks/prepare-proxmox-iso.yml) | `proxmox_hosts` | [proxmox_installer](../../roles/proxmox_installer/tasks/main.yml) | `prepare` |
| [preview-idrac-network.yml](../../playbooks/preview-idrac-network.yml) | `idracs` | [idrac_network](../../roles/idrac_network/tasks/main.yml) | `preview` |
| [reboot-proxmox-host.yml](../../playbooks/reboot-proxmox-host.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | `reboot` |
| [set-idrac-uefi.yml](../../playbooks/set-idrac-uefi.yml) | `idracs` | [idrac_boot](../../roles/idrac_boot/tasks/main.yml) | `uefi` |
| [snapshot-idrac.yml](../../playbooks/snapshot-idrac.yml) | `idracs` | [idrac_snapshot](../../roles/idrac_snapshot/tasks/main.yml) | `snapshot` |
| [status-idrac-iso.yml](../../playbooks/status-idrac-iso.yml) | `idracs` | [idrac_iso](../../roles/idrac_iso/tasks/main.yml) | `status` |
| [status-idrac-network.yml](../../playbooks/status-idrac-network.yml) | `idracs` | [idrac_network](../../roles/idrac_network/tasks/main.yml) | `status` |
| [update-proxmox-host.yml](../../playbooks/update-proxmox-host.yml) | `proxmox_hosts` | [proxmox_host](../../roles/proxmox_host/tasks/main.yml) | `upgrade` |
| [verify-idrac-iso-boot.yml](../../playbooks/verify-idrac-iso-boot.yml) | `idracs` | [idrac_boot](../../roles/idrac_boot/tasks/main.yml) | `verify` |
| [verify-idrac-network.yml](../../playbooks/verify-idrac-network.yml) | `idracs` | [idrac_network](../../roles/idrac_network/tasks/main.yml) | `verify` |
| [verify-opnsense-vm.yml](../../playbooks/verify-opnsense-vm.yml) | `proxmox_hosts` | [opnsense_vm](../../roles/opnsense_vm/tasks/main.yml) | `verify` |

## Custom action selection

Named entry points run directly, retaining `--limit` and supported `--check` previews:

```bash
ansible-playbook playbooks/configure-proxmox-repositories.yml --limit pve01 --check
ansible-playbook playbooks/update-proxmox-host.yml --limit pve01 --check
ansible-playbook playbooks/configure-switch-home-pilot-port.yml --check
ansible-playbook playbooks/verify-opnsense-vm.yml --limit pve01
```

Generic entry points require the role-scoped action dictionary. Use JSON or YAML for typed parameters:

```bash
ansible-playbook playbooks/configure-switch-ports.yml --check \
  -e '{"cisco_switch_options":{"task_action":"ports"},"switch_port_roles":["server_mgmt","pilot_wan"]}'
ansible-playbook playbooks/configure-proxmox-host.yml --limit pve01 --check \
  -e '{"proxmox_host_options":{"task_action":"repositories"}}'
```

The standard field is `task_action`. Its containing dictionary identifies the role, so selecting a pilot action cannot override the VM verification action or a separate backup role. Actions within one role share modular task files rather than recursively invoking that same role. Extra variables retain normal Ansible precedence; an explicit dictionary override must pass the selected contract.

The previous top-level action flags (`proxmox_host_upgrade`, `proxmox_boot_reboot`, `idrac_iso_operation`, `idrac_iso_boot_operation`, `idrac_network_operation`, `opnsense_verify_only` and `opnsense_home_requested`) no longer select operations. Use named entry points or the role-scoped `task_action` instead. `switch_port_roles` remains the required scope parameter for the switch `ports` action; `opnsense_verify_wan_state` remains an optional Boolean comparison setting, defaulting to true.

## Role action choices

| Parameter dictionary | Allowed `task_action` values |
|---|---|
| `cisco_switch_options` | `backup`, `management`, `ports`, `gateway` |
| `community_api_options` | `load`, `prepare` |
| `fortigate_backup_options` | `backup` |
| `idrac_backup_options` | `export` |
| `idrac_boot_options` | `boot`, `verify`, `uefi` |
| `idrac_iso_options` | `mount`, `eject`, `status` |
| `idrac_network_options` | `preview`, `apply`, `status`, `verify` |
| `idrac_snapshot_options` | `snapshot` |
| `opnsense_api_options` | `enroll` |
| `opnsense_install_options` | `install` |
| `opnsense_media_options` | `download`, `bootstrap` |
| `opnsense_pilot_options` | `management`, `home` |
| `opnsense_wireguard_options` | `prepare`, `configure`, `verify` |
| `opnsense_vm_options` | `describe`, `create`, `verify` |
| `proxmox_api_options` | `enroll` |
| `proxmox_host_options` | `repositories`, `upgrade`, `startup`, `reboot`, `bridges` |
| `proxmox_installer_options` | `prepare` |

## Inputs and execution environment

Keep addresses, hardware and VLAN mappings, desired state and guest configuration in inventory. Named switch entries select recovery, server, HOME, iDRAC or all inventory roles. The management pilot action preserves a recorded HOME allocation; the HOME action enrolls or reconciles it.

ISO mounting, booting and verification retain the selected image inputs. Original boot records and accepted network task paths must be supplied explicitly:

```bash
ansible-playbook playbooks/verify-idrac-iso-boot.yml --limit idrac01 \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml \
  -e 'idrac_iso_boot_record={{ inventory_dir }}/backups/<boot-record-directory>'
ansible-playbook playbooks/status-idrac-network.yml --limit idrac01 \
  -e idrac_network_task_path=/redfish/v1/TaskService/Tasks/JID_example
ansible-playbook playbooks/verify-idrac-network.yml --limit idrac01 \
  -e idrac_network_task_path=/redfish/v1/TaskService/Tasks/JID_example
```

Network status/verification are read-only operations and retain rejection of check mode. Preview submits a vendor validation job; it is not a read-only status operation. Network apply still requires Boolean `idrac_network_recovery_ready: true` after staging physical recovery. DHCP rollback retains `idrac_network_mode=dhcp` as an input, independent of action selection. No role sets recovery readiness or manual WAN/NIC-assignment confirmation automatically.

With a local ISO source, media operations run from the native Mac. ISO status disables hostname edits and needs no sudo password; the trusted hostname must already resolve. Mount and eject retain `--ask-become-pass` when hostname preparation requires sudo. VM verification checks resources; guest service verification uses the pilot workflows. Package updates and required host reboot handling remain separate named entry points.
