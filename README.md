# Home infrastructure automation

Run infrastructure backup, snapshot and configuration playbooks from the administration laptop using the pinned local Ansible environment.

## Install the pinned local environment

Run once in each new container or workstation, using Python 3.12 or later:

```bash
python3 tools/setup.py
```

This single command installs missing system dependencies, prepares both the runtime
and validation environments, builds the pinned SSH bindings, installs locked Python
packages and Ansible collections, and prepares validation tools. It is safe to rerun:
existing environments are preserved and satisfied dependencies are reused. Internet
access is needed for missing or changed dependencies. System package installation
may prompt for sudo.

Ubuntu/Debian setup installs system packages automatically. On macOS, install
Homebrew and Apple's command-line tools first; setup installs missing Homebrew
packages and selects `.venv-macos` and `.venv-validation-macos`. Linux uses `.venv`
and `.venv-validation`. These environments stay separate when sharing the repository.
Use `.venv/bin/ansible-playbook` on Linux or `.venv-macos/bin/ansible-playbook` on macOS.
Native Mac execution is required when hosting an ISO on the Mac's Ethernet address.

Setup does not read private inventory or credentials or contact network devices.
It does not configure Git hooks or run playbooks. Keep system/Homebrew security
updates current; setup installs missing packages rather than upgrading the OS.
The [SSH transport guide](docs/ssh-transport.md) explains the native library and
legacy compatibility scope. Python locks include SHA-256 download hashes,
enforced by setup. Collection pins remain the source of collection versions;
generated environments and tools stay Git-ignored.

## Repository scope

Keep reusable desired-state configuration, provisioning, maintenance, backups and
verification here. Temporary migration sequencing, lease holds, cutover overlays
and recovery coordination live outside this repository. Final DHCP declarations
use `all.vars.home_dhcp`; transition metadata must not be added to that contract.
Private-WAN and cutover workflows live in the external transition workspace.
Persisted device record names are compatibility identifiers, not instructions to
replay a migration.

## Repository commands

After `python3 tools/setup.py`, use the repository-pinned Just runner:

```bash
./just                    # List commands
./just setup              # Repeat dependency setup
./just validate           # Full offline validation
./just audit              # Online dependency and Git-history audit
```

`./just` requires no PATH changes or environment activation. Setup also exposes
`just` in both native Python environments; after activating either environment,
`just validate` works too. The runner is checksum-pinned in `tools/native-tools.json`.
No dev-container image or global shell configuration changes are needed.

Arguments are forwarded without shell interpolation, for example:

```bash
./just validate --checks php
./just playbook playbooks/configure-unifi-firewall.yml --limit unifi01 --check
```

`playbook` selects `.venv` on Linux and `.venv-macos` on macOS and preserves
Ansible's interactive prompts. Invoke each reusable verification playbook explicitly
with `./just playbook`.

Recipes delegate to the existing scripts and playbooks. Direct Python and Ansible
commands remain supported. Listing commands performs no setup or device operations.

## Shared inventory and credentials

Repository changes are checked with the [automated validation suite](docs/validation.md).
After its one-time setup, run `python3 tools/run-validation.py` from the repository root.
The suite uses synthetic inputs and performs no device configuration operations.

Keep real device addresses and connection settings in `inventory.private.yml`, mode 0600 and Git-ignored. Use `inventory.example.yml` as the starting structure for another installation. Store login usernames and passwords in the encrypted, Git-ignored `secrets/vault.yml`; inventory contains references rather than credential literals. Use the [native Vault commands](docs/credentials.md) to create, edit, view and rekey the store. The repo's `ansible.cfg` sets `ask_vault_pass = True`, so playbook commands prompt automatically without `--ask-vault-pass`. Keep the unlock password separately in your password manager and keep secrets out of command arguments and committed files.

Keep SSH host-key checking and TLS certificate validation enabled. Verify and establish trust before connecting. Scope legacy compatibility exceptions to the affected device/group; each workflow documents its requirements. Do not disable verification to bypass a mismatch.

For physical SSH devices, store the console-verified public host key in private inventory as
`ssh_host_public_key`. SSH-facing roles automatically rebuild `.cache/ssh/known_hosts` and install
those entries in the controller's `~/.ssh/known_hosts`, including during check mode. This restores
trust in fresh containers or after deleting the trust cache without scanning or contacting devices.
See [SSH trust preparation](docs/playbooks/prepare-ssh-trust.md) for enrollment and recovery.

FortiGate workflows also restore missing controller hostname resolution automatically. iDRAC workflows
use the explicit current `idrac_controller_endpoint` for the same recovery. See
[controller hostname preparation](docs/controller-hostnames.md) for sudo requirements and migration handling.

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

## Role architecture

Entry points orchestrate roles with explicit, role-scoped `task_action` parameters. See the [role architecture, contracts and complete directory layout](docs/roles.md) and [entry-point mapping](docs/playbooks/entry-points.md). Optional fallbacks live in role defaults; action selection has no default.

## Workflow documentation

| Workflow | Documentation |
|---|---|
| Permanent HOME DHCP allocation validation | [Validate HOME DHCP](docs/playbooks/validate-home-dhcp.md) |
| Named operation entry points and their inputs | [Playbook entry points](docs/playbooks/entry-points.md) |
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
| Installed firewall automatic startup and controlled Proxmox maintenance reboot | [Configure Proxmox boot](docs/playbooks/configure-proxmox-boot.md) |
| Proxmox guest LAN and WAN bridges with API verification | [Configure Proxmox bridges](docs/playbooks/configure-proxmox-bridges.md) |
| Verified OPNsense DVD ISO preparation on the controller | [Prepare an OPNsense ISO](docs/playbooks/prepare-opnsense-iso.md) |
| OPNsense VM creation and controlled WAN link maintenance | [Create the OPNsense VM](docs/playbooks/create-opnsense-vm.md) |
| Private OPNsense management bootstrap DVD preparation | [Prepare OPNsense bootstrap media](docs/playbooks/prepare-opnsense-bootstrap.md) |
| OPNsense ZFS installation and pinned management SSH verification | [Install OPNsense](docs/playbooks/install-opnsense.md) |
| OPNsense management DNS/NTP, firewall policy and runtime verification | [Configure OPNsense services](docs/playbooks/configure-opnsense-services.md) |
| Owned HOME network with DHCP, DNS and filtered internet access | [Configure OPNsense HOME](docs/playbooks/configure-opnsense-home.md) |
| HOME WireGuard administration, encrypted keys and Mac import | [Configure WireGuard](docs/playbooks/configure-opnsense-wireguard.md) |
| Permanent DEV/BMC routing and authenticated administration from Wi-Fi or port 8 | [Configure lab access](docs/playbooks/configure-opnsense-lab.md) |
| Verified headless Fedora Cloud Base VM, SSH baseline and explicit power operations | [Fedora development VM](docs/playbooks/fedora-dev.md) |
| UniFi guest firewall management and legacy migration | [Declarative UniFi firewall](docs/playbooks/configure-unifi-firewall.md) |
| Isolated UniFi controller VM, pinned artifacts and Vault-backed desired site/WLAN staging | [UniFi controller rehearsal](docs/playbooks/unifi-controller.md) |
| Switch management return route | [Configure switch gateway](docs/playbooks/configure-switch-gateway.md) |
