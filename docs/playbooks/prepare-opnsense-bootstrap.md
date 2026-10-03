# Prepare OPNsense bootstrap media

`playbooks/prepare-opnsense-bootstrap.yml` verifies the vendor DVD through `prepare-opnsense-iso.yml`, then creates a private DVD with inventory-owned management access. It runs locally and does not contact Proxmox or a firewall. Booting the prepared DVD starts a live system; it does not automatically format a disk. Use [the installation playbook](install-opnsense.md) for that operation.

## Inputs

Set `opnsense_guest: opnsense01` on the Proxmox host. Define that guest under `opnsense_hosts`, with `opnsense_proxmox_host: pve01`, `ansible_user: root`, its management `ansible_host`, and:

```yaml
opnsense_bootstrap:
  filesystem: zfs
  hostname: opnsense01
  domain: lab.home.arpa
  timezone: Etc/UTC
  prefix: 24
  ssh_public_key_files:
    - "{{ inventory_dir }}/.cache/proxmox-installer-inputs/admin.pub"
```

Keep the VM's five ordered NIC roles and MACs in `opnsense_vm` on its Proxmox host. WAN must remain disconnected. The management address belongs to the LAN/MGMT network; it must be unused and different from the Proxmox address. No management DHCP server is started.

Use `ansible-vault edit secrets/vault.yml` to add this entry alongside existing credentials:

```yaml
vault_devices:
  opnsense01:
    username: root
    password: '<new private root/UI password>'
```

Use 12–72 UTF-8 bytes, without newlines. The builder hashes the password with bcrypt; it is supplied through stdin, with task output and diffs suppressed. The plaintext password is not written into the DVD or local settings. SSH accepts public keys only; the password is for the console and web UI.

A Linux Docker or Podman engine must be running on the controller. The builder supports Linux and native macOS and runs as the controller UID, with no network, capabilities or writable container root. Its Debian base is digest-pinned. Set `opnsense_container_runtime: podman` if needed. The initial image build and vendor download require Internet; media construction uses the cached, signature-verified DVD.

## Run

```bash
ansible-playbook playbooks/prepare-opnsense-bootstrap.yml --limit pve01 --check
ansible-playbook playbooks/prepare-opnsense-bootstrap.yml --limit pve01
```

The preview validates inputs, Vault structure and configured public-key files. It does not hash a password or build media. The normal run generates three private SSH host keys and seeds the complete set required by OPNsense. An early live-media hook resolves guest interface names from their exact MACs before the OPNsense boot configuration runs. LAN/MGMT receives the inventory address; WAN is DHCP-configured but its hypervisor link stays disconnected. HOME/DEV/BMC are assigned but disabled. IPv6, DHCP/DNS services and outbound NAT are not enabled by the bootstrap. Management may access the firewall itself; there is no internal forwarding policy.

The resulting system enables key-only root SSH on MGMT, keeps HTTPS for the UI and disables checksum, segmentation and large-receive offloads using OPNsense's interface settings. Firewall policy, DNS, DHCP, updates and GUI certificate trust are separate configuration workflows.

## Artifacts and repeat behavior

Default directory: `.cache/opnsense-bootstrap/<Proxmox inventory name>`, mode 0700. Files are mode 0600 and Git-ignored:

- `opnsense-bootstrap.iso`: private installation media containing password hash and SSH host private keys.
- `completion.json`: exact source/derived checksums, seed identity, intended NICs/address and generated SSH public key.
- `ssh-host-key.pub`: the guest's ED25519 public host key.
- `settings.json` and `password-hash`: private builder inputs.

The builder preserves the original EFI FAT image bytes and creates an explicit UEFI boot catalog. It verifies the embedded configuration, EFI bytes and boot catalog before writing a completion record. The derived DVD is locally modified media; its provenance is the verified original plus recorded builder inputs, rather than a vendor signature on the derived bytes.

Identical inputs/password and intact output reuse the same ISO and host keys, reporting no changes. Changing the password, settings, script or source, or corrupting a completed ISO, is refused. A new seed requires a new `opnsense_bootstrap_dir`; use the same override for preparation and installation. Do not replace the seed of an existing installation to perform ordinary configuration changes. The installation record deliberately rejects a different seed.

Keep the artifacts protected like a system backup. Possession of their SSH host private keys allows impersonating this guest. Never share or commit the DVD, keys, hash or settings.

References: [OPNsense installation](https://docs.opnsense.org/manual/install.html), [virtual machine guidance](https://docs.opnsense.org/manual/virtuals.html), [vendor scriptable installer](https://github.com/opnsense/installer).
