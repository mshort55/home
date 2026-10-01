# Save an iDRAC state snapshot

Playbook: [snapshot-idrac.yml](../../playbooks/snapshot-idrac.yml).

Read current iDRAC, server, BIOS settings, controller, chassis, power, thermal, virtual-media, job/task and Lifecycle log resources over verified HTTPS and save them as a local state snapshot. These checks are included in the playbook's normal run; no preflight or diagnostic variable file is needed. Storage discovery starts at the system’s advertised `Storage` link, so it follows controller paths exposed by the updated firmware. It sends GET requests only and does not upload firmware, mount media, alter boot settings, recreate storage or reset either the host or iDRAC.

## Prerequisites and credentials

Use the `idracs` group in [inventory.example.yml](../../inventory.example.yml). Set `ansible_host` to a locally resolvable name matching the verified device certificate and `idrac_ca_path` to its connection-scoped PEM trust file under `secrets/`. Verify a self-signed certificate fingerprint independently before trusting it. Keep certificate and hostname validation enabled.

Use the default TLS cipher selection on updated firmware. The original 2.41 iDRAC8 connection required the scoped `idrac_tls_ciphers: [AES128-SHA]` compatibility setting; after updating to 2.70, that offer failed while default TLS successfully negotiated ECDHE-RSA-AES256-GCM-SHA384 with the same verified certificate. Remove the legacy inventory override after that transition. Requests bypass proxies and do not follow redirects.

The inventory hostname must resolve inside the environment running Ansible and match the device certificate. A manually added `/etc/hosts` entry in a container can be lost when the runtime regenerates that file. If a run reports `Name or service not known`, restore the independently verified address mapping in that environment; use persistent DNS or the container runtime's host-mapping configuration for durability. Do not substitute an IP address that fails certificate hostname validation or disable TLS verification.

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

The snapshot is **not a configuration or license recovery backup**. It includes whatever each resource reports at collection time. Old firmware may return 404 (missing) or 501 (not implemented) for optional resources; those statuses remain explicit instead of being interpreted as healthy or empty. Manager and system identification require HTTP 200. Authentication errors and unexpected server errors remain failures. A task collection is not necessarily the Lifecycle Controller job queue, and an empty queue does not establish that RAID initialization has completed. The snapshot does not by itself authorize a firmware update.

Storage responses are saved in `storage_discovery.resources`, keyed by their advertised paths. Discovery follows `Members`, `Drives` and `Volumes` links, reads each exact path once, and stops after 64 resources. Inline controller details and volume `Operations` are preserved in the response bodies. Only local Redfish storage/drive paths are accepted; external URLs and redirects are rejected before sending credentials to another destination. No initialization or other storage action is invoked.

An absent `Storage` link, HTTP 404/501, nonempty `unread_paths`, or a collection’s pagination link means some storage information is unavailable or uncollected. Storage pagination links are preserved but not followed. A complete snapshot file does not mean complete storage coverage; review these limits before drawing conclusions. Missing operation progress does not establish that initialization finished.

Lifecycle log collection saves the returned page and any pagination link; it does not follow subsequent pages or constitute a complete log archive. On the original firmware, that page contained the most recent 50 entries. The log-entry path is `/Managers/iDRAC.Embedded.1/Logs/Lclog` below `/redfish/v1`, as advertised by the device's log service. Hardware health and log history remain observations to review, not automatic approval to apply firmware.

Check mode is rejected before device access. Repeated normal runs retain independent observations. Resolve TLS/authentication failures without disabling verification or guessing passwords. Never print raw snapshots or enable verbose secret-bearing task output.

Each GET has a 30-second socket timeout. A connection failure explicitly reporting a timeout is retried up to twice, with five seconds between attempts. This tolerates a transient slow response while keeping persistent timeouts fatal. HTTP errors, certificate-verification failures and hostname-resolution errors are not retried. No mutation or firmware action is involved.

## Verification record

Prepared against the existing ansible-core 2.20.9 environment using builtin modules only. Syntax and whitespace checks passed. A temporary local HTTPS fixture verified authenticated GET collection, explicit recording of unsupported resources, saved-file integrity and permissions, exclusion of supplied credentials from artifacts, suppression of sensitive task output, and check-mode rejection before network access. The fixture was removed.

The owner confirmed the live iDRAC certificate fingerprint; the scoped trust file passes hostname, certificate and validity checks. The initial live run successfully authenticated and read the manager, system, controller and virtual-media endpoints, then exposed an unhandled 501 on the optional jobs endpoint. A synthetic HTTPS regression reproduced that exact failure before the fix. The playbook now records optional 404/501 responses while keeping required identity and authentication failures fatal. Regression checks passed for a preserved optional 501, rejected required-resource 501, rejected authentication 401, and check mode making no network requests. Syntax validation also passed; temporary fixtures were removed. The owner confirmed a successful rerun; the saved snapshot's completion manifest, checksum, size and permissions were independently verified. Renaming the workflow to `snapshot-idrac.yml` subsequently passed syntax validation.

The normal resource list now includes the chassis, power, thermal and Lifecycle log checks previously supplied through temporary overrides. The owner’s subsequent snapshot verified iDRAC 2.86.86.86; its obsolete fixed controller path returned 404, prompting advertised-link storage discovery.

The first post-update run reached the server but timed out on the manager GET while the other nine reads succeeded. A temporary authenticated HTTPS fixture replayed the actual loop task with a shortened timeout and reproduced that failure before the retry change. Afterward, a single timeout recovered on the second GET, persistent timeouts stopped after three GETs, and HTTP 401 failed after one GET. Synthetic credentials remained suppressed; syntax and whitespace checks passed. The fixture was removed. This validates bounded timeout recovery, not the cause of the live server's slow response.

References: [Dell iDRAC8 2.40 Redfish resource guide](https://dl.dell.com/topicspdf/idrac7-8-lifecycle-controller-v2.40.40.40_api-guide_en-us.pdf), [Ansible URI module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/uri_module.html).

Advertised-link storage discovery passed a temporary authenticated HTTPS fixture using the full playbook: controller, drive and volume collection; preserved initialization progress; duplicate-link suppression; explicit optional 501; rejected external links and authentication failures; snapshot checksum and permissions; and no supplied credentials in saved observations or console output. Syntax validation passed. Live storage verification awaits the owner’s next Vault-unlocked run. Resource layout reference: [Dell iDRAC8 2.70 Redfish guide, Storage and Volume resources](https://dl.dell.com/topicspdf/idrac8redfishguide_en-us.pdf).

The BIOS settings resource advertised by the updated server is included as `bios`, preserving `Attributes` for boot-mode and virtualization read-back. As with other optional resources, HTTP 404/501 is recorded as unavailable.
