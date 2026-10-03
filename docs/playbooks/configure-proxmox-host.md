# Configure Proxmox host repositories and updates

`playbooks/configure-proxmox-host.yml` manages the installed standalone Proxmox VE 9 host's signed package repositories and optionally applies package upgrades. `community.proxmox` verifies the node and firewall VM through trusted HTTPS. `ansible.builtin.deb822_repository` owns repository files and `ansible.builtin.apt` handles indexes and upgrades over existing trusted root SSH; the Proxmox collection does not provide these package-management operations.

## Prerequisites and inventory

Complete [Proxmox API enrollment](configure-proxmox-api.md), host bridges, OPNsense installation and the [management pilot](configure-opnsense-pilot.md). The owned firewall VM must be running with no pending hardware changes and its WAN connected. The host needs its management DNS/gateway and outbound HTTP/HTTPS access for repositories.

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

Repository/index setup is the default operation and installs no host package upgrades:

```bash
ansible-playbook playbooks/configure-proxmox-host.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-host.yml --limit pve01
```

The normal run refreshes signed indexes after repository changes. Otherwise it reuses the cache for `proxmox_host_cache_valid_time` seconds, default 3600. Override with `-e '{"proxmox_host_cache_valid_time":0}'` to request a fresh refresh. Check mode does not refresh indexes or modify repositories.

Once repository setup passes, explicitly preview and apply updates:

```bash
ansible-playbook playbooks/configure-proxmox-host.yml --limit pve01 \
  -e '{"proxmox_host_upgrade":true}' --check
ansible-playbook playbooks/configure-proxmox-host.yml --limit pve01 \
  -e '{"proxmox_host_upgrade":true}'
```

Upgrade mode refuses unconverged repository files; apply the default setup operation first. Its check-mode package preview uses the existing indexes and cannot predict packages published after that refresh. The normal upgrade refreshes expired indexes before applying updates, so its package set may differ from an older preview.

The APT task uses a full dependency-resolving upgrade within the configured release, with `fail_on_autoremove: true`, no automatic cleanup, no downgrades and no unauthenticated packages. Existing modified configuration files retain their installed contents using `force-confdef,force-confold`. Refused removals or held/conflicting packages need a separately reviewed resolution. Unattended major OS/PVE/Ceph release upgrades are outside this workflow. [Ansible APT module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/apt_module.html).

## Verification and reboot status

After normal repository or package work, the playbook checks source convergence, the Proxmox meta-package, package health, and identical hashes for Debian sources, host network files and storage definitions, plus an unchanged management default route. It verifies Proxmox services and trusted API access, and requires the firewall VM to retain identical current/pending configuration and running power state. It sends no VM start/stop or host network reload request. Package installation scripts may restart host services; API checks retry while they return.

The report includes the running kernel, newest installed Proxmox kernel and whether a newer kernel or Debian reboot marker indicates pending reboot work. It performs no host reboot. Plan any required reboot as separate maintenance with console recovery and verified firewall startup behavior; the pilot's firewall may still have automatic startup disabled.

A repeat run converges repository files and packages. Cache refresh can report a change when its age expires. An immediate repeated upgrade preview should report no package changes after successful application, unless repository content or installed state changed meanwhile.

If a run fails, preserve its output and reported source backup. Repository recovery consists of restoring the saved files and removing a newly created `proxmox.sources` only if it was absent in that backup, then refreshing APT indexes. Repository recovery does not undo installed packages. Reconcile the cause through the playbook or a reviewed maintenance workflow before repeating upgrades.
