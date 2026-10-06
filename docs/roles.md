# Role architecture

Permanent lab access uses `opnsense_lab` actions `configure`, `verify`, `disable`, and `verify_disabled`, with explicit `zone: bmc` or `dev`. `fedora_dev` provides `prepare`, `create`, `verify`, `start`, and `stop`; `fedora_host` provides `configure`, `verify`, and `connectivity`. See [lab access](playbooks/configure-opnsense-lab.md) and [Fedora provisioning](playbooks/fedora-dev.md). Client preparation queries completed protected zone records separately from immutable WireGuard key allocation.

`playbooks/` contains inventory orchestration only. Each entry point maps a host group and execution settings to a role and supplies an explicit action for a named workflow. Implementations, reusable tasks, optional defaults and formal contracts live under `roles/`. No entry point imports another playbook.

`ansible.cfg` sets `roles_path = ./roles` and `private_role_vars = True`. Dynamic role composition also uses `public: false`. Role parameters and defaults do not become general play variables. Ansible registered variables and facts remain host-scoped; documented workflow outputs below are deliberately shared between collaborating roles.

## Action contract

Every role accepts `<role_name>_options`, a required dictionary containing the standard required string field `task_action`. Allowed values match public action filenames under that role's `tasks/` directory. There is no default action. Prefixing the parameter dictionary with the role name keeps one role's action independent of another role's action, including when extra variables select a generic workflow.

```yaml
roles:
  - role: proxmox_host
    proxmox_host_options:
      task_action: repositories
```

Dynamic composition selects a different role independently:

```yaml
- name: Verify firewall VM resources before guest configuration
  ansible.builtin.include_role:
    name: opnsense_vm
    public: false
  vars:
    opnsense_vm_options:
      task_action: verify
    opnsense_verify_wan_state: false
```

Ansible automatically validates `meta/argument_specs.yml`'s `main` contract at role entry. `tasks/main.yml` then validates the selected action's contract and dispatches with `ansible.builtin.include_tasks: "{{ <role_name>_options.task_action }}.yml"`. Contracts declare choices, required inputs, types and optional defaults. Detailed task assertions retain address, identity, exact hardware, VLAN, protected-file and recovery checks. Optional values are in `defaults/main.yml`; no action control is defaulted there. Derived script payloads and module authentication defaults remain scoped to the action's task block.

Action files compose dependencies and include reusable `_*.yml` task modules. Same-role composition uses task includes rather than recursive role calls. For example, switch management/ports include the same backup implementation, and bootstrap media includes the download implementation. Independent services use `include_role`, such as iDRAC network apply calling `idrac_backup` and OPNsense install/pilot calling `opnsense_vm` verification. These dependencies execute only after the owning action contract passes.

`ansible.builtin.meta: end_role` returns from completed status/preview paths without terminating unrelated roles or post-tasks on the host. Local-only media/installer and Redfish entry points explicitly set `ansible_connection: local` and the executing controller Python interpreter, so inventory SSH settings do not redirect controller tasks to Proxmox. Switch plays retain enable privilege; guest and host work retain their existing SSH identities, TLS/CA validation and scoped community modules.

## Roles and contracts

| Role | Public actions | Optional defaults | Argument contracts |
|---|---|---|---|
| [cisco_switch](../roles/cisco_switch/tasks/main.yml) | `backup`, `management`, `ports`, `gateway` | [defaults](../roles/cisco_switch/defaults/main.yml) | [schema](../roles/cisco_switch/meta/argument_specs.yml) |
| [community_api](../roles/community_api/tasks/main.yml) | `load`, `prepare` | [defaults](../roles/community_api/defaults/main.yml) | [schema](../roles/community_api/meta/argument_specs.yml) |
| [fortigate_backup](../roles/fortigate_backup/tasks/main.yml) | `backup` | [defaults](../roles/fortigate_backup/defaults/main.yml) | [schema](../roles/fortigate_backup/meta/argument_specs.yml) |
| [fortigate_controller](../roles/fortigate_controller/tasks/main.yml) | `prepare`, `verify` | [defaults](../roles/fortigate_controller/defaults/main.yml) | [schema](../roles/fortigate_controller/meta/argument_specs.yml) |
| [idrac_backup](../roles/idrac_backup/tasks/main.yml) | `export` | [defaults](../roles/idrac_backup/defaults/main.yml) | [schema](../roles/idrac_backup/meta/argument_specs.yml) |
| [idrac_boot](../roles/idrac_boot/tasks/main.yml) | `boot`, `verify`, `uefi` | [defaults](../roles/idrac_boot/defaults/main.yml) | [schema](../roles/idrac_boot/meta/argument_specs.yml) |
| [idrac_iso](../roles/idrac_iso/tasks/main.yml) | `mount`, `eject`, `status` | [defaults](../roles/idrac_iso/defaults/main.yml) | [schema](../roles/idrac_iso/meta/argument_specs.yml) |
| [idrac_network](../roles/idrac_network/tasks/main.yml) | `preview`, `apply`, `status`, `verify` | [defaults](../roles/idrac_network/defaults/main.yml) | [schema](../roles/idrac_network/meta/argument_specs.yml) |
| [idrac_snapshot](../roles/idrac_snapshot/tasks/main.yml) | `snapshot` | [defaults](../roles/idrac_snapshot/defaults/main.yml) | [schema](../roles/idrac_snapshot/meta/argument_specs.yml) |
| [opnsense_api](../roles/opnsense_api/tasks/main.yml) | `enroll` | [defaults](../roles/opnsense_api/defaults/main.yml) | [schema](../roles/opnsense_api/meta/argument_specs.yml) |
| [opnsense_install](../roles/opnsense_install/tasks/main.yml) | `install` | [defaults](../roles/opnsense_install/defaults/main.yml) | [schema](../roles/opnsense_install/meta/argument_specs.yml) |
| [opnsense_media](../roles/opnsense_media/tasks/main.yml) | `download`, `bootstrap` | [defaults](../roles/opnsense_media/defaults/main.yml) | [schema](../roles/opnsense_media/meta/argument_specs.yml) |
| [opnsense_pilot](../roles/opnsense_pilot/tasks/main.yml) | `management`, `home` | [defaults](../roles/opnsense_pilot/defaults/main.yml) | [schema](../roles/opnsense_pilot/meta/argument_specs.yml) |
| [opnsense_wireguard](../roles/opnsense_wireguard/tasks/main.yml) | `prepare`, `configure`, `verify` | [defaults](../roles/opnsense_wireguard/defaults/main.yml) | [schema](../roles/opnsense_wireguard/meta/argument_specs.yml) |
| [opnsense_vm](../roles/opnsense_vm/tasks/main.yml) | `describe`, `create`, `verify` | [defaults](../roles/opnsense_vm/defaults/main.yml) | [schema](../roles/opnsense_vm/meta/argument_specs.yml) |
| [proxmox_api](../roles/proxmox_api/tasks/main.yml) | `enroll` | [defaults](../roles/proxmox_api/defaults/main.yml) | [schema](../roles/proxmox_api/meta/argument_specs.yml) |
| [proxmox_host](../roles/proxmox_host/tasks/main.yml) | `repositories`, `upgrade`, `startup`, `reboot`, `bridges` | [defaults](../roles/proxmox_host/defaults/main.yml) | [schema](../roles/proxmox_host/meta/argument_specs.yml) |
| [proxmox_installer](../roles/proxmox_installer/tasks/main.yml) | `prepare` | [defaults](../roles/proxmox_installer/defaults/main.yml) | [schema](../roles/proxmox_installer/meta/argument_specs.yml) |
| [unifi_vm](../roles/unifi_vm/tasks/main.yml) | `prepare`, `create`, `verify`, `start`, `stop` | [defaults](../roles/unifi_vm/defaults/main.yml) | [schema](../roles/unifi_vm/meta/argument_specs.yml) |
| [unifi_network](../roles/unifi_network/tasks/main.yml) | `configure`, `verify` | [defaults](../roles/unifi_network/defaults/main.yml) | [schema](../roles/unifi_network/meta/argument_specs.yml) |
| [unifi_host](../roles/unifi_host/tasks/main.yml) | `configure`, `verify`, `restore_ready` | [defaults](../roles/unifi_host/defaults/main.yml) | [schema](../roles/unifi_host/meta/argument_specs.yml) |

## Shared workflow outputs

| Producer | Explicit host-scoped outputs | Consumers |
|---|---|---|
| `community_api`, `load` | `pve_api` or `opn_api`, selected by required `community_api_var` | Trusted API modules in the calling role |
| `opnsense_vm`, `describe` | `opnsense_expected`, `opnsense_create_networks`, `opnsense_wan_argument` | VM resource reconciliation and Proxmox startup checks |
| `opnsense_vm`, `verify` | Desired VM outputs, `opnsense_manifest`, `opnsense_existing_vm` | Installation artifact/ownership checks and pilot hardware checks |
| `idrac_backup`, `export` | `idrac_backup_directory` | Network apply intent and recovery records |

`describe` only builds the desired VM description from inventory and the pinned release; it makes no API, SSH or device request. Other runtime registers retain their existing workflow prefixes. Credentials loaded into named output dictionaries remain suppressed by `no_log`, with their controller files protected as before.

The controller action plugin `plugins/action/wireguard_keys.py` prepares stable Vault-encrypted WireGuard keys using the unlocked Ansible Vault secret; `ansible.cfg` registers its plugin path. The existing runtime Python/PHP/shell helpers remain under `scripts/`, pinned release metadata/signing keys under `files/`, and container build definitions under `containers/`. Role tasks resolve these assets from `role_path`, not from the caller's playbook directory. Templates are local to their owning role. Private inventory, encrypted Vault, existing disk/VM ownership markers, generated artifact paths and recovery-record formats remain compatible.

## File layout

Every role has the same contract/default/dispatcher structure. The complete implementation layout is:

```text
roles/
  cisco_switch/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _backup.yml
      backup.yml
      gateway.yml
      main.yml
      management.yml
      ports.yml
  community_api/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      load.yml
      main.yml
      prepare.yml
  fortigate_backup/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      backup.yml
      main.yml
  fortigate_controller/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      main.yml
      prepare.yml
      verify.yml
  idrac_backup/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      export.yml
      main.yml
  idrac_boot/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _verify_boot.yml
      _verify_image.yml
      boot.yml
      main.yml
      uefi.yml
      verify.yml
  idrac_iso/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _change_media.yml
      _prepare_host.yml
      _read_media.yml
      _start_server.yml
      _stop_server.yml
      eject.yml
      main.yml
      mount.yml
      status.yml
    templates/
      iso-server.plist.j2
  idrac_network/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _preview_profile.yml
      _profile_preflight.yml
      _read_state.yml
      _read_task.yml
      apply.yml
      main.yml
      preview.yml
      status.yml
      verify.yml
  idrac_snapshot/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _network.yml
      _storage.yml
      main.yml
      snapshot.yml
  opnsense_api/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      enroll.yml
      main.yml
  opnsense_install/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      install.yml
      main.yml
  opnsense_media/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      bootstrap.yml
      download.yml
      main.yml
  opnsense_pilot/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _configure.yml
      _policy.yml
      home.yml
      main.yml
      management.yml
  opnsense_vm/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _describe.yml
      _reconcile.yml
      create.yml
      describe.yml
      main.yml
      verify.yml
  opnsense_wireguard/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _backup.yml
      _inputs.yml
      _load.yml
      _policy.yml
      configure.yml
      main.yml
      prepare.yml
      verify.yml
    templates/
      home-admin.conf.j2
  proxmox_api/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      enroll.yml
      main.yml
  proxmox_host/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      _bridges.yml
      _packages.yml
      _read_boot_vm.yml
      _startup.yml
      _verify_boot_network.yml
      bridges.yml
      main.yml
      reboot.yml
      repositories.yml
      startup.yml
      upgrade.yml
    templates/
      proxmox-guest-bridges.j2
  proxmox_installer/
    defaults/
      main.yml
    meta/
      argument_specs.yml
    tasks/
      main.yml
      prepare.yml
```

The orchestration files and their selected groups/actions are listed in [entry points](playbooks/entry-points.md). Generic `configure-*`/`manage-*` entry points require an explicit role action dictionary. Named entries keep their existing commands. Legacy action flags no longer select workflows; use the role parameter dictionary or the corresponding named entry.

The former `playbooks/tasks/` helpers are now task modules in `community_api`, `idrac_snapshot`, `idrac_iso`, `idrac_boot`, `opnsense_vm`, `opnsense_pilot` and `proxmox_host`. `playbooks/templates/iso-server.plist.j2` belongs to `roles/idrac_iso/templates/`; `playbooks/templates/proxmox-guest-bridges.j2` belongs to `roles/proxmox_host/templates/`. `README.md` indexes this architecture and the workflow usage documents.

## Isolated controller roles

`unifi_vm` prepares stable controller artifacts and guards VM 110 ownership, first boot and explicit power operations. `unifi_network` configures/verifies the four named OPNsense rules and DNS record. `unifi_host` installs/verifies the guest and gates the supported manual backup restore. Each role has `defaults/main.yml`, `meta/argument_specs.yml`, a required role-scoped `task_action`, and dynamic `tasks/main.yml` dispatch. Entry points and invocation order are in the [UniFi runbook](playbooks/unifi-controller.md).

```text
roles/
  unifi_vm/
    defaults/main.yml
    meta/argument_specs.yml
    tasks/{main,prepare,create,verify,start,stop,_read,_guest}.yml
    templates/{user-data.yml,isolation.json,isolation.service}.j2
  unifi_network/
    defaults/main.yml
    meta/argument_specs.yml
    tasks/{main,configure,verify,_load,_policy}.yml
  unifi_host/
    defaults/main.yml
    meta/argument_specs.yml
    tasks/{main,configure,verify,restore_ready,_baseline,_installed}.yml
```

Shared helpers live in `scripts/`: `prepare-unifi-artifacts.py`, `prepare-unifi-tls.py`, `inspect-unifi-vm.py`, `configure-unifi-vm-startup.py`, `unifi-isolation.py` and `configure-opnsense-unifi.php`. Ubuntu's pinned public signing key lives in `files/ubuntu-cloud-image-signing-key.asc`. Generated host keys, GUI private keys, seeds, backup copies and manifests stay in protected, Git-ignored controller directories. The existing Proxmox startup/reboot preflight invokes the controller ownership guard before accepting VM 110; it does not grant maintenance permission to arbitrary additional guests.

## Validation and execution

Syntax checking orchestration files does not execute dynamic action bodies. For action-aware checks, use the named entry point with its supported `--check` behavior and review its output; normal read-only verification entries perform their documented runtime checks. Backup workflows require a normal collection run. Network preview creates a vendor validation job, while network status/verification are reads. ISO mount/eject, boot, installation, upgrades and reboots retain their action-specific prerequisites.

Run from the repository root so `ansible.cfg`, pinned collections, role paths and private inventory apply. A minimal custom play can invoke a role through `roles:` or `ansible.builtin.include_role` and supply the corresponding parameter dictionary, required inventory data and execution context. Vault-backed entry points load credentials through `vars_files`, using `vault_file` when supplied by inventory or extra variables and otherwise resolving `secrets/vault.yml` from the repository containing the entry point. This path must resolve before role execution: private role defaults are unavailable at play scope. Roles retain the same optional path default for their own scope. No role grants implicit physical recovery readiness or WAN-assignment confirmation.

References: [Ansible roles and argument validation](https://docs.ansible.com/projects/ansible-core/devel/playbook_guide/playbooks_reuse_roles.html), [include_role and variable visibility](https://docs.ansible.com/projects/ansible-core/2.19/collections/ansible/builtin/include_role_module.html).
