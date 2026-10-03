# Back up the iDRAC Server Configuration Profile

Playbook: [backup-idrac.yml](../../playbooks/backup-idrac.yml).

Export an XML Server Configuration Profile (SCP) directly over verified HTTPS into a new private backup directory. The playbook submits the advertised Redfish export action once, receives the XML from its task endpoint, checks the final task status, and validates the profile. It does not import configuration, install firmware, or reboot anything.

## Prerequisites and run

Use the same `idracs` inventory, independently verified TLS certificate, and existing Vault credentials as [snapshot-idrac.yml](snapshot-idrac.md). Lifecycle Controller must be enabled. Local export must be advertised by the manager resource; Dell documents this feature for iDRAC7/8 firmware 2.50.50.50 and later.

From `/Repos/home`:

```bash
.venv/bin/ansible-playbook playbooks/backup-idrac.yml
```

Vault prompts locally. No NFS share, disk image, or extra variable file is needed. Repeated runs retain existing backups and create a separate export directory.

Offline syntax validation:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/backup-idrac.yml \
  -e vault_file=/dev/null --syntax-check
```

## Files and verification

Each invocation allocates a unique mode-0700 directory under `backups/idrac01-scp-<timestamp>-<suffix>/`. Files have mode 0600:

- `server-configuration.xml`: the downloaded profile, saved before another task GET can consume or replace the download response.
- `export-request.json`: submission intent, then the accepted response and task location.
- `export-download.json`: the last download response for private diagnosis; on success this includes a second copy of the sensitive XML.
- `export-task.json`: the final task response, including failed completion when available.
- `manifest.yml`: completion record written only after successful task status and XML verification; includes SHA-256, size, firmware, and export options.

The request selects `Target: ALL`, `ExportUse: Default`, and `IncludeInExport: IncludePasswordHashValues`. Treat all artifacts as secrets. Supplied credentials and Ansible request arguments are excluded from records; sensitive task output and diffs are suppressed. Keep the XML out of public logs and shared output.

Both polling phases allow at most 61 GETs with ten seconds between attempts and a thirty-second socket timeout per request. HTTP errors stop polling. A failed terminal task stops the run; completion requires `Completed` and `OK` or `Ok`. Task URLs must use the expected task path on the exact authenticated HTTPS origin. Redirects and proxies are disabled; certificate and hostname verification remain enabled.

The export POST is never automatically retried. If submission or download fails, inspect the private records and the iDRAC task before rerunning. A fresh invocation creates a separate export, not a resume of the previous task. Incomplete directories remain available for diagnosis. Check mode fails before network access.

The XML verifier rejects symlinks, malformed or oversized XML, DTDs, an unexpected root, a service tag differing from Redfish `SKU`, and missing iDRAC/BIOS/RAID components or configuration attributes. It checks file permissions and records a hash of the validated bytes.

This is a configuration recovery artifact, not a disk image. Export validation does not establish that the profile can be restored. Default exports leave some settings commented out; review the profile before any future import. Keep the separately saved Enterprise license XML.

Reference: [Dell RESTful Server Configuration, section 2.4: local SCP export](https://downloads.dell.com/manuals/common/dell-emc-restful-server-config-idrac-api.pdf).
