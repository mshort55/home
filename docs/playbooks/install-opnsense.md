# Install OPNsense through Ansible

`playbooks/install-opnsense.yml` installs ZFS on the single empty 32 GiB disk of the owned OPNsense VM, then boots and verifies the installed system over pinned SSH. It uses Proxmox's root SSH connection for VM operations and the guest's inventory SSH connection for the vendor installer components. It requires no guest Python or Proxmox API token and does not use simulated console keystrokes.

## Prerequisites

- Create the VM using [create-opnsense-vm.yml](create-opnsense-vm.md).
- Prepare [private bootstrap media](prepare-opnsense-bootstrap.md) on the same controller.
- Keep the five VM MACs/bridges/tags unchanged, WAN disconnected and automatic startup disabled.
- The first installation requires a stopped VM, no previous installation record, an owned 32 GiB system disk and zero bytes at both the first and last 2 MiB of that disk. Inside the live guest, the installer also requires exactly one non-optical disk, `da0`, with the expected size and no existing partition table.
- The controller must reach both Proxmox and the guest's management subnet and possess a private key corresponding to a public key included in the seed. Standard Ansible SSH key selection applies; specify `ansible_ssh_private_key_file` in private inventory if needed.

## Preview and install

```bash
ansible-playbook playbooks/install-opnsense.yml --limit pve01 --check
ansible-playbook playbooks/install-opnsense.yml --limit pve01
ansible-playbook playbooks/install-opnsense.yml --limit pve01
```

The initial imported VM workflow runs in verification-only mode: it requires an existing matching VM, reads its hardware/bridges/storage and makes no ISO upload, allocation or WAN change. The installation preview verifies the bootstrap manifest, existing VM, record ownership, media conflicts and first-install disk guards, then reports the bounded operation, current media and whether the stopped guest needs its bootstrap DVD mounted. It makes no trust-file, ISO, VM, guest or disk writes. Check mode is a host/artifact preflight; it does not prove the guest OS is installed or reauthenticate its SSH service. Use the normal repeat run for full installed-system verification.

A normal first run:

1. Pins the generated guest ED25519 host key into a dedicated private `known_hosts` file. This is the known key embedded in the verified seed, rather than an unverified network scan. SSH host-key checking stays enabled.
2. Writes a protected installation intent on Proxmox before changing VM media or power; stages and verifies the exact private DVD, then mounts it on the stopped VM and starts it.
3. Waits for MGMT SSH and validates the live filesystem, seed identity, all five MAC-to-role mappings, address and SSH host key.
4. Runs the installed vendor `bsdinstall opnsense-zfs`, clone, boot configuration and entropy components without interactive dialogs. The layout is a ZFS stripe with 2 GiB swap on the single virtual disk. Unexpected error dialogs fail the operation. Existing partitions are never destroyed by the wrapper.
5. Marks the target only after those components succeed and records the completed disk write on Proxmox. The playbook requests a clean ACPI shutdown through Proxmox with a 300-second timeout and forced stopping disabled, verifies that the VM is stopped, ejects the DVD, starts the disk and waits for SSH.
6. Verifies the ZFS root, installation marker, NIC mappings, SSH access, hardware, running state and disconnected WAN before recording completion.

No UI steps are required for this workflow. HTTPS trust for the generated GUI certificate is separate from the SSH trust established here. Keep the existing household gateway and DHCP service in place. Do not connect WAN until interface assignment and the firewall's pilot policy are verified.

The example inventory also selects the generated dedicated trust file for subsequent guest SSH playbooks. If using a custom bootstrap artifact directory, update that guest's `ansible_ssh_common_args` to select its `known_hosts` file for subsequent workflows; installation's own delegated SSH tasks use `opnsense_bootstrap_dir` directly.

## Repeat runs and interrupted installation

A completed normal repeat verifies the owned installed system and reports no changes while it remains running and its protected files match. It does not repartition, reinstall, reset credentials or reattach installation media. If a completed VM is stopped, this installation entry point starts it to perform the required SSH verification.

Proxmox records are stored in `/var/lib/home-automation/opnsense-100/install.json`, beneath a root-owned mode-0700 directory, with mode-0600 files. The record identifies the exact seed and system volume and distinguishes started, disk-written and verified-complete phases. The installed guest has `/conf/ansible-install.json`; its inspection code compares that marker with the embedded intent and actual configuration.

A repeated run can resume a recorded live system before partitioning or verify a recorded installation that already boots from disk. When the matching record is `disk_written`, it skips the disk installer even if the guest still runs from the live DVD, requests clean shutdown, ejects the DVD and boots the written disk. If that recorded VM is already stopped, it ejects remaining installation media before starting the disk. Rerun the same installation command; no media rebuild or manual power operation is required.

A live session with a partitioned disk or an installation lock but no recorded completed disk write fails rather than formatting again. A stopped, recorded system is booted disk-first; a successful target can be verified even if the controller was interrupted before recording completion. Media changes are only made on a stopped VM. A different seed, conflicting hardware, unowned disk, unexpected root filesystem or completed record pointing to a live DVD causes failure.

Preserve the failure output and installation records for inspection. Guest installer diagnostics are `/var/log/ansible-install.log` and `/var/log/installer.log`. Do not delete records or partitions merely to force a rerun. The workflow does not erase an incomplete installation or provide an automatic reinstall operation.

The guest remains at a management bootstrap: HOME/DEV/BMC disabled, no configured DHCP/DNS or forwarding policy, WAN link disconnected. Configure those services through a separate Ansible workflow after installation verification.
