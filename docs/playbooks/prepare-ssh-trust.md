# Prepare controller SSH trust

SSH-facing roles prepare controller trust before remote operations whenever the host has
`ssh_host_public_key` in inventory. `playbooks/prepare-ssh-trust.yml` also prepares it explicitly,
without connecting to any device. No container mounts or startup changes are required.

## Enroll a device once

Obtain the public host key through an independently trusted console. On Proxmox, use its verified
node shell or physical console:

```bash
cat /etc/ssh/ssh_host_ed25519_key.pub
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Put the complete single-line public key in the device's private inventory entry:

```yaml
pve01:
  ansible_host: 10.77.10.10
  ssh_host_public_key: "ssh-ed25519 <console-verified public key>"
```

For a legacy switch, obtain its RSA public host key through a trusted console or an already verified
SSH session. A network key scan alone does not verify a device's identity. Public host keys are
separate from the client login keys and passwords; login credentials continue using existing sources.

### Cisco switch enrollment and container recovery

The `cisco_switch` role already depends on `ssh_trust`; no separate Cisco cache or
automatic acceptance policy is needed. If preparation is skipped and libssh reports
an unknown host, check whether `switch01` is missing `ssh_host_public_key` in private
inventory.

On a workstation that previously trusted the switch, retrieve its existing entry
and fingerprint (substitute its actual address):

```bash
ssh-keygen -F 10.77.55.1 -f ~/.ssh/known_hosts
ssh-keygen -F 10.77.55.1 -f ~/.ssh/known_hosts | ssh-keygen -lf -
```

Use the `ssh-rsa` key type and complete base64 key from that trusted entry as
`ssh_host_public_key`. Do not copy the address, a hashed hostname, or a comment
line into the key value. If using a newly collected candidate instead, match its
fingerprint against that trusted entry or an independently trusted console before
enrollment. A candidate remains outside both active known_hosts files until verified.

```yaml
switch01:
  ansible_host: 10.77.55.1
  ssh_host_public_key: "ssh-rsa <verified complete base64 public key>"
  ssh_trust_names: [10.77.55.1, 10.77.10.2]
```

Include both addresses only when they are confirmed management addresses of the
same switch. Keep the existing scoped Cisco legacy-algorithm configuration.

```bash
./just playbook playbooks/prepare-ssh-trust.yml --limit switch01 --check
./just playbook playbooks/prepare-ssh-trust.yml --limit switch01 --check
./just playbook playbooks/backup-switch.yml --limit switch01
```

The first command populates local trust, even in check mode; the repeat should
report `changed=0`. The backup then proves that libssh accepts the enrolled key
and that privileged read-only access works. Neither operation changes switch
configuration. Subsequent switch workflows automatically reconstruct missing
local trust from the enrolled inventory key.

During a management address migration, explicitly list the verified names sharing the same key:

```yaml
ssh_trust_names: [10.77.55.1, 10.77.10.2]
```

Names default to `ansible_host` (or the inventory hostname). A nondefault `ansible_port` produces
OpenSSH's `[host]:port` entries. Patterns, known_hosts markers, and multiline keys are rejected.

## Run or recover

Existing SSH playbook commands need no additional step. For explicit controller preparation:

```bash
ansible-playbook playbooks/prepare-ssh-trust.yml --limit pve01 --check
ansible-playbook playbooks/reboot-proxmox-host.yml --limit pve01 --check
```

Preparation validates the public key using `ssh-keygen` before writing trust. It creates mode-0700
directories and mode-0600 files, restores `.cache/ssh/known_hosts` from inventory, and installs the
same entries into `~/.ssh/known_hosts` for OpenSSH and Cisco libssh. Unrelated entries remain intact.
Updates to these shared files are serialized across hosts in each play. Concurrent independent
playbook processes sharing the same controller trust files should run sequentially.

The local artifact writes intentionally run even with `--check`: they are prerequisites for remote
read-only checks. An unchanged repeat run reports no changes. `ssh_trust_cache_file` and
`ssh_trust_controller_file` can override the output paths; the latter must be the file actually read
by the configured transport.

Updating the authoritative inventory key replaces that host's cached/controller entry for the same
key type. A changed server key still fails SSH verification until its new identity is independently
verified and inventory is updated. Hosts without `ssh_host_public_key` retain their existing trust
workflow. OPNsense, Fedora and UniFi guests keep their existing dedicated seed-owned trust files.

Deleting the SSH trust cache is recoverable from inventory. Other artifacts, such as API credentials
and guest seed private keys, have their own recovery procedures; this task does not recreate them.
