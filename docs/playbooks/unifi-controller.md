# Isolated UniFi controller and restore rehearsal

Build VM 110 on MGMT, install a pinned UniFi OS Server, and restore the authoritative Network backup while production AP connections remain blocked. AP adoption, inform changes, firmware updates, switch AP-port changes and household gateway cutover are separate workflows. Keep the old laptop controller closed during this rehearsal.

## Allocation and ownership

| Item | Contract |
|---|---|
| Guest | `unifi01`, VM 110, two cores, fixed 4096 MiB RAM, 32 GiB disk |
| Network | One VirtIO NIC on the existing VLAN-aware data bridge, tag 10 |
| Services | MGMT address `.20/24`, local DNS `unifi01.<domain>`, MGMT gateway/resolver |
| Administrator | Named user with approved Ed25519 keys; password SSH and root SSH disabled |
| Boot | Automatic startup, order 2, up 30 seconds, down 120 seconds |
| OS | Ubuntu Server 24.04 cloud image, build `20260926` |
| Application | UniFi OS Server 5.1.42, bundled Network 10.5.67 |

`inventory.example.yml` uses synthetic addresses. The private allocation uses `10.55.10.20`, gateway/DNS `10.55.10.254`, WireGuard administrator `10.55.99.2` and wired SSH recovery `10.55.10.250`. `unifi_vm_allocation` belongs to the owning Proxmox host; `unifi_proxmox_host` belongs to the guest.

Three roles have required action dictionaries with no default action:

| Role | Explicit actions | Ownership |
|---|---|---|
| `unifi_vm` | `prepare`, `create`, `verify`, `start`, `stop` | Controller artifacts, cloud-init identity and guarded Proxmox lifecycle |
| `unifi_network` | `configure`, `verify` | Four named OPNsense rules and one DNS host record |
| `unifi_host` | `configure`, `verify`, `restore_ready` | Guest baseline, first installation and manual restore gate |

Each named playbook supplies its action. Schemas in `meta/argument_specs.yml` validate inputs before dispatch. The creation guard refuses unowned IDs, extra NICs/disks, pending hardware changes, changed seed identities and automatic recreation of a removed completed VM. An existing completed stopped guest stays stopped during `create`; use `start-unifi-vm.yml` explicitly.

## Restore isolation

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

OPNsense cannot isolate two endpoints on the same MGMT VLAN by itself. The guest firewall is therefore a required restore prerequisite. Keep UI remote management disabled and use a local console account. Do not adopt devices or enable automatic application/device updates. Public HTTP/HTTPS egress is for provisioning; this policy is not an Internet destination allowlist.

## Protected preparation

Run commands from the Ansible repository with the administrative WireGuard tunnel active. The existing MGMT route includes the controller address; no client profile change is required. Retain wired recovery ports 4/5 and HOME pilot port 8.

Stage a private copy of the authoritative `.unf` as `.cache/unifi-backup/authoritative.unf`, directory mode 0700/file mode 0600. The original supplied path is `/UbuntuSync/Repos/home/backups/unifi-controller.private.unf`; preserve it. Alternatively set the optional `unifi_backup_file` to its protected absolute path in private inventory. The preparation workflow freezes the backup's SHA-256 in `.cache/unifi-seed/unifi01/backup.json` and refuses replacement bytes afterward. Backup contents are never decoded, logged or uploaded by these playbooks. Network 7.3.83 is the documented source version; its successful restore into the selected release remains a rehearsal acceptance check.

```sh
ansible-playbook playbooks/prepare-unifi.yml --limit pve01 --check
ansible-playbook playbooks/prepare-unifi.yml --limit pve01
```

Preparation runs locally, without changing Proxmox. It verifies Ubuntu's signed checksum list against the pinned cloud-image public key, hashes the image and official UniFi installer, and creates stable guest SSH keys, a pinned `known_hosts`, the private cloud-init seed and GUI certificate/key. Missing backup staging permits isolated provisioning but blocks restore readiness. A repeat preparation preserves keys/certificates and should report no changes.

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

## Local setup, certificate and manual restore

1. Use native macOS Terminal/browser with WireGuard active. Open `https://10.55.10.20:11443`. Before accepting the initial self-signed certificate, compare its SHA-256 fingerprint with the one printed by `verify-unifi-host.yml`, obtained through the already pinned SSH connection. Do not enter credentials if it differs.
2. Complete local-only console setup with a strong unique password. Leave Site Manager/remote management disabled; disable automatic application and device updates. Do not restore/adopt during this setup.
3. Upload `.cache/unifi-seed/unifi01/gui-cert.pem` and `gui-key.pem` through **Settings → Control Plane → Console → Certificates**. Use the copies from the same controller checkout; keep the key private. This follows the vendor's supported GUI certificate mechanism. Trust only the reviewed certificate for the controller on the Mac; do not disable certificate validation globally. The leaf includes both the MGMT IP and local DNS name.
4. Run the gate:

   ```sh
   ansible-playbook playbooks/verify-unifi-restore-ready.yml --limit unifi01
   ```

   It requires the frozen original backup, exact uploaded certificate with hostname-verified TLS, DNS/public HTTPS and the loaded isolation policy. DNS is queried directly on the configured firewall resolver, bypassing the guest's normal own-host loopback entry in `/etc/hosts`. Fresh private-device connection probes must fail. This is a prerequisite check, not a backup restore.
5. Restore the authoritative `.unf` through the Network application's supported backup interface. Do not restore a whole-console backup or use an undocumented API/database write. Record acceptance/rejection and the resulting Network version. If this release rejects the old backup, stop and choose a supported staged migration; do not upgrade firmware or reset APs to work around it. [Supported backup migration](https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi).
6. Review the restored SSID/security, VLAN, AP membership, mesh/uplink-monitor, static addressing and inform settings privately. Preserve the existing SSID/passphrase and keep automatic updates/remote management disabled. APs must remain disconnected/offline in this controller. Re-run host and restore-readiness verification after restoration; neither proves the restored WLAN's semantics, so inspect those in the GUI.

The bootstrap fingerprint check sends no credentials and runs over loopback inside pinned SSH; subsequent restore readiness requires the explicitly prepared certificate and normal TLS validation. Certificate renewal is deliberate: preparation refuses near-expiry certificates or partial key pairs rather than silently replacing them.

## Recovery and next stage

Use `stop-unifi-vm.yml` for a graceful explicit stop and `start-unifi-vm.yml` to restart an already completed owned VM. Creation does not reset a completed guest. Preserve its original VM intent, seed, TLS inputs and authoritative backup. A pending vendor-install marker with no service requires inspection of the installer/service logs; the workflow will not replay a partially failed installer automatically. An interrupted firewall transaction can be reconciled by the same configure entry point while retaining its original backup.

After a successful isolated restore/review, rehearse firewall-first/controller-second startup and the physical recovery paths. The Proxmox maintenance guard accepts only completed owned VM 100/110/200 allocations; Fedora's manual-start policy requires VM 200 stopped for reboot. Startup delays do not prove DNS or application readiness: re-run the verification entry points after a controlled host boot. Gateway transfer and AP reconnection still require their separate migration steps and rollback checks.
