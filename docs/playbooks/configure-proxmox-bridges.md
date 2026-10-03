# Configure Proxmox guest bridges

`playbooks/configure-proxmox-bridges.yml` adds guest bridges to an installed Proxmox host over root SSH. It creates `/etc/network/interfaces.d/ansible-guest-bridges`, leaving `/etc/network/interfaces` unchanged. It activates changes with `ifreload --all`, the [Proxmox documented method for applying manual network configuration](https://github.com/proxmox/pve-docs/blob/master/pve-network.adoc).

## Prerequisites

- Run [Proxmox API enrollment](configure-proxmox-api.md) for `pve01` on this controller first.
- Proxmox is installed with ifupdown2 and a working management bridge. Establish SSH host-key trust and install the administration machine's public key for root first.
- The management bridge uses the installer configuration: static address and gateway, one physical port, STP off and forwarding delay zero.
- `/etc/network/interfaces` includes `source /etc/network/interfaces.d/*`. Other snippets and unrelated auto interfaces require separate review; this workflow refuses them.
- Each guest NIC has its observed MAC address, an existing `inet manual` stanza with no extra settings, no global address and no conflicting bridge membership.
- Switch access/trunk configuration and cabling match the inventory. A VLAN-aware guest bridge requires a corresponding switch trunk; the plain WAN bridge requires the upstream access port.
- There is no pending Proxmox GUI network configuration at `/etc/network/interfaces.new`. Bridge configuration changes and runtime repairs are refused once VM or container configuration files exist. Converged repeat runs can verify an existing configuration with guests present.
- Have console access available when applying network configuration.

The workflow installs no packages and needs no Internet access. It authenticates with an existing SSH key and does not load device passwords from Vault. The repository-wide Vault prompt still appears unless disabled for this command.

## Inventory

Define `proxmox_network` on the Proxmox host in the private inventory. The management fields describe the installed configuration for verification; this playbook does not change them.

```yaml
proxmox_network:
  management:
    bridge: vmbr0
    port: eno1
    mac: '02:00:00:00:00:10'
    address: 10.77.10.10/24
    gateway: 10.77.10.254
  guest_bridges:
    - name: vmbr1
      port: eno2
      mac: '02:00:00:00:00:11'
      vlan_aware: true
      vlans: [10, 20, 30, 40]
    - name: vmbr2
      port: eno3
      mac: '02:00:00:00:00:12'
      vlan_aware: false
```

Use the real observed MACs in private inventory. Guest bridges have no host IP address or gateway. Their persistent `disable-ipv6 yes` setting suppresses host IPv6, including link-local addresses, through the installed ifupdown2. Readback requires no addresses on either guest bridge or its physical port. Set VLAN tags on guest NICs attached to the VLAN-aware bridge. Guests attached to the plain WAN bridge send untagged traffic, which the switch maps to its access VLAN.

`bridge-vids` specifies the tagged VLANs. Linux bridges may retain their default untagged PVID 1; the switch trunk must exclude VLAN 1 and use an unused native VLAN to keep untagged traffic off the physical LAN trunk.

## Commands

From the repository root, preview first:

```bash
ansible-playbook playbooks/configure-proxmox-bridges.yml --limit pve01 --check --diff
```

Check mode reads configuration, checks identities and parses the candidate using the installed ifupdown2. It reports the proposed file and does not write network configuration or reload networking. Apply:

```bash
ansible-playbook playbooks/configure-proxmox-bridges.yml --limit pve01
```

A repeat preview should report `changed=0` after a successful apply. A normal converged run checks the running bridge state without reloading. If the owned file matches but its running state differs, the playbook detects that drift and reapplies the persistent definitions. This also permits recovery when an earlier run wrote the file but did not finish the reload; no separate correction command is required.

## Application and verification

Before a change, the playbook saves the main file and any previous owned snippet under a fresh `/root/ansible-network-*` directory with private permissions. It reports that path before writing. It validates the snippet, writes it, starts a bounded asynchronous `ifreload --all` and waits for management SSH to return.

Readback checks the reload result, `ifquery --check` (including IPv6 disablement), bridge administrative state, VLAN filtering, physical port membership, MACs and absence of all addresses on guest bridges and their physical ports. It also requires the main network file's SHA-256 to be unchanged. Physical carrier and connectivity through a guest require separate checks once guests exist.

## Recovery and subsequent editing

If SSH does not return, use the console and inspect the reload error. The playbook leaves recovery files and the attempted snippet available; it does not automatically roll back or reboot.

To revert the first creation, remove `/etc/network/interfaces.d/ansible-guest-bridges` and run `ifreload --all` from the console. If a snippet existed previously, restore `ansible-guest-bridges` from the reported recovery directory first. Restore the saved `interfaces` file only if it was subsequently changed. Reverting bridges with attached guests interrupts their networking.

Keep these bridge definitions in the owned snippet. If editing networking through the Proxmox GUI, inspect its pending file and reconcile definitions before using this playbook again. Duplicate definitions, unrelated snippets and pending GUI changes require explicit network maintenance outside this bootstrap workflow.

## Community API and file ownership

`community.proxmox.proxmox_node_network_info` checks pending API changes and management identity. The writer remains an owned ifupdown2 snippet. `proxmox_node_network` stages and applies the node-wide network configuration; using it here would move definitions into the main file and break the guarantee that the installer management file stays unchanged. Changing that ownership with attached guests requires a separate network maintenance workflow. Live MAC/address/VLAN checks continue through SSH.
