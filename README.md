# Home infrastructure automation

Run infrastructure workflows from the administration laptop, using a pinned local environment. Occasional maintenance and recovery tasks belong here when keeping them repeatable is useful; frequency alone does not determine whether a task should be automated. Build and test automation incrementally: establish initial access manually, then apply supported settings through small, explicitly invoked workflows. Document manual exceptions when automation is not practical.

## Install the pinned local environment


Run from this directory, using Python 3.12:

```bash
cd /Repos/home
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml -p .collections
```

`requirements.in` records direct Python dependencies; `requirements.txt` pins their resolved dependencies. Collections and their dependencies are pinned separately. The virtual environment and downloaded collections stay local and Git-ignored. Installation changes laptop files only.

## Shared inventory and credentials

Keep real device addresses and connection settings in `inventory.private.yml`, mode 0600 and Git-ignored. Use `inventory.example.yml` as the starting structure for another installation. Store login usernames and passwords in the encrypted, Git-ignored `secrets/vault.yml`; inventory contains references rather than credential literals. Use the [native Vault commands](docs/credentials.md) to create, edit, view and rekey the store. The repo's `ansible.cfg` sets `ask_vault_pass = True`, so playbook commands prompt automatically without `--ask-vault-pass`. Keep the unlock password separately in your password manager and keep secrets out of command arguments and committed files.

Keep SSH host-key checking and TLS certificate validation enabled. Verify and establish trust before connecting. Scope legacy compatibility exceptions to the affected device/group; each workflow documents its requirements. Do not disable verification to bypass a mismatch.

Private inventories, credentials, generated configuration and backup artifacts remain local and Git-ignored. Keep real device details out of public examples and workflow documentation; use synthetic values instead. Use mode 0700 for private artifact directories and 0600 for files. Suppress secret-bearing task output and diffs; keep persistent connection logging disabled.

## Layout and documentation conventions

| Location | Purpose |
|---|---|
| `playbooks/` | Explicitly invoked workflows |
| `roles/` | Reusable implementation units, added when needed |
| `docs/playbooks/<playbook-name>.md` | Purpose, prerequisites, inputs, commands, outputs, side effects, troubleshooting and verification record for that playbook |
| `docs/roles/<role-name>.md` | Role-specific inputs, behavior, dependencies and verification, added with each role |
| `docs/credentials.md` | Shared native Vault command reference |
| `collections/requirements.yml` | Pinned Ansible collections |
| `requirements.in` / `requirements.txt` | Direct and resolved Python dependencies |
| `inventory.example.yml` | Shareable inventory structure with synthetic values |
| `inventory.private.yml` | Local real inventory, untracked |
| `secrets/vault.yml` | Encrypted device credentials, untracked; unlock password stored separately |
| `backups/` | All local backups, grouped by device/run, untracked |

This README owns shared setup and conventions plus the documentation index. Put all playbook/role-specific operational instructions and test results under `docs/`, and link them here. Use matching filenames so a playbook or role's documentation is easy to find. Links between workflow documents and implementation files should be relative; command examples run from the automation root.

## Running workflows

Read the workflow's documentation before invoking it. Validate syntax first, review the intended scope, then run one bounded operation at a time. Check-mode support and repeat-run behavior are workflow-specific; never assume `--check` proves successful application or creates an artifact.

There is no automatic apply on Git push. Configuration-changing operations, initial installation, firmware maintenance and migration transitions use separate entry points. Routine runs must not replay destructive bootstrap steps. Verify the relevant behavior after execution and reconcile emergency manual changes before subsequent applies.

## Workflow documentation

| Workflow | Documentation |
|---|---|
| Shared credential management | [Ansible Vault CLI](docs/credentials.md) |
| Cisco configuration backup | [Switch backup](docs/playbooks/backup-switch.md) |
| FortiGate configuration backup | [FortiGate backup](docs/playbooks/backup-fortigate.md) |
| iDRAC state snapshot | [iDRAC snapshot](docs/playbooks/snapshot-idrac.md) |

No reusable roles have been introduced yet. Add their documentation to this index when they are implemented.
