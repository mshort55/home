# Back up the Cisco switch

Playbook: [backup-switch.yml](../../playbooks/backup-switch.yml).

Collect separate running and startup configuration exports over SSH without changing switch configuration. Complete the [shared environment setup](../../README.md#install-the-pinned-local-environment) first. Run the commands below from the automation root, not this documentation directory.

## Inventory and credentials


`inventory.private.yml` contains the current switch address/user, mode 0600 and Git-ignored. It contains no passwords. For another installation, copy `inventory.example.yml`, replace the example address/user, and run `chmod 600 inventory.private.yml`.

The switch's previously trusted key must be in the operator's `~/.ssh/known_hosts`. Host-key checking remains enabled and automatic acceptance is disabled. This switch uses Paramiko because of its legacy SSH compatibility; the choice is scoped to the Cisco inventory group. OpenSSH `-o` algorithm options do not configure this transport. Do not disable host-key checking to bypass a key mismatch. Revisit the transport when switch SSH support changes.

Credentials are entered at hidden terminal prompts, not saved in inventory or command arguments. At Ansible's become-password prompt, enter the enable password, or press Enter to use the SSH password if they are the same. Ansible Vault can replace prompts later.

## Run a backup

```bash
cd /Repos/home
.venv/bin/ansible-playbook playbooks/backup-switch.yml --syntax-check
.venv/bin/ansible-playbook playbooks/backup-switch.yml --ask-pass --ask-become-pass
```

The playbook reads `show privilege`, `show running-config` and `show startup-config`, requiring privilege level 15. The connection plugin also handles enable mode and session-local terminal settings. It does not enter configuration mode, save running configuration to startup, reload, restore or change switch settings. Running and startup may differ; preserve both as found.

All backups live under the single Git-ignored `backups/` directory in the repository root. Each run creates a unique subdirectory:

```text
backups/switch01-<UTC timestamp>-<unique suffix>/
  running.cfg
  startup.cfg
  manifest.yml
```

Directories are mode 0700 and files mode 0600. Configuration output is suppressed with `no_log` and `diff: false`; persistent connection logging is disabled. Configurations are validated for IOS version/end markers before files are created. The manifest records completion, source, privilege level, sizes and SHA-256 checksums after both files are saved and checked. It also compares the configuration bodies beginning at the IOS `version` line, excluding leading display headers; this is a text comparison, not a semantic configuration audit. A directory without a completion manifest is incomplete and must not be relied on. Backups remain Git-ignored, and previous runs are retained.

`--check` is deliberately rejected: a simulated run does not produce a backup. Use `--syntax-check` for offline validation. A repeated normal run intentionally creates another snapshot; local files report changes even though switch configuration is untouched. These exports do not back up IOS images, the separate VLAN database file, certificates/private keys or every other device filesystem artifact, and collection does not establish that restoration has been rehearsed.

If authentication or enable fails, stop and resolve credentials; do not retry guesses. If output validation fails, investigate privately without printing configuration or enabling verbose connection logs. Never use `write memory` or `copy running-config startup-config` as part of taking a backup.

## Verification record

2026-09-30: syntax validation and Python dependency checks passed. Two actual backup runs completed over SSH against the existing switch, including enable-mode privilege level 15. Each created its own folder; both sets of checksums, sizes and permissions were independently verified. The explicit check-mode rejection was tested and stopped before device collection. No switch configuration was changed.

Tested environment: Python 3.12.3, ansible-core 2.20.9, Paramiko 4.0.0, cisco.ios 11.5.1, ansible.netcommon 8.7.1 and ansible.utils 6.1.1. Existing backup folders were consolidated under the repository's `backups/` directory, preserving checksums and permissions. New runs use the same layout. The path change passed syntax validation; it did not require another device collection.

Review of the saved exports found only a self-signed certificate representation difference: running-config embeds the certificate bytes, while startup-config references an NVRAM certificate file. All configuration text outside that representation matches. The manifest correctly reports a text mismatch; this is not evidence of unsaved VLAN, port or access settings. Both originals remain unchanged. The referenced NVRAM certificate file has not been independently read or compared, and a restore has not been attempted.

References: [IOS commands module](https://docs.ansible.com/projects/ansible/latest/collections/cisco/ios/ios_command_module.html), [IOS enable-mode setup](https://docs.ansible.com/projects/ansible/latest/network/user_guide/platform_ios.html), [network CLI connection settings](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/network_cli_connection.html).
