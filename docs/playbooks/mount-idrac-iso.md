# Mount an ISO through iDRAC virtual media

Playbook: [mount-idrac-iso.yml](../../playbooks/mount-idrac-iso.yml).

Host a checksum-verified ISO on the native Mac and attach it read-only to iDRAC8's virtual DVD. The same workflow accepts an original installation ISO or an ISO containing unattended-install answers. Operations are `mount` (default), `status` and `eject`. Mounting does not change boot settings, restart the host or start an installer.

## Native Mac setup and prerequisites

Use the [native Mac environment](../../README.md#install-the-pinned-local-environment), not the Linux container's virtual environment. This playbook uses builtin Ansible modules; it needs no additional collection. Run it as the logged-in Mac user, with the desktop session active. Local hosting uses that user's `launchd` GUI domain and requires no SSH login. Sudo is used only when the native hosts mapping needs an update.

Connect the Mac's Ethernet to the BMC recovery port, assign its inventory-defined static address, and disable Wi-Fi/VPN/bridging for the direct path. iDRAC must reach the Mac's HTTP port; a route from the Ansible process to iDRAC alone is insufficient. Allow the native Python executable through the Mac firewall if prompted. The server runs under `caffeinate -i -s` to prevent idle sleep and, on AC power, system sleep while serving. Keep the Mac powered on, its lid open and Ethernet connected until the installer has finished reading the ISO.

The existing `idracs` inventory supplies `ansible_host`, `idrac_expected_mac`, `idrac_network.address`, `idrac_ca_path` and Vault credentials. `idrac_network.address` must be the current reachable iDRAC address. The hostname must resolve **on the native Mac** and match its trusted certificate. Local mode ensures a dedicated `address hostname` entry in the Mac's `/etc/hosts`; unrelated entries are preserved, and duplicate/shared-alias entries stop the run. Supply `--ask-become-pass` for the Mac sudo password if that mapping needs changing. Set `idrac_iso_manage_hosts: false` to use existing verified name resolution instead. Certificate and hostname validation remain enabled.

Set these additional inputs in private inventory:

```yaml
idrac_iso_path: /Users/example/Repos/home/.cache/iso/installer.iso
idrac_iso_sha256: '<expected lowercase ISO SHA-256>'
idrac_iso_bind_address: 10.77.40.250
idrac_iso_port: 8080  # Optional; default 8080.
```

The path must be an absolute native Mac path to a regular, nonempty, nonsymlink ISO. Filenames may contain letters, digits, dots, underscores and hyphens. Obtain the expected SHA-256 from verified source metadata or the build that produced the ISO. Do not use a Linux-container path or accept a mismatching file. Keep unattended ISOs private because their embedded answer files can contain password hashes and SSH keys.

## Preview and mount

From the native Mac repository root:

```bash
.venv-macos/bin/ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --check --ask-become-pass
.venv-macos/bin/ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --ask-become-pass
```

Vault and sudo passwords prompt locally. Check mode previews any hostname edit, reads iDRAC, validates identity/action paths and reports whether a media action is needed. It makes no writes, starts no server, and does not verify local-file integrity, local hosting or bootability. The hostname must already resolve correctly for a first check-mode run: a proposed hosts edit is not applied in check mode. A normal run can establish the mapping before its verified HTTPS connection.

A normal mount verifies the ISO hash, installs [the single-file HTTP helper](../../scripts/serve-iso.py), starts a temporary `launchd` job, and checks an HTTP byte-range response and checksum-based ETag. Only then does it submit `InsertMedia` with `Image`, `Inserted: true` and `WriteProtected: true`. It reads the DVD resource back to require the exact image URL and read-only inserted state.

An already-mounted matching read-only ISO receives no additional insert POST. A different image, inconsistent console attachment or unexpected action target stops the run. The playbook never automatically ejects an unrelated image. Changes to an active local server's source or helper require ejection first.

Once mounting succeeds, [boot-idrac-iso.yml](boot-idrac-iso.md) can configure one-time virtual DVD boot and power on an offline UEFI server. Mounting and booting remain separately invoked operations.

The server exposes exactly one ISO over HTTP/1.1, without directory browsing, on the specified Ethernet IPv4 address. GET and HEAD support single byte ranges, including suffix ranges. Only the iDRAC address and serving Mac address can read it. HTTP image requests carry no iDRAC credentials. HTTP is unencrypted; use this temporary service on the isolated BMC path. The Redfish connection separately uses verified HTTPS.

## Boot for discovery

After mounting, use VGA/keyboard and the server's F11 one-time boot menu to select the UEFI virtual DVD. Choose **Advanced Options → Install Proxmox VE (Terminal UI, Debug Mode)** and stop at the full debug shell before starting the installation wizard. Continue past an early boot shell only if needed to reach that full shell. Do not continue into installation for a discovery-only boot.

Read the Linux disk and NIC identities:

```bash
lsblk -d -b -o NAME,TYPE,SIZE,MODEL,SERIAL,WWN,LOG-SEC
ls -l /dev/disk/by-id/
ip -br link
```

Use the observed RAID logical-disk device with `udevadm info --query=property --name=/dev/<observed-device>` to obtain installer filter properties. Match NICs by permanent MAC, not an assumed Linux name. iDRAC inventory cannot establish Linux udev identifiers. Mount/read-back success confirms media state, not successful boot or installation.

## Inspect, eject and switch images

Read-only status does not start or stop hosting:

```bash
.venv-macos/bin/ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --ask-become-pass \
  -e idrac_iso_operation=status
```

Once the host no longer needs the DVD, eject it using the same source inputs:

```bash
.venv-macos/bin/ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 --ask-become-pass \
  -e idrac_iso_operation=eject
```

Ejection requires the attached image URL to match the selected image. After verified ejection, the playbook stops its local server. Repeating ejection with empty media also cleans up a remaining local job. Never eject while an installer is reading the DVD.

To use a preconfigured ISO, first eject the original image, then update `idrac_iso_path` and `idrac_iso_sha256` in private inventory and run the mount command again. A prepared unattended ISO may install automatically when booted; this playbook only mounts it.

An existing web server can be used instead of local hosting:

```bash
.venv-macos/bin/ansible-playbook playbooks/mount-idrac-iso.yml --limit idrac01 \
  -e '{"idrac_iso_source":"url","idrac_iso_url":"http://10.77.40.250:8080/installer.iso"}'
```

Use the same URL/source when ejecting. External URLs must be credential-free HTTP(S), end in `.iso`, and contain no query parameters or fragment. External hosting is neither started nor stopped, and its bytes are not checksum-verified by this playbook. iDRAC must independently reach and support that source; the Ansible Redfish CA setting does not configure iDRAC's trust of an HTTPS image server.

## Local lifecycle and recovery records

The temporary job is `local.home-automation.iso.<inventory-hostname>` in `gui/<Mac-user-uid>`. Its helper, plist and log live under `.cache/iso-server/<inventory-hostname>/`, with directory mode 0700 and file mode 0600. The plist stays outside `~/Library/LaunchAgents`, so it is not installed as a login service. It runs until explicitly stopped, the desktop session ends, or the Mac restarts; it is not automatically restarted. The original ISO is read through an open read-only descriptor. In-place size/mtime changes cause subsequent reads to fail rather than serving a modified file.

Every media-changing run creates a private `backups/<host>-iso-<timestamp>-<suffix>/` directory. `before.json` records the media and intent; `result.json` preserves submission and final read responses without request credentials. `completion.json` is written only after verified read-back. Sensitive task output and diffs are suppressed.

POST actions are never automatically retried. Read-back allows up to 13 GETs, five seconds apart, with a 30-second request timeout. HTTP errors stop polling. If a submission times out or verification fails, inspect the private records and current media before retrying; a successful POST does not prove successful attachment. An incomplete operation does not automatically eject media or stop its server. Use `eject` after inspection when it is safe to remove the DVD.

If local hosting fails, inspect `.cache/iso-server/<host>/server.log`, the Mac's Ethernet address, firewall and desktop-session `launchd` domain. The server log records client IP, HTTP status, GET/HEAD method and whether a Range header was supplied, without logging request paths or header values. Correct checksum/path errors before mounting. Resolve TLS/hostname/authentication failures without disabling verification.

Offline syntax validation, without unlocking the real Vault:

```bash
ANSIBLE_ASK_VAULT_PASS=False .venv-macos/bin/ansible-playbook \
  -i inventory.example.yml playbooks/mount-idrac-iso.yml \
  -e vault_file=/dev/null --syntax-check
```

References: [Dell iDRAC8 virtual media API](https://www.dell.com/support/manuals/en-us/poweredge-c6320p/idrac8_redfishapiguide_2.70.70.70/virtualmedia?guid=guid-d9e76cf6-627d-4cb9-a3de-3f2b88b74cfb&lang=en-us), [Dell insert/eject request examples](https://github.com/dell/iDRAC-Redfish-Scripting/blob/master/Redfish%20Python/InsertEjectVirtualMediaREDFISH.py), [Proxmox installer debug boot](https://github.com/proxmox/pve-installer/blob/master/unconfigured.sh), [Apple caffeinate manual](https://github.com/apple-oss-distributions/PowerManagement/blob/main/caffeinate/caffeinate.8).
