# Manage credentials with Ansible Vault

Use the native `ansible-vault` commands to create, edit, display and rekey the credential store. Device credentials are data in the Vault, not part of a device-specific setup playbook. Complete the [shared environment setup](../README.md#install-the-pinned-local-environment) first. Run the commands below from `/Repos/home`.

The encrypted store is `secrets/vault.yml`. The entire `secrets/` directory is Git-ignored, including encrypted files. Keep its unlock password separately in your password manager; never put it in inventory, command arguments or the repository. Use mode 0700 for the directory and 0600 for the Vault file.

## Create a Vault once

Skip this step when `secrets/vault.yml` already exists. For a new checkout:

```bash
cd /Repos/home
umask 077
mkdir -p secrets
chmod 700 secrets
.venv/bin/ansible-vault create secrets/vault.yml
chmod 600 secrets/vault.yml
```

Choose and confirm a strong Vault password. Ansible opens the editor selected by `$EDITOR` (default `vi`). Start with a device-neutral structure:

```yaml
vault_devices: {}
```

Save and exit; Ansible encrypts the file. Creation initializes the store; adding device credentials is a separate edit below. The current local Vault already exists and does not need to be recreated.

## Add or update device credentials

```bash
cd /Repos/home
.venv/bin/ansible-vault edit secrets/vault.yml
```

Enter the Vault password and edit the YAML. For example, a switch entry uses the inventory hostname as its key:

```yaml
vault_devices:
  switch01:
    username: '<device login username>'
    ssh_password: '<device SSH password>'
    enable_password: '<device enable password>'
```

Replace the placeholders in the editor. Preserve existing device entries when adding another device. Existing switch entries created before the username was moved into Vault need the `username` field added alongside their existing passwords. Use valid YAML quoting for passwords with special characters. Add only fields required by the relevant workflow; an API-managed device may need different fields from an SSH-managed device. Updating this file changes credentials supplied to automation, not the accounts or passwords configured on devices.

Ansible decrypts into a temporary editor file, then re-encrypts on save. Avoid editor backup/swap/history copies containing secrets. Do not use `ansible-vault decrypt` to leave the store permanently unencrypted.

## View or print decrypted contents

To view using the configured pager:

```bash
.venv/bin/ansible-vault view secrets/vault.yml
```

To print directly to stdout instead:

```bash
PAGER=cat .venv/bin/ansible-vault view secrets/vault.yml
```

Both prompt for the Vault password and leave the on-disk file encrypted. Printing intentionally displays the credentials in the terminal; no plaintext output file is created unless you redirect it.

## Change the Vault password

```bash
.venv/bin/ansible-vault rekey secrets/vault.yml
```

Enter the existing password and the new password when prompted, then update your password manager. Rekeying changes the encryption password without changing the stored device credentials.

Keep a protected recovery copy of the encrypted file, with the unlock password stored separately. The encrypted file is intentionally not uploaded to the public repository. Losing the unlock password prevents decrypting this store; it does not change the devices' credentials.

## How playbooks use the store

The private inventory contains references rather than password literals:

```yaml
ansible_user: "{{ vault_devices[inventory_hostname].username }}"
ansible_password: "{{ vault_devices[inventory_hostname].ssh_password }}"
ansible_become_password: "{{ vault_devices[inventory_hostname].enable_password }}"
```

A playbook loads `secrets/vault.yml` using `vars_files`. The repo's `ansible.cfg` sets `ask_vault_pass = True`, so playbook commands prompt automatically; `--ask-vault-pass` is unnecessary when running from the repo root. This supplies the stored credentials without individual SSH/enable prompts. The default also prompts for playbooks that do not need Vault; for those commands, use `ANSIBLE_ASK_VAULT_PASS=False` as a per-command override. This setting does not store or cache the password. See the [switch backup instructions](playbooks/backup-switch.md) for the complete command and prerequisites.

Encryption does not verify a device password. A successful connection through the relevant playbook is the acceptance check. If unlocking fails, check the Vault password. If authentication fails after successful unlocking, inspect the device entry with `edit`. Keep secret-bearing output suppressed during ordinary playbook runs.

Vault protects this credential store at rest. It does not automatically encrypt configuration exports under `backups/`, which retain their separate permissions and Git ignores.

## Verification record

The existing local Vault was confirmed to have an Ansible Vault header and mode 0600. Replacing the custom setup workflow with native CLI instructions preserved both the encrypted file and private inventory byte-for-byte. Inventory credential resolution and backup syntax were previously validated with an encrypted test fixture. Live validation of owner-entered credentials remains a separate backup run; no real credentials were decrypted as part of this documentation change.

Reference: [Ansible Vault create, edit, view and rekey](https://docs.ansible.com/projects/ansible/latest/vault_guide/vault_encrypting_content.html).
