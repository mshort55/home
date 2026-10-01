# Back up the iDRAC Server Configuration Profile

Playbook: [backup-idrac.yml](../../playbooks/backup-idrac.yml).

Export an XML Server Configuration Profile (SCP) from the existing iDRAC8 to a prepared NFS share. This submits the advertised Redfish **export** action, polls its task, then validates the file through the laptop's shared filesystem. It does not import settings, upload firmware or reset the server or iDRAC.

## Prerequisites

Use the same `idracs` inventory, independently verified TLS certificate and existing Vault administrator credentials as [snapshot-idrac.yml](snapshot-idrac.md). Lifecycle Controller must be enabled. The old firmware requires a network share for this export; local Redfish file streaming is unavailable on this version.

Prepare a dedicated run directory under this repository's `backups/`, containing an empty `export/` directory. Both directories must have mode 0700. Share only `export/` over NFS, restrict it to the iDRAC address, and map writes to the local backup owner's UID/GID. Keep the share available until task completion and file validation. NFS carries the configuration over the LAN without transport encryption; use the trusted administration network and remove the temporary export afterward.

The Mac host and Ubuntu administration environment must see the same backup files. The NFS path is the **Mac's exported path**; the backup directory variable is the **Ubuntu path**. A share on another computer needs a different file retrieval workflow and is not supported by this playbook.

Put the following non-secret but private values in a mode-0600, ignored file such as `.cache/idrac-scp.private.json`:

```json
{
  "idrac_nfs_server": "192.0.2.20",
  "idrac_nfs_share": "/System/Volumes/Data/Users/example/Repos/home/backups/idrac01-scp-example/export",
  "idrac_backup_directory": "/Repos/home/backups/idrac01-scp-example"
}
```

For macOS, preserve any existing `/etc/exports`, validate the proposed file with `sudo nfsd -F <candidate> checkexports`, then add the restricted export and use `sudo nfsd start` and `sudo nfsd update`. `showmount -e localhost` should advertise the exact directory and iDRAC address without an offline marker. A stopped daemon cannot verify export permissions; the real export must still establish write access. Preserve the service's original enablement setting. Do not export the entire repository or existing backups.

## Run

From `/Repos/home`, after the share is prepared:

```bash
.venv/bin/ansible-playbook playbooks/backup-idrac.yml \
  -e @.cache/idrac-scp.private.json
```

Vault prompts locally. Offline validation:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/backup-idrac.yml \
  -e vault_file=/dev/null --syntax-check
```

Check mode is rejected before network access. One invocation handles one prepared export per host; each host needs its own destination. The workflow refuses to overwrite an existing export or resubmit when `export-request.json` already exists. The POST is never automatically retried. If submission times out, inspect iDRAC's task state before deciding whether another export is needed.

## Files and verification

The run directory contains:

- `export/server-configuration.xml`: the original SCP, restricted to mode 0600.
- `export-request.json`: submission intent, then the accepted response and task location, excluding supplied credentials and Ansible request arguments.
- `export-task.json`: the last polling response, including an unsuccessful or timed-out task when available.
- `manifest.yml`: written only after successful task completion and file verification; records the SHA-256, size, firmware and export settings.

The request selects `Target: ALL`, `ExportUse: Default`, and `IncludeInExport: IncludePasswordHashValues`. Sensitive HTTP responses and XML validation output are suppressed. Credentials stay in Vault; treat the exported password hashes as secrets. Do not enable verbose secret-bearing output or paste the XML into chat.

Polling uses at most 61 requests, separated by ten seconds, with a thirty-second timeout per request. Unexpected HTTP failures stop polling. The task must report `Completed` and either `OK` or the legacy firmware's `Ok`. Task URLs must be relative to the expected task collection or use the exact authenticated HTTPS origin; redirects are disabled.

The local verifier rejects symlinks, malformed/oversized XML, an unexpected root, a service tag that differs from Redfish `SKU`, and missing iDRAC/BIOS/RAID components or configuration attributes. It verifies the file mode and hashes the validated bytes. These checks establish a configuration artifact for the expected server, **not a tested restoration**. The default SCP format leaves some attributes commented out; any future restore needs review. The SCP is not a disk image and does not replace the separately saved Enterprise license.

If a task fails, inspect the private task record for the export error. Resolve share access without disabling TLS validation or widening the NFS host restriction. Leave incomplete artifacts in place for diagnosis; do not delete the request marker and blindly rerun.

After success, remove only the temporary line added to `/etc/exports` and reload with `sudo nfsd update`. If NFS was originally stopped and no other share needs it, run `sudo nfsd stop`. Preserve unrelated entries and the original enabled/disabled setting. Retain the backup files after removing the share.

## Verification record

Syntax validation passed with the pinned ansible-core environment. A temporary authenticated HTTPS fixture passed successful export, checksum/permission verification, service-tag mismatch rejection, foreign task-origin rejection, failed-task rejection, check mode without network access, and repeat-run rejection before device access. Supplied credentials did not appear in logs or artifacts. The fixture was removed.

Live testing subsequently succeeded using a small HFS+ disk image on the Mac NFS host. The original host-filesystem destination allowed mount/access/create/remove but the export stopped after a capacity query with SYS045; the small HFS+ destination returned SYS043 and produced the XML. This establishes a working alternative without isolating whether filesystem type or capacity caused the earlier failure. The successful response used `TaskStatus: Ok`, exposing an overly strict `OK` comparison. Replaying that response reproduced the assertion failure before the correction; the corrected assertion accepts Completed/Ok and Completed/OK and rejects Critical, Warning and non-completed states. The successful XML passed the actual playbook verifier, including service-tag matching and core components. It was copied out of the mounted image, verified again, and recorded in a completion manifest whose `file` points to the permanent copy. Restoration remains untested.

After firmware 2.50.50.50 or later, prefer a separately implemented local-streaming SCP workflow, avoiding the legacy network-share requirement. This NFS playbook does not automatically switch transports. [Dell local-file streaming support, section 2.4](https://downloads.dell.com/manuals/common/dell-emc-restful-server-config-idrac-api.pdf).

References: [Dell iDRAC8 2.40 Redfish guide](https://dl.dell.com/topicspdf/idrac7-8-lifecycle-controller-v2.40.40.40_api-guide_en-us.pdf), [Dell SCP export types](https://infohub.delltechnologies.com/en-us/l/server-configuration-profiles-reference-guide/export-type-clone-and-replace-2/), [Apple nfsd manual](https://raw.githubusercontent.com/apple-oss-distributions/nfs/main/nfsd/nfsd.8), [Apple exports manual](https://raw.githubusercontent.com/apple-oss-distributions/nfs/main/nfsd/exports.5).
