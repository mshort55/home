# Home infrastructure automation

Run infrastructure backup, snapshot and configuration playbooks from the administration laptop using the pinned local Ansible environment.

## Install the pinned local environment

Run from this directory, using Python 3.12:

```bash
cd /Repos/home
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml -p .collections
```

`requirements.in` records direct Python dependencies; `requirements.txt` pins their resolved dependencies. Collections and their dependencies are pinned separately. The virtual environment and downloaded collections stay local and Git-ignored. Installation changes laptop files only.

When the repository is shared between a Linux container and a Mac, create a separate native Mac environment. Python must be 3.12 or later. Run in the Mac's terminal:

```bash
cd /Users/$(whoami)/Repos/home
python3 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r requirements.txt
.venv-macos/bin/ansible-galaxy collection install -r collections/requirements.yml -p .collections
```

Use `.venv-macos/bin/ansible-playbook` for native Mac runs. Linux virtual environments cannot be reused on macOS. Native execution is required when hosting an ISO on the Mac's Ethernet address.

## Shared inventory and credentials

Keep real device addresses and connection settings in `inventory.private.yml`, mode 0600 and Git-ignored. Use `inventory.example.yml` as the starting structure for another installation. Store login usernames and passwords in the encrypted, Git-ignored `secrets/vault.yml`; inventory contains references rather than credential literals. Use the [native Vault commands](docs/credentials.md) to create, edit, view and rekey the store. The repo's `ansible.cfg` sets `ask_vault_pass = True`, so playbook commands prompt automatically without `--ask-vault-pass`. Keep the unlock password separately in your password manager and keep secrets out of command arguments and committed files.

Keep SSH host-key checking and TLS certificate validation enabled. Verify and establish trust before connecting. Scope legacy compatibility exceptions to the affected device/group; each workflow documents its requirements. Do not disable verification to bypass a mismatch.

Private inventories, credentials, generated configuration and backup artifacts remain local and Git-ignored. Keep real device details out of public examples and workflow documentation; use synthetic values instead. Use mode 0700 for private artifact directories and 0600 for files. Suppress secret-bearing task output and diffs; keep persistent connection logging disabled.

## Repository layout

| Location | Purpose |
|---|---|
| `playbooks/` | Explicitly invoked workflows |
| `docs/playbooks/<playbook-name>.md` | Playbook purpose, prerequisites, inputs, commands, outputs and troubleshooting |
| `docs/credentials.md` | Shared native Vault command reference |
| `collections/requirements.yml` | Pinned Ansible collections |
| `requirements.in` / `requirements.txt` | Direct and resolved Python dependencies |
| `inventory.example.yml` | Shareable inventory structure with synthetic values |
| `inventory.private.yml` | Local real inventory, untracked |
| `secrets/vault.yml` | Encrypted device credentials, untracked; unlock password stored separately |
| `backups/` | All local backups, grouped by device/run, untracked |

The workflow documentation below describes each playbook. Command examples run from the repository root.

## Running workflows

Read the workflow's documentation before invoking it. Validate syntax first, review the intended scope, then run one bounded operation at a time. Check-mode support and repeat-run behavior are workflow-specific; never assume `--check` proves successful application or creates an artifact.

Playbooks run only when explicitly invoked; Git pushes do not apply configuration. Use the documented read-back and recovery procedures to verify changes and reconcile manual device changes before subsequent applies.

## Workflow documentation

| Workflow | Documentation |
|---|---|
| Shared credential management | [Ansible Vault CLI](docs/credentials.md) |
| Cisco configuration backup | [Switch backup](docs/playbooks/backup-switch.md) |
| Switch access ports and static trunks, including iDRAC and server roles | [Configure managed ports](docs/playbooks/configure-switch-ports.md) |
| Switch VLAN objects and management SVI preparation | [Configure management](docs/playbooks/configure-switch-management.md) |
| FortiGate configuration backup | [FortiGate backup](docs/playbooks/backup-fortigate.md) |
| iDRAC state snapshot | [iDRAC snapshot](docs/playbooks/snapshot-idrac.md) |
| iDRAC configuration backup | [iDRAC SCP backup](docs/playbooks/backup-idrac.md) |
| iDRAC IPv4 network transition | [Configure iDRAC networking](docs/playbooks/configure-idrac-network.md) |
| iDRAC UEFI boot maintenance | [Set UEFI through Redfish](docs/playbooks/set-idrac-uefi.md) |
| iDRAC ISO mounting and native Mac image hosting | [Mount an ISO](docs/playbooks/mount-idrac-iso.md) |
| iDRAC one-time virtual DVD boot and power on | [Boot a mounted ISO](docs/playbooks/boot-idrac-iso.md) |
| Private unattended Proxmox ISO preparation | [Prepare a Proxmox ISO](docs/playbooks/prepare-proxmox-iso.md) |
| Proxmox API enrollment and HTTPS trust | [Configure Proxmox API](docs/playbooks/configure-proxmox-api.md) |
| OPNsense API enrollment and HTTPS trust | [Configure OPNsense API](docs/playbooks/configure-opnsense-api.md) |
| Proxmox repositories and explicit host package upgrades | [Configure Proxmox host](docs/playbooks/configure-proxmox-host.md) |
| Proxmox guest LAN and WAN bridges with API verification | [Configure Proxmox bridges](docs/playbooks/configure-proxmox-bridges.md) |
| Verified OPNsense DVD ISO preparation on the controller | [Prepare an OPNsense ISO](docs/playbooks/prepare-opnsense-iso.md) |
| OPNsense VM creation and controlled pilot WAN attachment | [Create the OPNsense VM](docs/playbooks/create-opnsense-vm.md) |
| Private OPNsense management bootstrap DVD preparation | [Prepare OPNsense bootstrap media](docs/playbooks/prepare-opnsense-bootstrap.md) |
| OPNsense ZFS installation and pinned management SSH verification | [Install OPNsense](docs/playbooks/install-opnsense.md) |
| OPNsense management DNS/NTP, restricted update access and private WAN pilot | [Configure OPNsense pilot](docs/playbooks/configure-opnsense-pilot.md) |
