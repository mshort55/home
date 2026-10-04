# Configure Proxmox API access

`playbooks/configure-proxmox-api.yml` enrolls a scoped Proxmox API token through existing trusted root SSH, exports its cluster CA and private credentials to this controller, and verifies access with `community.proxmox`. It targets only `proxmox_hosts` and does not change VM hardware, power or networking.

Install the pinned dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
ansible-galaxy collection install -r collections/requirements.yml -p .collections
```

Proxmox must already be installed and have trusted root SSH. Run enrollment before previews or applies of the bridge, VM or guest installation workflows:

```bash
ansible-playbook playbooks/configure-proxmox-api.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-api.yml --limit pve01
```

Check mode validates current identity and reports planned enrollment without creating credentials or local artifacts. Normal reruns retain the original token and repair a missing ACL or controller export without rotating credentials. Conflicting account ownership, privileges or a missing original secret record stop the run. Existing records from the former combined enrollment playbook remain valid.

Proxmox uses a passwordless `home-ansible@pve` account, token `controller`, and a bounded `HomeAutomation` role. The token inherits that user's role, which permits VM allocation/configuration/power, ISO and disk allocation, SDN use and audit access. The role applies at `/` to support allocation and cluster inventory; it cannot administer users/permissions or modify/power off the node. The original token remains root-owned beneath `/root/.home-automation-api`. Its cluster CA is exported through trusted SSH. The installed server certificate must already include the inventory IP.

Controller artifacts are mode 0600 under the mode-0700 `.cache/community-api/<inventory-host>/` directory. They contain API secrets and must not be committed or shared. Enrollment can recreate a missing controller export from the original host records. Never delete a host record to force rotation; explicit credential rotation is a separate operation.

After enrollment, preview and run the existing Proxmox workflows in this order:

```bash
ansible-playbook playbooks/configure-proxmox-bridges.yml --limit pve01 --check
ansible-playbook playbooks/configure-proxmox-bridges.yml --limit pve01
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01 --check
ansible-playbook playbooks/create-opnsense-vm.yml --limit pve01
ansible-playbook playbooks/install-opnsense.yml --limit pve01 --check
ansible-playbook playbooks/install-opnsense.yml --limit pve01
```

Inspect each preview and stop if a run fails. The bridge workflow verifies an unchanged owned snippet when guests exist. VM creation preserves matching hardware; a completed running installation verifies the installed guest without reinstalling. See [bridges](configure-proxmox-bridges.md), [VM creation](create-opnsense-vm.md) and [installation](install-opnsense.md) for their required media, inventory and records.

After guest installation, run [OPNsense API enrollment](configure-opnsense-api.md) separately before applying its pilot policy. Local Proxmox ISO preparation and iDRAC boot precede API enrollment and retain their native workflows.

Reference: [Proxmox collection](https://docs.ansible.com/projects/ansible/latest/collections/community/proxmox/index.html).

The Fedora cloud-init workflow adds `VM.Config.Cloudinit`. Enrollment permits only the exact original owned privilege set to upgrade to the new expected set, retaining the existing account/token/secret. It continues refusing unrelated privilege changes. Rerun this entry point before creating the Fedora guest; no storage-administration privileges are added.
