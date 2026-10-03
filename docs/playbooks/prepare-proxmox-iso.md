# Prepare a Proxmox unattended installation ISO

Playbook: [prepare-proxmox-iso.yml](../../playbooks/prepare-proxmox-iso.yml).

Build a private ISO with embedded installation answers using the official `proxmox-auto-install-assistant`. Preparation changes local files and container images only. Mounting and booting use separate workflows. Booting the resulting ISO starts an unattended installation that formats the disk selected by its exact serial.

## Prerequisites and inputs

Run locally from the repository on Linux or a native Mac, as an ordinary user. A running Docker engine is required by default; set `pve_container_runtime=podman` for Podman. The engine must execute `linux/amd64` containers and access bind-mount paths from this checkout. Docker-outside-Docker setups must expose the same paths to the engine. On Apple Silicon or another ARM controller, AMD64 execution needs the engine's emulation support.

The first run builds [the preparation image](../../containers/proxmox-installer/Dockerfile) and requires internet access. It pins the Debian base image by digest and the preparation assistant to version 9.2.8. The Proxmox signing key is fetched over verified HTTPS and checked against the published SHA-256; APT validates repository signatures and package checksums. A cached builder is reused based on the Dockerfile checksum. Debian dependency versions follow that image build's signed repositories; this is not a fully reproducible package snapshot. All subsequent ISO-generation commands run without network access, as the invoking user, with a read-only container root filesystem and read-only source ISO/helper mounts.

Configure `proxmox_install` on the Proxmox host, such as `pve01`, in the `proxmox_hosts` inventory group. Set that host's `proxmox_idrac_host` to its management controller's inventory name, such as `idrac01`. The Proxmox inventory retains its management address and SSH connection settings for later provisioning; this preparation playbook explicitly overrides its connection and Python interpreter to run locally before the server has an OS. It sends no requests to either device. Use [inventory.example.yml](../../inventory.example.yml) for the complete structure:

```yaml
proxmox_install:
  source_iso: "{{ inventory_dir }}/.cache/iso/installer.iso"
  source_sha256: '<verified original ISO SHA-256>'
  fqdn: pve01.lab.home.arpa
  mailto: admin@example.test
  country: us
  keyboard: en-us
  timezone: UTC
  cidr: 10.77.10.10/24
  gateway: 10.77.10.254
  dns: 10.77.10.254
  disk_serial: '<exact observed ID_SERIAL>'
  management_mac: '02:00:00:00:00:10'
  maxroot: 96
  swapsize: 8
  minfree: 32
  ssh_public_key_files:
    - "{{ inventory_dir }}/.cache/proxmox-installer-inputs/admin.pub"
```

Obtain the disk's `ID_SERIAL` using `udevadm info -q property -n /dev/<observed-disk>`. The logical RAID disk's identity is distinct from the RAID controller and physical member identities. Match the management NIC's observed MAC to its cabling. The answer uses `filter.ID_SERIAL` and `filter.ID_NET_NAME_MAC`, with exact values and no wildcard disk selection. Confirm those filters in the installer environment before booting the unattended ISO. Management selection does not configure the remaining NICs or guest bridges; those are configured after installation over SSH.

Storage uses ext4 on the existing logical disk with LVM-thin. `maxroot`, `swapsize` and `minfree` are in GiB. `hdsize` and `maxvz` are omitted to retain the full detected disk capacity and automatic thin-pool sizing. The ISO changes logical-disk partitions; it does not create or change the controller's RAID configuration.

Store this credential entry under the existing `vault_devices` mapping in encrypted `secrets/vault.yml`, using [Ansible Vault](../credentials.md):

```yaml
pve01:
  username: root
  password: '<chosen root password>'
```

The Vault key must match the Proxmox inventory hostname (`pve01` in this example). Passwords need at least eight characters and cannot contain NUL or newlines. The password is passed over the container's standard input with task output and diffs suppressed. It is never placed in a container argument, environment variable, build layer or settings file. The helper hashes it with yescrypt and embeds only the hash in `root-password-hashed`. Specified `.pub` files are read and embedded as `root-ssh-keys`; no private key is read or copied.

## Preview and prepare

From the activated local Ansible environment at the repository root:

```bash
ansible-playbook playbooks/prepare-proxmox-iso.yml --limit pve01 --check
ansible-playbook playbooks/prepare-proxmox-iso.yml --limit pve01
```

Vault prompts locally. No sudo password is needed. Check mode verifies the original file checksum, reads the selected public keys and checks the container engine/cache. It does not build images, hash the password, validate the full answer schema or generate artifacts.

A normal run allocates a new directory under `.cache/proxmox-installer/`. It validates the rendered answer with the pinned assistant, creates a new ISO, extracts and compares its embedded answer, verifies its embedded answer-fetch mode and UEFI boot catalog, confirms the original ISO remains unchanged and independently verifies the result checksum. Existing build artifacts are not overwritten. Repeated normal runs produce separate builds with independently salted password hashes.

Private directories use mode 0700 and files use mode 0600. Output includes:

- `settings.json`: installation settings and public keys; no password or hash.
- `answer.toml`: validated installation answers, public keys and password hash.
- `proxmox-auto.iso`: prepared boot media containing those answers.
- `build.log` and `runner-result.json`: private preparation diagnostics.
- `verification/`: answers and mode file extracted from the finished ISO.
- `completion.json`: verified checksums, identities, tool version and boot/answer checks.
- `mount-vars.yml`: portable ISO path and checksum inputs for the mount playbook, generated only after verification.

Treat the answer and ISO as sensitive credential material. Completion verifies the build, not successful server boot or installation. If preparation fails, the reported directory retains diagnostics; it does not produce verified mount inputs. Correct the error and run again to allocate a fresh directory.

## Use the prepared image

The completion report includes `idrac_host`, taken from the Proxmox host's `proxmox_idrac_host` association. Use that controller as the limit for the mount workflow. Keep the original mounted ISO available while a discovery shell needs it. Once that environment has shut down, eject the original image using its original mount inputs:

```bash
ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --ask-become-pass \
  -e idrac_iso_operation=eject
```

Mount the prepared image from the native Mac using the new build's reported `mount-vars.yml`:

```bash
ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --ask-become-pass \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml
```

The generated path is relative to `inventory_dir`, so the same shared checkout can be prepared in a Linux dev container and mounted from its native Mac location. Keep the ISO server running while the installer reads media. Review the disk filter, network settings and public key before selecting the prepared DVD for boot. The prepared ISO selects unattended installation automatically; no per-setting installer UI review should be assumed.

After mounting, automate one-time virtual DVD boot and power on with [boot-idrac-iso.yml](boot-idrac-iso.md). The server must be off. Run the preview first, then the normal boot operation using the same generated inputs:

```bash
ansible-playbook playbooks/boot-idrac-iso.yml --limit idrac01 --check \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml
ansible-playbook playbooks/boot-idrac-iso.yml --limit idrac01 \
  -e @.cache/proxmox-installer/<build-directory>/mount-vars.yml
```

A planned gateway/DNS may be configured before that gateway is operational. Same-subnet wired access to the installed management address works without it; internet-dependent provisioning must wait for the management gateway. Preserve local console access and establish SSH host-key trust before the first automated SSH connection.

Syntax validation without unlocking the real Vault:

```bash
ANSIBLE_ASK_VAULT_PASS=False ansible-playbook \
  -i inventory.example.yml playbooks/prepare-proxmox-iso.yml \
  -e vault_file=/dev/null --syntax-check
```

References: [Proxmox preparation tool](https://github.com/proxmox/pve-installer/tree/master/proxmox-auto-install-assistant), [official answer examples](https://github.com/proxmox/pve-installer/tree/master/proxmox-auto-installer/tests/resources/parse_answer), [Proxmox signed repositories and key checksum](https://github.com/proxmox/pve-docs/blob/master/pve-package-repos.adoc), [unattended installation](https://pve.proxmox.com/wiki/Automated_Installation).
