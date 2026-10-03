# Back up the FortiGate

Playbook: [backup-fortigate.yml](../../playbooks/backup-fortigate.yml).

Download a global FortiOS configuration export over verified HTTPS using the existing administrator login. Complete the [shared environment setup](../../README.md#install-the-pinned-local-environment), including the pinned `fortinet.fortios` collection. Run commands from `/Repos/home`.

## Inventory, trust and credentials

Use the `fortigates` group in [inventory.example.yml](../../inventory.example.yml) as the structure for your private inventory. `ansible_host` must resolve to the device and match its certificate. Keep certificate validation enabled. Set `ansible_httpapi_ca_path` to a PEM file containing the verified issuing CA or self-signed device certificate; this trust file is scoped to this connection and belongs under the Git-ignored `secrets/` directory.

Verify a self-signed certificate's SHA-256 fingerprint through an independently trusted device session before trusting it. Downloading a certificate from an unverified connection only gives a candidate to compare. Check its validity and hostname too. A certificate issued only to a hostname cannot validate a connection to an IP address. A local hostname mapping can preserve the device configuration when its existing certificate has a usable name; establish that mapping and verify TLS before sending credentials. Do not work around failures with `ansible_httpapi_validate_certs: false`.

Add the existing administrator login locally with the [native Vault editor](../credentials.md):

```bash
.venv/bin/ansible-vault edit secrets/vault.yml
```

Preserve other devices and add this entry beneath the existing `vault_devices` mapping:

```yaml
vault_devices:
  fortigate01:
    username: '<existing administrator username>'
    password: '<existing administrator password>'
```

The account must be authorized to export the entire device configuration, including global settings and all VDOMs. No account, API token or permission change is performed by this playbook. Resolve insufficient privileges separately; never accept a VDOM-only or masked export as the recovery backup. Authentication may create audit/session activity. The collection implements username/password authentication and session logout.

## Run a backup

```bash
.venv/bin/ansible-playbook playbooks/backup-fortigate.yml --syntax-check
.venv/bin/ansible-playbook playbooks/backup-fortigate.yml
```

Vault prompts automatically. For syntax-only validation without unlocking the real store, use `/dev/null` as the Vault input:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/backup-fortigate.yml \
  -e vault_file=/dev/null --syntax-check
```

The playbook calls `fortinet.fortios.fortios_monitor_fact` with selector `system_config_backup` and `scope: global`. In the pinned collection this performs a GET on `/api/v2/monitor/system/config/backup`. It saves `meta.raw` directly and closes the persistent session after collection. It does not save, restore, reboot or write device settings. The `root` request context does not limit the explicitly global export to that VDOM.

This is a native configuration recovery export of the whole device, rather than selected API settings. It is not an image of device storage or an export that explicitly expands every default setting. Firmware, logs and separate recovery credentials still need their own records. Certificate/private-key recovery requirements must be checked for the actual device; this workflow alone does not prove those assets can be restored.

## Output and verification

Each run creates a separate snapshot beneath the shared backup directory:

```text
backups/fortigate01-<UTC timestamp>-<unique suffix>/
  configuration.cfg
  manifest.yml
```

Directories are mode 0700 and files mode 0600. Export tasks suppress sensitive results and diffs; module and persistent connection logging are disabled. The export is not additionally Vault-encrypted. Treat all configuration contents, including encrypted password fields, as sensitive and retain the Git exclusions.

Before writing, the playbook requires HTTP 200, a FortiOS configuration header, global/interface sections, a final `end` and no `FortinetPasswordMask` placeholder. After writing, it verifies the saved SHA-256 against the response and checks file permissions. Only then does it write the completion manifest. These structural and integrity checks detect common failed/truncated exports; they do not prove restoration. A folder without a completion manifest is incomplete.

`--check` is deliberately rejected before connection. A repeated normal run creates another snapshot and reports local changes. No automatic restore or device configuration change is part of either run.

If TLS validation fails, resolve the certificate chain, name or expiry before authenticating. If authentication fails, verify the Vault entry locally without guessing credentials or enabling verbose connection logs. If export validation fails, inspect it privately and confirm firmware/API compatibility and account scope; do not print its body into ordinary logs.

References: [Fortinet backup/restore workflow](https://ansible-galaxy-fortios-docs.readthedocs.io/en/latest/faq.html#how-to-backup-and-restore-fos), [monitor facts module](https://docs.ansible.com/projects/ansible/latest/collections/fortinet/fortios/fortios_monitor_fact_module.html), [HTTP API connection and scoped CA trust](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/httpapi_connection.html).
