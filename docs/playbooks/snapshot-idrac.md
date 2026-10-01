# Save an iDRAC state snapshot

Playbook: [snapshot-idrac.yml](../../playbooks/snapshot-idrac.yml).

Read current iDRAC, server, controller, virtual-media and job/task resources over verified HTTPS and save them as a local state snapshot. This bounded workflow is prepared for the previously discovered iDRAC8 resource paths. It sends GET requests only and does not upload firmware, mount media, alter boot settings, recreate storage or reset either the host or iDRAC.

## Prerequisites and credentials

Use the `idracs` group in [inventory.example.yml](../../inventory.example.yml). Set `ansible_host` to a locally resolvable name matching the verified device certificate and `idrac_ca_path` to its connection-scoped PEM trust file under `secrets/`. Verify a self-signed certificate fingerprint independently before trusting it. Keep certificate and hostname validation enabled.

The old iDRAC8 connection requires the scoped `idrac_tls_ciphers: [AES128-SHA]` setting. This changes only the TLS cipher offer for these requests, not the laptop's global policy. Reassess it after firmware maintenance. Requests bypass proxies and do not follow redirects.

Use the [native Vault editor](../credentials.md) to add the existing administrator credentials while preserving other device entries:

```yaml
vault_devices:
  idrac01:
    username: '<existing iDRAC administrator>'
    password: '<existing iDRAC password>'
```

## Run

From `/Repos/home`:

```bash
.venv/bin/ansible-playbook playbooks/snapshot-idrac.yml
```

Vault prompts automatically. For offline syntax validation:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/snapshot-idrac.yml \
  -e vault_file=/dev/null --syntax-check
```

## Output and limits

Each run creates `backups/idrac01-snapshot-<timestamp>-<suffix>/observations.json` and `manifest.yml`, with directory mode 0700 and file mode 0600. Sensitive responses and file diffs are suppressed. The snapshot saves only resource paths, HTTP statuses and response bodies, excluding Ansible request arguments and supplied credentials. A completion manifest follows checksum/permission verification and identifies new artifacts as `state_snapshot`, with `recovery_backup: false`. Snapshots created before the rename retain their original `idrac01-inspection-*` folders and manifests.

The snapshot is **not a configuration or license recovery backup**. It includes whatever each resource reports at collection time. Old firmware may return 404 (missing) or 501 (not implemented) for optional storage, virtual-media or job/task resources; those statuses remain explicit instead of being interpreted as healthy or empty. Manager and system identification require HTTP 200. Authentication errors and unexpected server errors remain failures. A task collection is not necessarily the Lifecycle Controller job queue, and an empty queue does not establish that RAID initialization has completed. The snapshot does not by itself authorize a firmware update.

Check mode is rejected before device access. Repeated normal runs retain independent observations. Resolve TLS/authentication failures without disabling verification or guessing passwords. Never print raw snapshots or enable verbose secret-bearing task output.

## Verification record

Prepared against the existing ansible-core 2.20.9 environment using builtin modules only. Syntax and whitespace checks passed. A temporary local HTTPS fixture verified authenticated GET collection, explicit recording of unsupported resources, saved-file integrity and permissions, exclusion of supplied credentials from artifacts, suppression of sensitive task output, and check-mode rejection before network access. The fixture was removed.

The owner confirmed the live iDRAC certificate fingerprint; the scoped trust file passes hostname, certificate and validity checks. The initial live run successfully authenticated and read the manager, system, controller and virtual-media endpoints, then exposed an unhandled 501 on the optional jobs endpoint. A synthetic HTTPS regression reproduced that exact failure before the fix. The playbook now records optional 404/501 responses while keeping required identity and authentication failures fatal. Regression checks passed for a preserved optional 501, rejected required-resource 501, rejected authentication 401, and check mode making no network requests. Syntax validation also passed; temporary fixtures were removed. The owner confirmed a successful rerun; the saved snapshot's completion manifest, checksum, size and permissions were independently verified. Renaming the workflow to `snapshot-idrac.yml` subsequently passed syntax validation.

References: [Dell iDRAC8 2.40 Redfish resource guide](https://dl.dell.com/topicspdf/idrac7-8-lifecycle-controller-v2.40.40.40_api-guide_en-us.pdf), [Ansible URI module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/uri_module.html).
