# Save an iDRAC state snapshot

Playbook: [snapshot-idrac.yml](../../playbooks/snapshot-idrac.yml).

Read current iDRAC, server, BIOS settings, controller, chassis, power, thermal, virtual-media, job/task, Lifecycle log and network/PCIe inventory resources over verified HTTPS and save them as a local state snapshot. These checks are included in the playbook's normal run; no preflight or diagnostic variable file is needed. Storage discovery starts at the system’s advertised `Storage` and `SimpleStorage` links, so it follows controller paths exposed by the device. It sends GET requests only and does not upload firmware, mount media, alter boot settings, recreate storage or reset either the host or iDRAC.

## Prerequisites and credentials

Use the `idracs` group in [inventory.example.yml](../../inventory.example.yml). Set `ansible_host` to a locally resolvable name matching the verified device certificate and `idrac_ca_path` to its connection-scoped PEM trust file under `secrets/`. Verify a self-signed certificate fingerprint independently before trusting it. Keep certificate and hostname validation enabled.

Use the default TLS cipher selection. If older firmware requires an explicit compatibility cipher list, set `idrac_tls_ciphers` only for that device and review the override after firmware upgrades. Requests bypass proxies and do not follow redirects.

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

Each run creates `backups/idrac01-snapshot-<timestamp>-<suffix>/observations.json` and `manifest.yml`, with directory mode 0700 and file mode 0600. Sensitive responses and file diffs are suppressed. The snapshot saves only resource paths, HTTP statuses and response bodies, excluding Ansible request arguments and supplied credentials. A completion manifest follows checksum/permission verification and identifies the artifact as `state_snapshot`, with `recovery_backup: false`.

The snapshot is **not a configuration or license recovery backup**. It includes whatever each resource reports at collection time. Old firmware may return 404 (missing) or 501 (not implemented) for optional resources; those statuses remain explicit instead of being interpreted as healthy or empty. Manager and system identification require HTTP 200. Authentication errors and unexpected server errors remain failures. A task collection is not necessarily the Lifecycle Controller job queue, and an empty queue does not establish that RAID initialization has completed.

The advertised BIOS settings resource is saved as `bios`, preserving `Attributes` for boot-mode and virtualization inspection. HTTP 404/501 is recorded as unavailable.

Storage responses are saved in `storage_discovery.resources`, keyed by their advertised paths. Discovery follows `Members`, `Drives`, `Volumes`, `StorageControllers`, related `Links.Drives`/`Links.Volumes`, and advertised storage settings links; it reads each exact path once and stops after 64 resources. Inline controller details and volume `Operations` are preserved in the response bodies. `advertised_roots` records which storage roots were exposed. Only local Redfish storage/controller/drive paths are accepted; external URLs and redirects are rejected before sending credentials to another destination. No initialization or other storage action is invoked.

An absent `Storage` link, HTTP 404/501, nonempty `unread_paths`, or a collection’s pagination link means some storage information is unavailable or uncollected. Storage pagination links are preserved but not followed. A complete snapshot file does not mean complete storage coverage; review these limits before drawing conclusions. Missing operation progress does not establish that initialization finished.

Network inventory is saved in `network_discovery.resources`. Roots come from advertised system, manager and chassis `EthernetInterfaces`, `NetworkInterfaces` and `NetworkAdapters` links, plus system PCIe device/function links. iDRAC8 also documents `/redfish/v1/Systems/System.Embedded.1/NetworkAdapters`; when it is absent from the system's advertised roots, this optional GET is recorded under `documented_optional.NetworkAdapters`. Discovery follows collection members, adapters, ports, device functions, PCIe associations and physical-port assignments. It stops after 128 unique paths, records any `unread_paths`, and preserves unsupported HTTP 404/501 and pagination links without following pagination. Invalid/external links are rejected before credential use; redirects are not followed. Manager interface IDs containing the encoded `#` character are supported.

The resulting bodies preserve permanent/current MAC addresses, Dell FQDDs, link state, PCIe location, and any disk identifiers that the firmware actually exposes. They do not establish Linux interface names or udev filter properties; `linux_interface_names_observed: false` makes that limit explicit. A controller WWN or a physical RAID member's WWN/serial is not the virtual disk's identifier. An empty virtual-disk `Identifiers` array remains empty. Before preparing a destructive unattended install, verify the chosen logical disk and NIC filter against the installer environment; do not infer `sda`, `eno1`, or a virtual-disk WWN from unrelated hardware identifiers.

Lifecycle log collection saves the returned page and any pagination link; it does not follow subsequent pages or constitute a complete log archive. The log-entry path is `/Managers/iDRAC.Embedded.1/Logs/Lclog` below `/redfish/v1`, as advertised by the device's log service.

Check mode is rejected before device access. Repeated normal runs retain independent observations. Resolve TLS/authentication failures without disabling verification or guessing passwords. Never print raw snapshots or enable verbose secret-bearing task output.

Each GET has a 30-second socket timeout. A connection failure explicitly reporting a timeout is retried up to twice, with five seconds between attempts. This tolerates a transient slow response while keeping persistent timeouts fatal. HTTP errors, certificate-verification failures and hostname-resolution errors are not retried. No mutation or firmware action is involved.

References: [Dell iDRAC8 2.40 Redfish resource guide](https://dl.dell.com/topicspdf/idrac7-8-lifecycle-controller-v2.40.40.40_api-guide_en-us.pdf), [Dell iDRAC8 2.70 Redfish resource guide](https://dl.dell.com/topicspdf/idrac8redfishguide_en-us.pdf), [Ansible URI module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/uri_module.html).
