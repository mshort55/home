# Configure iDRAC IPv4 networking

Playbook: [configure-idrac-network.yml](../../playbooks/configure-idrac-network.yml).

Preview a small Server Configuration Profile (SCP), submit its IPv4 changes once, inspect its task and verify completion through the recovered endpoint. This workflow supports iDRAC8's advertised Redfish SCP actions when its manager attribute endpoints are unavailable. It keeps certificate and hostname validation enabled and uses the normal inventory and Vault credentials.

## Inputs and scope

Inventory supplies the independently verified `idrac_expected_mac` and `idrac_network.address`, `.netmask`, `.gateway`. The public example uses synthetic addresses. Static configuration is bounded to a private IPv4 /24 with a different usable gateway in that subnet. The interface must already be enabled and untagged; its MAC must match inventory. The hostname must resolve to the current address and match the trusted certificate.

Operations are `preview` (default), `apply`, `status`, and `verify`. `idrac_network_mode` defaults to `static`; `dhcp` is the rollback option. Static mode includes exactly four attributes in the `iDRAC.Embedded.1` component: `IPv4.1#DHCPEnable=Disabled` and `IPv4Static.1#Address`, `Netmask`, `Gateway`. DHCP mode contains only `IPv4.1#DHCPEnable=Enabled`. BIOS, RAID, other NIC settings, IPv6, hostname and DNS settings are outside this profile. Existing DNS learned from DHCP might become unavailable after DHCP is disabled; direct recovery uses the trusted hostname through a local hosts mapping.

The future gateway can be configured before it exists. Same-subnet recovery does not require it. Inter-VLAN reachability requires a later firewall stage.

## Preview

From the automation root:

```bash
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e idrac_network_mode=dhcp
```

Each normal preview creates one validation job and private local records. It does not submit a configuration import or reboot. `--check` is rejected before network access; it cannot simulate the asynchronous validation action. For offline syntax validation:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv/bin/ansible-playbook \
  -i inventory.example.yml playbooks/configure-idrac-network.yml \
  -e vault_file=/dev/null --syntax-check
```

The workflow checks the advertised action targets and local-buffer support, refuses unfinished or unknown job states, posts a preview once, validates its returned task URL against the exact HTTPS origin and polls until completion. `Completed` with `OK` or `Ok` is required before apply.

## Coordinated apply and recovery

Stage a recovery computer on the destination BMC access port with a static address in the destination /24, no gateway/DNS, and Wi-Fi, VPNs and bridging disabled for the test. Keep independent control of the switch on its legacy network or console. Prepare both forward and rollback switch inventory edits before proceeding. The apply readiness input means this physical recovery path is staged; it does not establish or test it automatically.

```bash
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e '{"idrac_network_operation":"apply","idrac_network_recovery_ready":true}'
```

Apply first runs the existing iDRAC backup workflow, then reads live identity and settings, refuses unfinished jobs and performs a fresh preview. If the requested IPv4 state is already present, it submits no import. Otherwise it imports the same bounded profile once with `Target: IDRAC`, omitting shutdown and other host power-control options. Dell documents that iDRAC-only profiles do not trigger a host reboot. A successful POST means the request was accepted; configuration completion remains unverified. The response can be lost when the management address changes. Do not resubmit blindly after a timeout or interrupted run: inspect the private intent/submission record and the recovered endpoint first.

`ShutdownType: NoReboot` can defer iDRAC8 SCP changes until a host reboot. This playbook omits that option and does not automatically reboot the host. If an existing import is paused waiting for reboot, inspect its task with `status` and follow the recovery procedure below before submitting another import. [Dell SCP guide, sections 4.1 and 4.2.3](https://dl.dell.com/manuals/all-products/esuprt_solutions_int/esuprt_solutions_int_solutions_resources/servers-solution-resources_setup-guide3_en-us.pdf).

Next, update only the `idrac` port's access VLAN in the normal private switch inventory. Preview and apply the shared port workflow:

```bash
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["idrac"]}' --check
.venv/bin/ansible-playbook playbooks/configure-switch-ports.yml \
  -e '{"switch_port_roles":["idrac"]}'
```

The iDRAC remains untagged. Its management cable stays on its existing switch port; the recovery computer uses the separate BMC recovery port. Test the new address from that recovery computer. Update its local hostname mapping to the new address while retaining the same verified CA/certificate identity. Execute verification from a controller with direct BMC access or a working route to the destination network. Transfer the pinned repo environment, private inventory, CA and encrypted credentials to that controller if needed.

Use the relative `task_path` printed after an accepted import (or strip the verified origin from `import-submission.json.location`):

```bash
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e '{"idrac_network_operation":"status","idrac_network_task_path":"/redfish/v1/TaskService/Tasks/JID_example"}'
```

`status` makes one task GET through the currently reachable endpoint and reports task/job state, progress, current IPv4 settings and `waiting_for_host_reboot`. It checks device identity but does not require the requested address to have been applied. It creates no backup, preview or import. Successful execution means the status read succeeded, not that configuration completed. For an older paused NoReboot import, use the retained source-subnet recovery path to inspect it, then perform the planned host reboot manually. Do not submit another import while the old one remains paused.

After the new endpoint is reachable, verify the existing task:

```bash
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e '{"idrac_network_operation":"verify","idrac_network_task_path":"/redfish/v1/TaskService/Tasks/JID_example"}'
```

Verification requires the requested live IPv4 settings, expected MAC and an enabled untagged interface, as well as successful task completion. It stops polling immediately for a task reporting that it is waiting for reboot and fails with the operator action, rather than timing out or claiming completion. It reads the interface again after task completion. Verification does not submit an import, backup or preview job. An unavailable task cannot establish successful completion; inspect the device rather than inventing a task path.

A recovery Mac without Ansible can make the same authenticated reads with its built-in `curl`. Copy the verified CA file to it first. For synthetic example values:

```bash
curl --fail --silent --show-error --noproxy '*' \
  --cacert ./idrac-ca.pem \
  --resolve bmc.example.test:443:10.77.40.10 --user admin \
  'https://bmc.example.test/redfish/v1/Managers/iDRAC.Embedded.1/EthernetInterfaces/iDRAC.Embedded.1%23NIC.1'
```

`--user` prompts for the password; keep it out of the command. `--resolve` directs the request to the new IP while validating the certificate against the trusted hostname. Read the saved task path on the same origin, require `Completed`/`OK`, and reread the interface after completion. Compare the returned MAC, IPv4/VLAN settings and task result with the requested configuration.

## Rollback

While direct BMC access still works, preview and apply DHCP mode:

```bash
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e idrac_network_mode=dhcp
.venv/bin/ansible-playbook playbooks/configure-idrac-network.yml \
  -e '{"idrac_network_operation":"apply","idrac_network_mode":"dhcp","idrac_network_recovery_ready":true}'
```

After submission, restore the iDRAC switch port's original access VLAN through the same shared port playbook. Discover the renewed DHCP address, verify identity and update hostname resolution before running `verify` with `idrac_network_mode=dhcp` and the rollback import's task path. DHCP does not guarantee the previous lease. Changing only the switch VLAN leaves a static destination-subnet address stranded; restore DHCP from the BMC path first. If the endpoint is unreachable on both networks, use the retained physical console and reviewed recovery records rather than repeated imports.

## Records and validation

Each submitted preview/apply has a unique mode-0700 `backups/<host>-network-<timestamp>-<suffix>/` directory. Mode-0600 files contain the exact `profile.xml`, `before.json`, `intent.json`, `preview-submission.json` and `preview-task.json`. Apply adds `import-submission.json` and references its separate verified SCP backup. Credentials are excluded from records and suppressed in task output/diffs. Intent distinguishes pending submission, completed preview and accepted-but-unverified import; an incomplete intent alone does not prove a POST failed. No import is automatically retried. HTTP errors stop polling. Preview allows 25 GET attempts, verification 13, with five-second delays and 30-second request timeouts. Read-only status performs one task GET.

Reference: [Dell RESTful Server Configuration, sections 2.5, 2.9 and 2.13–2.14](https://downloads.dell.com/manuals/common/dell-emc-restful-server-config-idrac-api.pdf).
