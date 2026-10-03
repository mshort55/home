# Create the OPNsense VM

`playbooks/create-opnsense-vm.yml` stages the verified DVD ISO and creates VM 100 through `community.proxmox` over verified HTTPS. It allocates one 32 GiB system disk and one EFI variable disk on LVM-thin storage, attaches installation media and leaves the new VM stopped. It does not install the guest OS, start/stop a VM or change the switch/host network configuration.

## Prerequisites

- Run [ISO preparation](prepare-opnsense-iso.md) normally on the same controller first. VM creation requires its completion manifest and exact matching ISO bytes.
- Apply [the guest bridge configuration](configure-proxmox-bridges.md). Management must work, both data bridges must be up on the expected MACs, and they and their physical ports must have no host addresses.
- Run [Proxmox API enrollment](configure-proxmox-api.md) for `pve01` on this controller. Keep root SSH for physical NIC, runtime bridge, file checksum and local storage checks. Install the pinned collections and controller Python dependencies.
- The named ISO storage must be an active directory storage with `iso` content. Disk storage must be active LVM-thin storage with `images` content. VM ID 100 must be unused or already identify this workflow's matching QEMU VM on this host. Orphaned VM-100 volumes block fresh creation.

## Inventory and hardware

Define `opnsense_vm` on the Proxmox host. The allocation is deliberately bounded to the firewall design:

```yaml
opnsense_vm:
  vmid: 100
  name: opnsense01
  cores: 4
  memory_mib: 8192
  disk_gib: 32
  disk_storage: local-lvm
  iso_storage: local
  onboot: false
  wan_connected: false
  networks:
    - {device: net0, role: WAN, bridge: vmbr2, mac: '02:77:00:00:64:00'}
    - {device: net1, role: MGMT, bridge: vmbr1, mac: '02:77:00:00:64:01', tag: 10}
    - {device: net2, role: HOME, bridge: vmbr1, mac: '02:77:00:00:64:02', tag: 20}
    - {device: net3, role: DEV, bridge: vmbr1, mac: '02:77:00:00:64:03', tag: 30}
    - {device: net4, role: BMC, bridge: vmbr1, mac: '02:77:00:00:64:04', tag: 40}
```

Use unique locally administered MACs and retain them across repeat runs. Every guest NIC uses VirtIO and disables the Proxmox VM NIC firewall. Internal NICs have individual tags; the guest sees untagged Ethernet and does not create additional VLAN subinterfaces for these four connections.

The VM uses Q35, OVMF UEFI without pre-enrolled Secure Boot keys, CPU type `host`, one socket, fixed RAM with ballooning disabled, VirtIO SCSI Single and `cache=none` with an I/O thread. Discard remains disabled. Boot uses the modern explicit order `scsi0;ide2`: an installed system disk takes priority over the DVD. Startup order is 1, with 30 seconds before the next VM starts and a 120-second shutdown timeout. Automatic host-boot startup is disabled during installation; enabling it after bootstrap is a separate reviewed setting.

## Preview and create

```bash
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01 --check
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01 --check
```

The first preview reads the host and local ISO, checks bridges/storage/ID availability, and reports the desired hardware and network definitions. It uploads no ISO and allocates no disks. A normal creation uploads the ISO with `proxmox_template`, checks its remote SHA-256 and size, then invokes `proxmox_kvm` once. `proxmox_vm_info` reads current and pending configuration and `proxmox_nic` applies the bounded WAN link transition. Readback validates ownership, hardware, disk ownership/size, NIC mappings, boot order and stopped state. The repeat preview should report `changed=0`.

An existing matching VM is verified rather than recreated. Its disks are never reformatted, resized or replaced by this playbook. An ejected/removed DVD is accepted and not reattached. A running VM is not stopped. The named bootstrap DVD produced by the installation workflow is also accepted, without reattaching it. With `opnsense_verify_only: true`, an existing matching VM is required and all staging/creation/WAN mutations are skipped; the installation playbook uses this mode for its preflight. Conflicting hardware, an unrelated ownership marker, extra devices or pending VM configuration changes cause failure before writes. `scripts/validate-opnsense-vm.py` compares parsed properties rather than relying on their printed order.

The [management pilot workflow](configure-opnsense-pilot.md) additionally uses `opnsense_verify_wan_state: false` during its read-only preflight. This permits a planned WAN link difference while still validating all other hardware. The default is `true`, which requires the desired WAN state to match during verification-only use. Interface-assignment confirmation applies to WAN writes, not to a read-only preflight.

## Installation and interface assignment

For an automated install, use [bootstrap media preparation](prepare-opnsense-bootstrap.md) and [the installation playbook](install-opnsense.md). For a manual install, use the trusted Proxmox web interface to start VM 100 and open its graphical console. The physical server VGA screen shows the host, not the VM's display. Follow [OPNsense's DVD installer instructions](https://docs.opnsense.org/manual/install.html#opnsense-installer): log in to the live installer with `installer` / `opnsense`, select the single 32 GiB guest system disk and set a new root password locally. The EFI variable disk is not an additional guest installation disk.

The WAN vNIC is disconnected during initial creation. Keep it disconnected until console assignment identifies WAN and MGMT/LAN by their recorded MACs. Set MGMT as LAN; assign HOME/DEV/BMC to the remaining explicit-tag NICs. Do not rely on assumed `vtnet` numbering or default assignments. Set the real private gateway addresses in the console, with IPv6 disabled. When WAN uses the existing household subnet for the pilot, HOME must use the distinct pilot subnet rather than that WAN subnet.

Guest network/services configuration is a separate bootstrap phase. Follow [OPNsense virtual installation guidance](https://docs.opnsense.org/manual/virtuals.html) for disabling hardware offloads after installation. Use the MGMT path for administration; no WAN management rule is needed.

## Connect or disconnect the pilot WAN through the playbook

Fresh creation requires `wan_connected: false`. After verifying guest interface assignments, change only `opnsense_vm.wan_connected` to `true` in private inventory. Preview and apply with an explicit console-assignment confirmation:

```bash
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01 --check \
  -e '{"opnsense_wan_assignment_confirmed":true}'
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01 \
  -e '{"opnsense_wan_assignment_confirmed":true}'
```

For an existing owned VM, the only configuration change this entry point supports is its WAN link state. All other NIC/hardware settings must still match before `qm set --net0` is allowed. Confirmation is required only when changing a disconnected WAN to connected; it is unnecessary on converged repeats. Setting `wan_connected: false` disconnects WAN through the same playbook without a confirmation override. Neither transition starts or stops the VM.

## Interrupted creation

If ISO upload succeeded but creation did not, rerunning reuses the verified ISO. If the VM exists with matching hardware, rerunning verifies it and makes only a requested WAN link transition. If creation left an orphaned volume, an incomplete VM or pending configuration, the workflow stops for explicit inspection; it never automatically destroys a VM or deletes a volume. Preserve the failure output and inspect the named VM/storage before choosing recovery.
