# Back up the Cisco switch

Playbook: [backup-switch.yml](../../playbooks/backup-switch.yml).

Collect separate running and startup configuration exports over SSH without changing switch configuration. Complete the [shared environment setup](../../README.md#install-the-pinned-local-environment) first. Run the commands below from the automation root, not this documentation directory.

## Inventory and credentials

`inventory.private.yml` contains the switch address and references to Vault credentials, mode 0600 and Git-ignored. The login username, SSH password and enable password are read from `vault_devices.switch01` in Vault. For another installation, copy `inventory.example.yml`, replace the example address, populate the matching Vault entry, and run `chmod 600 inventory.private.yml`.

The switch's previously trusted key must be in the operator's `~/.ssh/known_hosts`. Host-key checking remains enabled and automatic acceptance is disabled. The Cisco inventory group uses the [pinned libssh transport](../ssh-transport.md) and explicitly selects `files/ssh/cisco-legacy.conf`; this adds only the legacy host signature, group14 key exchange and full SHA-1 MAC required by older IOS. Other connections retain their normal policies. OpenSSH `-o` arguments do not configure this transport. Do not disable host-key checking to bypass a key mismatch. Revisit the compatibility policy when switch SSH support changes.

Create the credential store if needed and add the switch entry using the [native Vault commands](../credentials.md). The playbook loads the encrypted `secrets/vault.yml`, and inventory references the device's username, SSH password and enable password by inventory hostname. The switch entry requires `username`, `ssh_password` and `enable_password`.

## Run a backup

```bash
cd /Repos/home
.venv/bin/ansible-playbook playbooks/backup-switch.yml --syntax-check
.venv/bin/ansible-playbook playbooks/backup-switch.yml
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

IOS can represent a self-signed certificate as inline bytes in running configuration and an NVRAM file reference in startup configuration. The manifest's text comparison can report a mismatch for that representation difference; it does not read the referenced certificate file or compare its contents.

`--check` is deliberately rejected: a simulated run does not produce a backup. Use `--syntax-check` for offline validation. A repeated normal run intentionally creates another snapshot; local files report changes even though switch configuration is untouched. These exports do not back up IOS images, the separate VLAN database file, certificates/private keys or every other device filesystem artifact, and collection does not establish that restoration has been rehearsed.

If authentication or enable fails, stop and resolve credentials; do not retry guesses. If output validation fails, investigate privately without printing configuration or enabling verbose connection logs. Never use `write memory` or `copy running-config startup-config` as part of taking a backup.

References: [IOS commands module](https://docs.ansible.com/projects/ansible/latest/collections/cisco/ios/ios_command_module.html), [IOS enable-mode setup](https://docs.ansible.com/projects/ansible/latest/network/user_guide/platform_ios.html), [network CLI connection settings](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/network_cli_connection.html).
