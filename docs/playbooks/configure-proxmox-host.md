# Configure Proxmox host repositories, updates, time and WAN EEE

`playbooks/configure-proxmox-host.yml` manages the installed standalone Proxmox VE 9 host's signed package repositories and optionally applies package upgrades. `community.proxmox` verifies the node and firewall VM through trusted HTTPS. `ansible.builtin.deb822_repository` owns repository files and `ansible.builtin.apt` handles indexes and upgrades over existing trusted root SSH; the Proxmox collection does not provide these package-management operations.

The entry points invoke the `proxmox_host` role. Its required `proxmox_host_options.task_action` selects an explicit action; repository and package work use `repositories` or `upgrade`, while `time` and `wan_eee` configure the settings described below. The generic host entry point requires this dictionary explicitly. [Role contracts](../roles.md) validate inputs before API or host access.

## Prerequisites and inventory

Complete [Proxmox API enrollment](configure-proxmox-api.md), host bridges, OPNsense installation and the [management pilot](configure-opnsense-services.md). The owned firewall VM must be running with no pending hardware changes and its WAN connected. The host needs its management DNS/gateway and outbound HTTP/HTTPS access for repositories.

This workflow requires an amd64 host, Debian 13 trixie, Proxmox VE 9, the installed `proxmox-ve` meta-package, Python `apt` and `debian.deb822`, and Ceph 19 Squid client packages. It supports the accepted standalone local/LVM storage layout; cluster membership, local/external Ceph storage, package holds and incomplete dpkg transactions require separate maintenance. At least 4 GiB free root space and 512 MiB free boot space are required.

Select the repository channel on the Proxmox host:

```yaml
proxmox_host_repository: no-subscription
```

`enterprise` requires an active host subscription. Both channels use the installed Proxmox archive keyring, with APT signature verification enabled. The workflow keeps Ceph client packages on Squid rather than changing their major release. It creates no Ceph cluster or storage. [Proxmox repository reference](https://github.com/proxmox/pve-docs/blob/master/pve-package-repos.adoc).

## Repository ownership

The workflow accepts the two installed Debian base/security stanzas in `/etc/apt/sources.list.d/debian.sources`, preserving that file byte-for-byte. It manages these deb822 files:

| File | Purpose |
|---|---|
| `pve-enterprise.sources` | Enterprise PVE channel, enabled only when selected |
| `proxmox.sources` | No-subscription PVE channel, enabled only when selected |
| `ceph.sources` | Same-major Squid client updates from the selected channel |

Unexpected active legacy sources, third-party `.list`/`.sources` files, duplicate stanzas, different releases/components/signing keys or conflicting repository destinations stop the workflow. Repository work retains comments and old contents in a private backup, while managed files converge to the module's canonical format. It does not patch the web interface or subscription notices.

Before a repository change, existing source files are copied into a fresh mode-0700 `/root/ansible-repositories-*` directory with mode-0600 files. The directory is reported before repository writes. Package upgrades do not have an automatic rollback or create a VM backup.

## Configure repositories, then preview upgrades

The repository entry point explicitly selects repository/index setup and installs no host package upgrades:

```bash
ansible-playbook playbooks/configure-proxmox-repositories.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-repositories.yml --limit pve01
```

The normal run refreshes signed indexes after repository changes. Otherwise it reuses the cache for `proxmox_host_cache_valid_time` seconds, default 3600. Override with `-e '{"proxmox_host_cache_valid_time":0}'` to request a fresh refresh. Check mode does not refresh indexes or modify repositories.

Once repository setup passes, explicitly preview and apply updates:

```bash
ansible-playbook playbooks/update-proxmox-host.yml --limit pve01 --check
ansible-playbook playbooks/update-proxmox-host.yml --limit pve01
```

`update-proxmox-host.yml` invokes `proxmox_host` with `task_action: upgrade`. Upgrade mode refuses unconverged repository files; apply `configure-proxmox-repositories.yml` first. Its check-mode package preview uses the existing indexes and cannot predict packages published after that refresh. The normal upgrade refreshes expired indexes before applying updates, so its package set may differ from an older preview.

The APT task uses a full dependency-resolving upgrade within the configured release, with `fail_on_autoremove: true`, no automatic cleanup, no downgrades and no unauthenticated packages. Existing modified configuration files retain their installed contents using `force-confdef,force-confold`. Refused removals or held/conflicting packages need a separately reviewed resolution. Unattended major OS/PVE/Ceph release upgrades are outside this workflow. [Ansible APT module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/apt_module.html).

## Verification and reboot status

After normal repository or package work, the playbook checks source convergence, the Proxmox meta-package, package health, and identical hashes for Debian sources, host network files and storage definitions, plus an unchanged management default route. It verifies Proxmox services and trusted API access, and requires the firewall VM to retain identical current/pending configuration and running power state. It sends no VM start/stop or host network reload request. Package installation scripts may restart host services; API checks retry while they return.

The report includes the running kernel, newest installed Proxmox kernel and whether a newer kernel or Debian reboot marker indicates pending reboot work. It performs no host reboot. Use [configure-proxmox-boot.yml](configure-proxmox-boot.md) to enable startup for the installed firewall and explicitly request a required maintenance reboot with recovery checks.

A repeat run converges repository files and packages. Cache refresh can report a change when its age expires. An immediate repeated upgrade preview should report no package changes after successful application, unless repository content or installed state changed meanwhile.

If a run fails, preserve its output and reported source backup. Repository recovery consists of restoring the saved files and removing a newly created `proxmox.sources` only if it was absent in that backup, then refreshing APT indexes. Repository recovery does not undo installed packages. Reconcile the cause through the playbook or a reviewed maintenance workflow before repeating upgrades.


## Synchronize time through OPNsense

The existing generic host playbook also supports `proxmox_host_options.task_action: time`.
It derives the sole NTP source from `proxmox_network.management.gateway` and requires
that address to match the enrolled `opnsense_guest` management address. Public NTP
is blocked by the MGMT policy, while UDP 123 to the firewall is allowed.

```bash
./just playbook playbooks/configure-proxmox-host.yml --limit pve01 --check --diff \
  -e '{"proxmox_host_options":{"task_action":"time"}}'
./just playbook playbooks/configure-proxmox-host.yml --limit pve01 \
  -e '{"proxmox_host_options":{"task_action":"time"}}'
```

This action requires installed Chrony and takes ownership of `/etc/chrony/chrony.conf`.
Review the diff: the managed file replaces public pools and dynamic include/source
directories with the single gateway source. The template validates with `chronyd -p`
before installation, piping the candidate to stdin because AppArmor blocks direct
reads from Ansible temporary directories. Pipeline failures also reject the candidate.
It saves a backup when replacing an existing file. Chrony is
enabled and restarted only when the configuration changes (or started if stopped).
It performs no package installation, VM operation, host reboot or network reload.

The retained `makestep 1 3` policy can step the host clock after the restart; for the
observed unsynchronized host this corrects approximately 24 seconds of lag.
Apply waits up to approximately 50 seconds for synchronization within 0.5 seconds
and requires the gateway to be the selected source. If synchronization fails, the
new configuration remains installed; inspect `chronyc -n sources` and `chronyc tracking`
and gateway NTP availability before rerunning. The source depends on the firewall
VM starting and obtaining upstream time; no host-startup wait dependency is added.

Check mode reports the proposed file/service changes and the current (possibly
unsynchronized) clock state without restarting Chrony or requiring synchronization.
Repeat the preview after applying to confirm no changes.

The syntax-only `-p` behavior is documented in the
[Chrony manual](https://chrony-project.org/doc/4.8/chronyd.html).

## Disable EEE on the physical WAN port

Use the existing host playbook's `wan_eee` action to disable Energy Efficient Ethernet
on the dedicated modem-facing NIC. The action derives the port from the firewall's
WAN bridge and `proxmox_network.guest_bridges` (currently `vmbr2` / `eno3`), then
checks its MAC and live bridge membership against inventory. It requires installed
`ethtool`, EEE support, and enabled ifupdown2 interface hooks.

```bash
./just playbook playbooks/configure-proxmox-host.yml --limit pve01 --check --diff \
  -e '{"proxmox_host_options":{"task_action":"wan_eee"}}'
./just playbook playbooks/configure-proxmox-host.yml --limit pve01 \
  -e '{"proxmox_host_options":{"task_action":"wan_eee"}}'
```

Apply installs `/etc/network/if-up.d/proxmox-wan-eee` and changes the current EEE
setting only if needed. The hook reapplies the setting when that physical interface
comes up, including after reboot, and skips interfaces other than the declared WAN.
Both paths avoid redundant EEE writes. The action verifies `EEE status: disabled`.
It performs no network reload or reboot and leaves bridge definitions unchanged.
Changing EEE may briefly renegotiate the WAN link and interrupt internet access.
Check mode only reads device state and previews changes; repeat it after applying
to check convergence.

This is a diagnostic experiment for WAN link instability, not a confirmed fix for
the gateway's apparent unsolicited restart. Observe subsequent link events and
gateway uptime. Direct readback:

```bash
ssh root@10.55.10.10 'ethtool --show-eee eno3'
```

To restore EEE at runtime and in the persistent hook:

```bash
./just playbook playbooks/configure-proxmox-host.yml --limit pve01 \
  -e '{"proxmox_host_options":{"task_action":"wan_eee"},"proxmox_host_wan_eee_enabled":true}'
```

The default is disabled; retain `proxmox_host_wan_eee_enabled: true` in host inventory
if future invocations should keep EEE enabled. If runtime application fails, the
hook remains installed with the requested setting; resolve the reported error and
rerun, or use the restore command above.
