# Configure OPNsense API access

`playbooks/configure-opnsense-api.yml` enrolls a restricted OPNsense API user through seeded trusted root SSH, exports its public certificate and private credentials to this controller, and verifies access with OXL. It targets only `opnsense_hosts` and does not change VM hardware, power or networking.

Install the pinned dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
ansible-galaxy collection install -r collections/requirements.yml -p .collections
```

OPNsense must already be installed and reachable through its seeded trusted SSH key; it needs no Python. Run enrollment after [guest installation](install-opnsense.md) and before applying the pilot policy:

```bash
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-api.yml --limit opnsense01
```

Check mode validates current identity and reports planned enrollment without creating credentials, certificates or local artifacts. Normal reruns retain the original API key and certificate and recreate a missing controller export. Conflicting account ownership, privileges or a missing original secret record stop the run. Existing records from the former combined enrollment playbook remain valid. Rerunning also upgrades the original Firewall/Unbound account with Kea DHCPv4 and WireGuard configuration access, preserving the existing key and certificate without a GUI restart. Firewall, DHCP and WireGuard API reads are checked after enrollment.

OPNsense uses a separate `home-ansible` API user with Firewall Rules, Unbound, Kea DHCPv4 and WireGuard configuration privileges, a random unrecoverable interactive password and the default no-shell setting. It preserves the root account and seeded SSH key. It creates a self-signed GUI/API certificate containing the installed management IP and FQDN, retains the existing certificates, and selects the new certificate. Applying it restarts the web GUI/API once; SSH remains available. The original configuration and private enrollment material remain root-owned under `/conf/ansible-api`. GUI browsers require their own trust import; collection connections validate the exported public certificate and the inventory IP. No hosts-file mapping is needed.

Controller artifacts are mode 0600 under the mode-0700 `.cache/community-api/<inventory-host>/` directory. They contain API secrets and must not be committed or shared. Enrollment can recreate a missing controller export from the original host records. Never delete a host record to force rotation; explicit credential rotation is a separate operation. The generated certificate lasts 825 days; certificate renewal is separate from a repeated enrollment.

For the original OPNsense 26.7 release, enrollment also persists and applies `kern.ipc.tls.enable=0` to avoid corrupted large HTTPS API responses, then restarts the web GUI. TLS and certificate verification remain enabled. This disables kernel TLS offload system-wide; the saved tunable persists across upgrades and can be removed through System → Settings → Tunables after upgrading to a release with the upstream fix. Enrollment does not add it on later releases. See the [26.7 TLS issue](https://github.com/opnsense/core/issues/10573) and [26.7.1 release notes](https://docs.opnsense.org/releases/CE_26.7.html).

After enrollment, preview and run the [management pilot](configure-opnsense-pilot.md). Its VM operations also require [Proxmox API enrollment](configure-proxmox-api.md) on this controller:

```bash
ansible-playbook playbooks/configure-opnsense-management.yml --limit pve01 --check
ansible-playbook playbooks/configure-opnsense-management.yml --limit pve01
```

Inspect the preview and stop if a run fails. The first OXL policy apply may save descriptions and explicit defaults on existing owned objects. Repeating the preview after successful application should report no changes.

Reference: [OXL connection setup](https://ansible-opnsense.oxl.app/usage/2_basic.html).

WireGuard enrollment additionally grants `page-wireguard-config` and verifies the server/peer API reads through OXL. Existing API keys and certificate trust are preserved; see the [WireGuard workflow](configure-opnsense-wireguard.md).
