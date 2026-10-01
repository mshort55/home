# Set UEFI boot mode through Redfish

[set-idrac-uefi.yml](../../playbooks/set-idrac-uefi.yml) is a maintenance operation for this server before OS installation. It changes `BootMode` from `Bios` to `Uefi`, creates the Dell BIOS configuration job, waits for scheduling, issues one `ForceRestart`, waits for completion, and verifies the applied BIOS attribute. The force restart is deliberate for the owner's server with no installed OS; do not reuse this workflow on a running workload without a shutdown plan.

Run locally with the existing inventory, scoped certificate trust and Vault credentials:

```bash
cd /Repos/home
.venv/bin/ansible-playbook playbooks/set-idrac-uefi.yml
```

No virtual console or additional variable file is needed. After success, run `playbooks/snapshot-idrac.yml` to capture full hardware state.

Before writing, the playbook checks advertised BIOS/settings and reset paths, current boot mode, pending BIOS differences and all entries in a bounded job collection. Unknown or unfinished job states and incomplete collections stop the run. Historical terminal jobs are retained. Already-applied UEFI with no pending changes exits without another write or restart. Only `BootMode` is patched; unrelated pending BIOS changes are refused both before and after the PATCH. It does not recreate RAID, mount media, install an OS, or change network settings.

Mutations are never retried automatically. Polling is bounded: up to 31 scheduling reads five seconds apart, then 91 completion reads ten seconds apart, each with a 30-second socket timeout. HTTP failures stop the run. The created job must report `Scheduled` before restart and `Completed` afterward; BIOS read-back must report `Uefi` before success. TLS/hostname verification stays enabled, proxies/redirects are disabled, and returned job URLs must match the authenticated origin and expected job path.

Private records are saved under `backups/idrac01-uefi-<timestamp>-<suffix>/`, with directory mode 0700 and files 0600. Records include pre-change observations, intent, job submission/location, last polled job response and verified BIOS read-back. Request credentials are excluded and task output suppressed. If a run fails after a write, inspect these records and pending settings/jobs before retrying; the workflow does not automatically discard pending settings, delete jobs, resume an interrupted run, or roll back. If a write times out, its outcome may be unknown.

Check mode is rejected before network access. Offline validation:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/set-idrac-uefi.yml \
  -e vault_file=/dev/null --syntax-check
```

Validation uses a temporary authenticated HTTPS fixture running the actual playbook: successful PATCH/job/restart/read-back; already-UEFI no-op; pending BIOS and active-job refusal before writes; foreign job URL and failed scheduling refusal before restart; incorrect final BIOS value rejected; check mode without requests; private record permissions and credential suppression. The owner's live run subsequently completed successfully: the BIOS job reported Completed and both the maintenance read-back and an independent full snapshot confirmed BootMode Uefi. Processor virtualization remained enabled and storage health remained OK.

References: [Dell BIOS setting example](https://infohub.delltechnologies.com/en-nz/l/dell-poweredge-getting-started-with-redfish-ansible-modules/changing-a-bios-setting/), [Dell iDRAC8 job API](https://www.dell.com/support/manuals/en-nz/precision-r7910-workstation/idrac8_redfishapiguide_2.70.70.70/delljob?guid=guid-79d11cfa-c737-45b1-ab5e-f46f10508ca7&lang=en-us).
