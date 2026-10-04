# Headless Fedora development VM

`fedora_dev` prepares and provisions VM 200; `fedora_host` configures/verifies its guest baseline through SSH. Every role requires an explicit action. The allocation is 4 vCPU, 8 GiB RAM and 80 GiB on existing storage, with one VirtIO NIC tagged DEV 30. Inventory owns the static address, gateway/DNS, hostname, domain and SSH user. Automatic startup is disabled. Provisioning starts the initial installation; completed reruns respect a deliberately stopped VM.

## Preparation and creation

Use the same controller checkout for preparation, creation and guest trust. Set `fedora_dev_vm.ssh_public_key_files` to approved Ed25519 public key files; never supply private keys. The controller needs Python 3.11+, `gpgv` and `ssh-keygen`, plus repository dependencies.

```bash
ansible-playbook playbooks/prepare-fedora-dev.yml --limit pve01 --check
ansible-playbook playbooks/prepare-fedora-dev.yml --limit pve01
ansible-playbook playbooks/configure-proxmox-api.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-api.yml --limit pve01
ansible-playbook playbooks/create-fedora-dev-vm.yml --limit pve01 --check
ansible-playbook playbooks/create-fedora-dev-vm.yml --limit pve01
ansible-playbook playbooks/verify-fedora-dev-vm.yml --limit pve01
```

Enable/verify [DEV routing](configure-opnsense-lab.md) before creation. Refresh and activate WireGuard before guest SSH. Preparation is local. Creation reaches Proxmox and the firewall; first-boot verification uses the authenticated hypervisor guest agent instead of a MGMT-to-DEV SSH allowance.

API enrollment supports a controlled upgrade from the exact previous owned role to add `VM.Config.Cloudinit`, preserving the original token and rejecting arbitrary privilege drift. Rerun enrollment before cloud-init VM creation.

`prepare-fedora-cloud.py` verifies the official Fedora Cloud Base Generic 44-1.7 x86_64 image using the signed release checksum, pinned Fedora 44 signing fingerprint and pinned image SHA-256. Protected artifacts live in `.cache/fedora-cloud`; mismatched existing files are refused. See [Fedora verification](https://fedoraproject.org/cloud/download/).

Preparation creates a stable guest Ed25519 host key and private cloud-init seed under `.cache/fedora-dev/dev01`, pinning its public key in a dedicated `known_hosts` before any SSH connection. Cloud-init installs Python, SSH, firewalld and the guest agent, provisions the named key-only user with administrative sudo, restricts SSH to the laptop tunnel /32, retains SELinux enforcement and disables root/password SSH and IPv6.

Creation records allocation and seed digest before writes. An existing VM needs that matching protected record and exact hardware, without pending changes, extra NICs, passthrough, extra disks or unattached volumes. Missing completed VMs are not recreated. Pending installs resume using their recorded disk/seed; a changed seed is refused.

`community.proxmox` handles VM allocation, disk growth and power. The image import uses bounded root SSH because absolute-path import is unavailable to the existing non-root API token. Dedicated node-local snippet-only storage is registered through root SSH without adding storage-administration permissions to the token or modifying existing storage. The seed contains a host private key and is protected on controller and hypervisor.

## Guest baseline and access

With the refreshed WireGuard profile active:

```bash
ansible-playbook playbooks/configure-fedora-dev-host.yml --limit dev01 --check
ansible-playbook playbooks/configure-fedora-dev-host.yml --limit dev01
ansible-playbook playbooks/verify-fedora-dev-host.yml --limit dev01
ansible-playbook playbooks/verify-fedora-dev-connectivity.yml --limit dev01
```

The guest role verifies identity, named-user key-only SSH, SELinux, services, permanent/runtime firewall policy, IPv4-only operation and cloud-init completion. Applications require explicit guest firewall openings even though the routed tunnel permits DEV workload ports.

For native Mac SSH, use `ssh -o UserKnownHostsFile=<checkout>/.cache/fedora-dev/dev01/known_hosts mjs@10.55.30.10` with an approved key. Verify guest DNS/public HTTPS and blocked guest-initiated MGMT/BMC/HOME/WG connections. Tunnel-off must deny lab access again; port 8 uses the same policy through the wired profile.

## Explicit power operations

```bash
ansible-playbook playbooks/stop-fedora-dev-vm.yml --limit pve01
ansible-playbook playbooks/start-fedora-dev-vm.yml --limit pve01
```

Power operations require the completed owned install. Stop is graceful without forced termination. VM deletion and image replacement are outside these workflows; disabling DEV routing preserves its disk.

Before `reboot-proxmox-host.yml`, explicitly stop DEV with `stop-fedora-dev-vm.yml`. Startup-only host verification accepts the completed running guest; a host reboot requires it stopped and leaves it stopped under the manual-start policy.
