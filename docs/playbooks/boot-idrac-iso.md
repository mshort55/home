# Boot a mounted ISO through iDRAC

Playbook: [boot-idrac-iso.yml](../../playbooks/boot-idrac-iso.yml).

Configure one-time boot from iDRAC8's virtual CD/DVD and power on an offline UEFI server. This replaces manual selection in the F11 boot menu. Mount the image first with [mount-idrac-iso.yml](mount-idrac-iso.md); this boot workflow does not mount, eject or restart a running server. Booting an unattended installation ISO can immediately format its selected disk.

The `boot-idrac-iso.yml` and `verify-idrac-iso-boot.yml` entry points explicitly select `boot` and `verify`. Both invoke the [idrac_boot role](../../roles/idrac_boot/tasks/main.yml), which requires `idrac_boot_options.task_action` before inspecting ISO files or accessing iDRAC. The generic `manage-idrac-iso-boot.yml` requires this parameter dictionary explicitly.

## Inputs and prerequisites

Run from an Ansible controller with BMC network access, trusted hostname/CA, Vault credentials and a local copy of the selected ISO. The image hosting job runs on the native Mac and must remain running. A Linux dev container can execute this boot playbook if it shares the ISO files and can reach iDRAC and the Mac's hosting address. Paths are resolved in the executing controller's inventory location. Keep the hosting Mac powered, its lid open and its Ethernet connected until installation finishes reading the media.

The `idracs` inventory supplies `ansible_host`, `idrac_expected_mac` and `idrac_ca_path`. Supply `idrac_iso_path`, `idrac_iso_sha256`, `idrac_iso_bind_address` and optionally `idrac_iso_port` (default 8080), matching the mounted image. A generated `mount-vars.yml` from [Proxmox ISO preparation](prepare-proxmox-iso.md) supplies the prepared path and checksum. Paths must be valid on the machine executing the playbook. External image hosting is not supported by this boot workflow.

The server must be powered off, already configured for UEFI, and have the exact selected image attached read-only. Shut down any discovery environment before replacing its media. This workflow stops if the server is on; repeated execution cannot restart an active installer or running OS. It also refuses a conflicting boot override, pending BIOS differences, incomplete job collections, and unfinished or unknown jobs.

## Preview and boot

From the activated Ansible environment at the repository root, after mounting a prepared image:

```bash
ansible-playbook playbooks/boot-idrac-iso.yml --limit idrac01 --check \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml
ansible-playbook playbooks/boot-idrac-iso.yml --limit idrac01 \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml
```

Vault prompts locally. No sudo password is needed; this workflow does not edit hostname mappings. For an original ISO already described by inventory, omit the `-e @...` argument. Keep its discovery-only boot separate from an unattended installation boot.

Check mode hashes the local ISO, reads device state and jobs, and probes the existing HTTP service with a one-byte range request. The service must return the expected file size and checksum ETag. The probe sends no iDRAC credentials. Check mode creates no records and submits no configuration or power requests.

A normal run imports exactly two iDRAC settings: `ServerBoot.1#BootOnce=Enabled` and `ServerBoot.1#FirstBootDevice=vCD-DVD`. Dell's virtual-media-specific SCP method distinguishes the virtual DVD from a physical optical drive. The import targets only `IDRAC`; it omits shutdown/reboot options because `NoReboot` can stage iDRAC8 imports until a host reboot. Dell's default final power state for an import is `On`, so the import itself may power on the server. The playbook waits for `Completed` with an `OK` task status before considering any separate power request. Failed, suspended or reboot-waiting imports stop the workflow without a separate power request; current host power must still be inspected.

After the completed import, it reads the system and DVD again and requires the same attached read-only image and a stable `Off` or `On` state. If the server is already on, it skips the power POST. If it remains off, it submits `ComputerSystem.Reset` with `ResetType=On` once. Both paths read back `PowerState=On`. It does not change the persistent BIOS boot sequence. The one-time setting allows the next normal boot to use the existing boot sequence after the override is consumed.

## Verification and recovery

Each normal run creates a private `backups/<host>-iso-boot-<timestamp>-<suffix>/` directory, mode 0700, with files mode 0600:

- `before.json`: selected image, checksum, initial power/boot state and the two-attribute profile.
- `import-submission.json` and `import-task.json`: configuration response and last task state.
- `ready.json`: system and media read-back after import, retained even if a subsequent assertion fails.
- `power-intent.json` and `power-result.json`: power request intent, response and last system read-back.
- `completion.json`: successful configuration task, powered-on state and whether a separate power request was sent, with OS installation explicitly unverified.

Request credentials and Ansible invocation arguments are not recorded. Device responses are private and task output is suppressed. Import and power POSTs are never automatically retried. Import polling allows 25 GET attempts, and power polling allows 13, with five-second delays and 30-second request timeouts. HTTP errors end polling.

If a request fails or times out, inspect the saved responses and current iDRAC state before rerunning. A lost power response may still have powered on the server. A completed boot-profile import followed by a later failure may leave one-time DVD boot armed; inspect that setting before manually powering on. The workflow does not automatically roll back an uncertain request, power off a server, force restart it, or remove media.

Successful completion confirms API task completion and the reported power state. Observe the VGA console or iDRAC virtual console to confirm the installer actually boots and finishes. For Proxmox, establish management connectivity and SSH host-key trust after installation; boot API success alone does not establish OS installation or SSH access.

To verify an existing boot attempt on a running server, use `verify-idrac-iso-boot.yml`. It selects operation `verify`; supply the original record directory and the same image inputs:

```bash
ansible-playbook playbooks/verify-idrac-iso-boot.yml --limit idrac01 \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml \
  -e 'idrac_iso_boot_record={{ inventory_dir }}/backups/<boot-record-directory>'
```

Verification checks the selected ISO's local checksum, the protected original intent/submission files, device identity, original completed import task, current power state and attached image. Each resource GET has a 60-second timeout; override `idrac_iso_boot_read_timeout` if needed. Read timeouts receive at most two retries with five-second delays. HTTP errors and other connection failures are not retried. No POST is retried or submitted by verification.

The operation saves named resource results in private `verification-reads.json`, including HTTP status, timeout indication, attempts and response bodies. This diagnostic file is retained even when a read fails. A successful verification also writes `verification.json`; it preserves the original attempt's records and does not create a retroactive `completion.json`. It does not require the HTTP hosting service to remain reachable after media has finished loading. It requires the image to remain attached. Check mode performs the reads without writing verification files. This operation verifies the original boot request rather than proving OS installation completed.

Offline syntax validation without unlocking the real Vault:

```bash
ANSIBLE_ASK_VAULT_PASS=False ansible-playbook \
  -i inventory.example.yml playbooks/boot-idrac-iso.yml \
  -e vault_file=/dev/null --syntax-check
```

References: [Dell virtual-media one-time boot example](https://github.com/dell/iDRAC-Redfish-Scripting/blob/master/Redfish%20Python/SetNextOneTimeBootVirtualMediaDeviceOemREDFISH.py), [Dell import power-state defaults](https://github.com/dell/iDRAC-Redfish-Scripting/blob/master/Redfish%20Python/ImportSystemConfigurationLocalFilenameREDFISH.py), [iDRAC8 power action](https://www.dell.com/support/manuals/en-us/poweredge-r230/idrac8_redfishapiguide_2.70.70.70/supported-action--reset?guid=guid-3444cf02-da8d-422a-9400-6ce5ba71d9bd&lang=en-us).
