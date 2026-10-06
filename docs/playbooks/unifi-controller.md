# Isolated UniFi controller and declarative configuration

Build VM 110 on MGMT, install a pinned UniFi OS Server, and stage fresh Ansible-owned HOME/WLAN settings while production AP connections remain blocked. The historical Network backup is retained only for reference/recovery and is not imported. AP adoption, inform changes, firmware updates, switch AP-port changes and household gateway cutover are separate workflows. Keep the old laptop controller closed during this rehearsal.

## Allocation and ownership

| Item | Contract |
|---|---|
| Guest | `unifi01`, VM 110, two cores, fixed 4096 MiB RAM, 32 GiB disk |
| Network | One VirtIO NIC on the existing VLAN-aware data bridge, tag 10 |
| Services | MGMT address `.20/24`, local DNS `unifi01.<domain>`, MGMT gateway/resolver |
| Administrator | Named user with approved Ed25519 keys; password SSH and root SSH disabled |
| Boot | Automatic startup, order 2, up 30 seconds, down 120 seconds |
| OS | Ubuntu Server 24.04 cloud image, build `20260926` |
| Application | UniFi OS Server 5.1.42; reviewed Network/API baseline 10.6.106 (initial bundle 10.5.67) |

`inventory.example.yml` uses synthetic addresses. The private allocation uses `10.55.10.20`, gateway/DNS `10.55.10.254`, WireGuard administrator `10.55.99.2` and wired SSH recovery `10.55.10.250`. `unifi_vm_allocation` belongs to the owning Proxmox host; `unifi_proxmox_host` belongs to the guest.

Three roles have required action dictionaries with no default action:

| Role | Explicit actions | Ownership |
|---|---|---|
| `unifi_vm` | `prepare`, `create`, `verify`, `start`, `stop` | Controller artifacts, cloud-init identity and guarded Proxmox lifecycle |
| `unifi_network` | `configure`, `verify` | Four named OPNsense rules and one DNS host record |
| `unifi_host` | `configure`, `verify`, `configuration_ready`, `restore_ready` | Guest baseline, first installation, TLS/isolation readiness and optional recovery gate |
| `unifi_site` | `inspect`, `configure`, `verify` | Official local API, HOME VLAN 20 and disabled household WLAN staging |

Each named playbook supplies its action. Schemas in `meta/argument_specs.yml` validate inputs before dispatch. The creation guard refuses unowned IDs, extra NICs/disks, pending hardware changes, changed seed identities and automatic recreation of a removed completed VM. An existing completed stopped guest stays stopped during `create`; use `start-unifi-vm.yml` explicitly.

## Configuration isolation

OPNsense permits only the authenticated laptop `/32` to controller TCP 22/11443 and permits the controller `/32` to public TCP 80/443 for packages and installation. Existing MGMT private-range denies precede those outbound permissions. The guest also owns a default-deny nftables table, `inet home_unifi`:

| Connection | Allowed |
|---|---|
| WireGuard administrator → controller | TCP 22/11443 and diagnostic ICMP |
| Wired recovery administrator → controller | TCP 22 and diagnostic ICMP |
| Controller → MGMT firewall | DNS TCP/UDP 53 and NTP UDP 123 |
| Controller → public destinations | TCP 80/443 and established replies |
| Controller ↔ APs and other private devices | Blocked, including same-VLAN AP traffic |
| Discovery, STUN, inform, IPv6 and forwarded container traffic | Blocked |

The vendor uses rootless Podman with pasta networking; its host sockets pass through the output policy. A separate drop policy covers forwarding. Loopback remains available for the application's internal services. Both vendor service units require the isolation unit and verify its loaded rules before startup. The distribution's global-flush `nftables.service` is masked; the owned service applies only its own table atomically. Repeating an unchanged apply leaves it unchanged and preserves unrelated tables. Do not enable another firewall manager or change container networking during the rehearsal.

OPNsense cannot isolate two endpoints on the same MGMT VLAN by itself. The guest firewall is therefore a required configuration prerequisite. Keep UI remote management disabled and use a local console account. Do not adopt devices or enable automatic application/device updates. Public HTTP/HTTPS egress is for provisioning; this policy is not an Internet destination allowlist.

## Protected preparation

Run commands from the Ansible repository with the administrative WireGuard tunnel active. The existing MGMT route includes the controller address; no client profile change is required. Retain wired recovery ports 4/5 and HOME pilot port 8.

Preserve the historical `.unf` at `/UbuntuSync/Repos/home/backups/unifi-controller.private.unf`. Its optional protected cache copy at `.cache/unifi-backup/authoritative.unf` and frozen checksum remain for explicitly selected recovery, without becoming desired state. Fresh configuration does not require a backup. Existing host keys, seed bytes, certificates and completed VM intent remain unchanged.

```sh
ansible-playbook playbooks/prepare-unifi.yml --limit pve01 --check
ansible-playbook playbooks/prepare-unifi.yml --limit pve01
```

Preparation runs locally, without changing Proxmox. It verifies Ubuntu's signed checksum list against the pinned cloud-image public key, hashes the image and official UniFi installer, and creates stable guest SSH keys, a pinned `known_hosts`, the private cloud-init seed and GUI certificate/key. Missing backup staging does not block provisioning or declarative configuration; only the optional restore gate requires it. A repeat preparation preserves keys/certificates and should report no changes.

The Ubuntu signer is `D2EB44626FDDC30B513D5BB71A5D6C4C7DB87C81`. Image SHA-256 is `6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2`; installer SHA-256 is `f6111e9396a42c74016f5dde9b01fbef486a6fe69efe137935e6e38b7c22f94d`. The installer pin records the exact official HTTPS download; it is not a vendor detached-signature claim. Origins and validation logic are in `scripts/prepare-unifi-artifacts.py`. [Ubuntu verification](https://documentation.ubuntu.com/security/software-integrity/image-verification/), [selected UniFi release](https://community.ui.com/releases/UniFi-OS-Server-5-1-42/509f4de9-8fe4-4718-abad-1bb6990dedcc).

## Provision and install

Preview the firewall changes first. Expect four `Home automation: UNIFI …` rules and the `unifi01` A record. Apply and verify after reviewing that scope:

```sh
ansible-playbook playbooks/configure-opnsense-unifi.yml --limit opnsense01 --check
ansible-playbook playbooks/configure-opnsense-unifi.yml --limit opnsense01
ansible-playbook playbooks/verify-opnsense-unifi.yml --limit opnsense01
```

The role records intent and preserves the original OPNsense configuration before merges, then verifies saved rules, loaded rule identities and DNS before completing. Its controller backup export retains the original transaction identity on repeat runs.

```sh
ansible-playbook playbooks/create-unifi-vm.yml --limit pve01 --check
ansible-playbook playbooks/create-unifi-vm.yml --limit pve01
ansible-playbook playbooks/verify-unifi-vm.yml --limit pve01
ansible-playbook playbooks/configure-unifi-host.yml --limit unifi01 --check
ansible-playbook playbooks/configure-unifi-host.yml --limit unifi01
ansible-playbook playbooks/verify-unifi-host.yml --limit unifi01
```

VM creation requires the completed network policy first. It checks storage/RAM headroom and probes the proposed address using ARP on Proxmox's native MGMT link. No reply is a collision check, not a permanent reservation guarantee. It imports the verified disk once, resizes to the absolute allocation, starts only the initial installation, and verifies cloud-init through the guest agent and pinned SSH.

The pinned Ubuntu image contains Python/nftables, so first boot applies isolation before package downloads. Application installation is separate and uses the inspected vendor options `--non-interactive --network-mode pasta --web-port 11443`. An immutable first-install marker prevents automatic reinstall, purge or upgrade. Verification checks the installed CLI at `/usr/local/bin/uosserver`, service binary at `/var/lib/uosserver/bin/uosserver-service`, exact version/network/port settings, service user, startup guard and GUI listener. If installation succeeds but verification is interrupted, rerunning configuration skips the installer and completes the record after verification passes. [Vendor installation requirements](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi).

The API creates the guest with automatic startup disabled. Proxmox requires host-wide `Sys.Modify` for the `startup` field; the automation token does not receive that permission. A guarded task over trusted root SSH sets only VM 110's startup order, verifies its protected ownership record and full hardware, and uses the current configuration digest to reject concurrent changes. A second guarded task enables automatic startup only after first-boot verification. Completed guests require the exact enabled startup policy; interrupted pending guests may retain the disabled initial policy. Rerunning creation resumes the protected intent without rotating keys or granting new API privileges.

## Local setup, certificate and Vault enrollment

1. Use native macOS Terminal/browser with WireGuard active. Open `https://10.55.10.20:11443`. Before accepting the initial self-signed certificate, compare its SHA-256 fingerprint with the one printed by `verify-unifi-host.yml`, obtained through the already pinned SSH connection. Do not enter credentials if it differs.
2. Complete local-only console setup with a strong unique password. Leave Site Manager/remote management disabled; disable automatic application and device updates. Do not restore/adopt during this setup.
3. Upload `.cache/unifi-seed/unifi01/gui-cert.pem` and `gui-key.pem` through **Settings → Control Plane → Console → Certificates**. Use the copies from the same controller checkout; keep the key private. This follows the vendor's supported GUI certificate mechanism. Trust only the reviewed certificate for the controller on the Mac; do not disable certificate validation globally. The leaf includes both the MGMT IP and local DNS name.
4. Run the configuration gate:

   ```sh
   ansible-playbook playbooks/verify-unifi-config-ready.yml --limit unifi01
   ```

   It requires the uploaded prepared certificate with hostname-verified TLS, configured firewall DNS, public HTTPS and loaded isolation policy. Fresh private-device probes must fail. It does not require or upload a backup.
5. Create a local Network API key using **UniFi Network → Integrations**, where the installed version's API documentation is available. Keep remote management disabled; use the local API rather than a Site Manager/cloud key. Choose the narrowest permissions offered that support site/resource reads and network/WLAN writes. If this release has no per-resource write scope, the key is a controller credential: limit its use to this workflow and revoke/rotate deliberately. [Official local API guidance](https://help.ui.com/hc/en-us/articles/30076656117655-Getting-Started-with-the-Official-UniFi-API).
6. Run `ansible-vault edit secrets/vault.yml` (or your existing `vault_file`) and **add** the following without replacing other entries:

   ```yaml
   vault_devices:
     unifi01:
       api_key: "<local Integrations key>"
       ssid: "<existing household SSID>"
       passphrase: "<existing household Wi-Fi passphrase>"
   ```

   Do not paste secrets into chat, command arguments or Git. Ansible loads Vault at play scope, sends decrypted values through standard input under `no_log`, and reports only a safe summary. No plaintext API-key or WLAN credential file is created. Inventory holds endpoint/allocation data; Vault holds credentials.

## Stage and verify fresh desired configuration

```sh
ansible-playbook playbooks/inspect-unifi-site.yml --limit unifi01
ansible-playbook playbooks/configure-unifi-site.yml --limit unifi01 --check
ansible-playbook playbooks/configure-unifi-site.yml --limit unifi01
ansible-playbook playbooks/verify-unifi-site.yml --limit unifi01
```

UniFi OS 5.1.42 initially bundled Network 10.5.67, but the verified controller now runs Network 10.6.106. The local API helper pins 10.6.106 and the exact prepared leaf certificate. Its used operations and 132 referenced schemas were compared against the original contract without differences; future versions still require explicit review. A version refusal reports the observed version without credentials and performs no API writes. It uses `https://<controller>:11443/proxy/network/integration/v1` with `X-API-Key`, refuses redirects/proxies, reads complete paginated collections, and requires one exact site. `unifi_site_id` may select its UUID explicitly when multiple sites exist. [Pinned official OpenAPI](https://developer.ui.com/network/v10.6.106/openapi.json).

| Owned setting | Initial desired value |
|---|---|
| Network | HOME, VLAN 20, enabled definition, `UNMANAGED` (external gateway) |
| WLAN | Existing Vault SSID/passphrase, `STANDARD`, **disabled** |
| Client network | Explicit reference to HOME VLAN 20 |
| Security | WPA2/WPA3-Personal mixed mode; PMF Optional; WPA2/WPA3 fast roaming disabled |
| Bands | 2.4 GHz and 5 GHz |
| Visibility/isolation | Visible SSID, client isolation off for printer/casting |
| Extra features | No hotspot, MAC filtering, blackout schedule, MLO or new roaming/radio optimizations |

Live Network 10.6.106 testing rejected the original WPA2 request containing `mloEnabled: false` with an MLO/WPA3 prerequisite error. The helper omits that optional field and independently requires MLO to be absent or false on readback. The approved profile now uses WPA2/WPA3 mixed mode with PMF Optional. Its required SAE anti-clogging and sync settings are explicitly five seconds each; both fast-roaming flags remain false. A live update of the disabled diagnostic WLAN returned the exact desired mixed-mode fields while preserving its ID, HOME and zero adopted devices. Its ownership journal remains pending until configure replaces the disposable test values with the vaulted household inputs. Preserve that journal and run configure followed by verify to complete staging. Production client compatibility remains an AP-migration acceptance check.

The definition does not configure OPNsense DHCP/routing or Cisco ports. Check mode performs GETs only and creates no files. The first apply preserves a private original API snapshot and an ownership journal under `.cache/unifi-site/unifi01` (0700 directory/0600 files). Repeat apply updates only the recorded IDs when declared fields differ; unchanged apply is a no-op. Inspect is read-only and reports counts/site ID without SSID/password values. Verify requires complete ownership and exact saved fields, including the secret; API masking/omission cannot count as verified. Do not edit these resources simultaneously in the GUI: the API has no documented conditional-write contract, so reads detect preparation changes but cannot eliminate a server-side race.

Unowned HOME/VLAN 20/WLAN collisions, missing owned resources, changed object types, an already enabled owned WLAN or any adopted device cause a refusal. Lost create responses require inspection rather than automatically claiming a matching object. An interrupted allocation with recorded IDs resumes those IDs and never reruns completed allocation blindly. No delete, device adoption/action, firmware, inform or WLAN activation endpoint is used.

An HTTP 400/422 refusal reports the operation, resource type and whitelisted validation field/constraint names. Vendor response messages and submitted values are withheld because they can contain the SSID or passphrase. HTTP 401/403 points to API-key permissions instead. If HOME creation succeeds before WLAN creation fails, preserve the journal and original snapshot; the next configure run reuses the recorded network ID and resumes the disabled WLAN step. A rejected request is not a completed staging transaction.

**AP migration remains a separate phase.** The final tagged VLAN 20 WLAN stays disabled during staging. Before reconnecting an AP, prove its current SSH/recovery access and live identity, and prepare a compatible native/untagged migration profile or coordinated AP/switch transition. Do not enable the tagged WLAN on today's access ports. Preserve AP1's working AP2 mesh uplink until wired independence is proven. Unsupported device-wide mesh/uplink-monitor/static-IP settings require a documented supported workflow; this role does not claim to manage them.

The bootstrap fingerprint check sends no credentials and runs over loopback inside pinned SSH; subsequent configuration readiness requires the explicitly prepared certificate and normal TLS validation. Certificate renewal is deliberate: preparation refuses near-expiry certificates or partial key pairs rather than silently replacing them.

## Recovery and next stage

Use `stop-unifi-vm.yml` for a graceful explicit stop and `start-unifi-vm.yml` to restart an already completed owned VM. Creation does not reset a completed guest. Preserve its original VM intent, seed, TLS inputs, ownership journal and historical backup. A pending vendor-install marker with no service requires inspection of the installer/service logs; the workflow will not replay a partially failed installer automatically. An interrupted firewall transaction can be reconciled by the same configure entry point while retaining its original backup.

After successful isolated configuration/review, rehearse firewall-first/controller-second startup and the physical recovery paths. The Proxmox maintenance guard accepts only completed owned VM 100/110/200 allocations; Fedora's manual-start policy requires VM 200 stopped for reboot. Startup delays do not prove DNS or application readiness: re-run the verification entry points after a controlled host boot. Gateway transfer and AP reconnection still require their separate migration steps and rollback checks.

## Optional historical recovery restore

`verify-unifi-restore-ready.yml` is retained only for an explicitly selected recovery restore. It requires the frozen historical `.unf` checksum in addition to TLS/isolation checks. It is not part of the fresh migration workflow. Restoring into an Ansible-owned site can introduce unowned resources; do not combine the two paths automatically. No backup is uploaded or restored by any entry point.
