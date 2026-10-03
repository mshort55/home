# Prepare the OPNsense ISO

`playbooks/prepare-opnsense-iso.yml` runs locally on the Ansible controller. It downloads the pinned amd64 DVD image, verifies its compressed SHA-256, decompresses it and verifies the uncompressed ISO's OpenSSL signature before making it available for VM creation.

## Release and trust

`files/opnsense/release.yml` locks the version, filenames, download origin, compressed checksum, public-key checksum and release announcement. `files/opnsense/26.7.pub` contains the release signing key from that announcement. The public key and checksum are published in the [OPNsense release repository](https://github.com/opnsense/changelog/blob/5a18f785fc5d5817d21d8fb6a233476ffee8546a/community/26.7/26.7); verification follows the [official installation guide](https://docs.opnsense.org/manual/install.html#download-and-verification). A mirror's unsigned checksum file alone is not used to establish trust.

Updating the release requires reviewing its announcement and signing key, updating the lock and rerunning preparation. This workflow does not automatically follow a newer version. Installed firewall updates are separate from installation media preparation.

## Prerequisites and output

Use the repository's Ansible environment on Linux or native macOS. The controller needs Internet access, `openssl` on PATH and space for the compressed image, decompressed ISO and temporary verification files. During regeneration, an existing ISO may coexist with its replacement. No Proxmox connection or password is needed.

Output defaults to `{{ inventory_dir }}/.cache/iso/opnsense-<version>/`:

| File | Purpose |
|---|---|
| `OPNsense-<version>-dvd-amd64.iso.bz2` | Compressed release image, checked against the pinned SHA-256 |
| `OPNsense-<version>-dvd-amd64.iso.sig` | Base64 signature of the uncompressed image |
| `OPNsense-<version>-dvd-amd64.iso` | Verified installation ISO |
| `completion.json` | Release, archive/key digests, ISO digest/size and successful signature verification |

The cache directory is private, mode 0700; files are mode 0600. Output paths are derived from `inventory_dir`, so a shared checkout works from either controller platform without embedding a Linux-only path in the manifest. `opnsense_iso_cache` can override the cache directory; supply the same value to VM creation.

## Commands and repeat runs

```bash
ansible-playbook playbooks/prepare-opnsense-iso.yml --limit pve01 --check
ansible-playbook playbooks/prepare-opnsense-iso.yml --limit pve01
```

Check mode validates the release lock and local public key, then describes the work. It performs no downloads, decompression or signature verification and creates no completion manifest. Run normally before using the ISO.

A normal repeat checks the archive hash and ISO signature again. A valid existing ISO is reused, and unchanged files/manifest produce `changed=0`. `scripts/prepare-opnsense-iso.py` prepares a replacement in a temporary directory and atomically renames it only after successful signature verification. Symlink image/manifest inputs are refused. A corrupt regular ISO can be regenerated from the verified archive; a failed signature never replaces the existing ISO.

The repository-wide Vault prompt can appear even though this playbook loads no Vault credentials. Enter the password locally or disable that prompt for this credential-free command.

Continue with [VM creation](create-opnsense-vm.md).
