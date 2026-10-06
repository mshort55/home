# SSH transport and legacy IOS compatibility

The Cisco group uses `ansible.netcommon.network_cli` with explicit
`ansible_network_cli_ssh_type: libssh`. Runtime and validation environments use
`ansible-pylibssh` 1.4.0+home1 with statically embedded libssh 0.12.2. Paramiko is
no longer a runtime dependency. IOS modules and enable mode remain in use;
changing the client does not change switch configuration.

## Build and verify

Follow the platform prerequisites in the [README](../README.md). Run
`tools/install-ssh.py` with each target virtual environment's Python **before**
installing `requirements.txt` or `requirements-dev.txt`. It verifies committed
source SHA-256 pins, builds libssh and the bindings, installs the local wheel and
checks its versions. The libssh pin was established by checking the upstream
release signature against the [published key](https://www.libssh.org/get-it/).

The native library is embedded, so an old system libssh cannot be loaded by
accident. Server support, GSSAPI and compression are omitted. OpenSSL is linked
dynamically and needs operating-system/Homebrew security updates. Keep Linux and
Mac virtual environments and build caches separate. Mac operation needs testing
on that native platform; Linux CI does not establish Mac compatibility.

Upstream Python 1.4.0 wheels bundle libssh 0.12.0, predating later security fixes.
They also ignore the `config_file` keyword documented by Ansible. The installer
adds only the missing binding and uses the distinct local version `1.4.0+home1`.
It checks exact source anchors before patching. A missing or unparseable file
fails before connecting. Replace this patch only after verifying an upstream
release's policy-file support and repeating compatibility/host-key tests.

```bash
.venv/bin/python tools/check-ssh.py
# After source/build pin changes:
.venv/bin/python tools/install-ssh.py --force
```

Validation and online audits check exact Python/native versions, modern default
host signatures/key exchanges, and missing-policy refusal. Python vulnerability
scans do not inspect embedded native libraries: maintain `tools/ssh-sources.json`
against upstream libssh security releases too. Build dependencies are isolated
and locked in `tools/requirements-ssh-build.txt`; update that file with
`pip-compile` from its `.in` file. Audit all three dependency locks.

The base requirement `ansible-pylibssh==1.4.0` accepts the local build under
PEP 440; the SSH checker additionally requires the exact local version.
The locks prohibit upstream wheels. Existing environments must also uninstall
the obsolete Paramiko package after installing the replacement.

## Scoped compatibility

`files/ssh/cisco-legacy.conf` is selected explicitly through
`ansible_libssh_config_file` only in the Cisco group. Its `Host *` applies only
to sessions selecting that file. It adds `ssh-rsa`,
`diffie-hellman-group14-sha1` and `hmac-sha1` after modern defaults. Encryption is
limited to AES-CTR. Group1, SHA-1 group exchange, CBC, 3DES and truncated SHA-1
MACs are not enabled. Host-key checking stays on, automatic acceptance stays off,
passwords remain Vault-backed and persistent session logging remains off.

For another private inventory, copy the Cisco connection/policy-file settings
from `inventory.example.yml` and remove Paramiko-only settings. Keep credentials
out of source files. A changed management address still requires an independently
verified known-host entry before connecting.

This removes the flagged Paramiko package and outdated native wheel; it does
**not** eliminate RSA/SHA-1 or SHA-1 key exchange on a legacy switch. HMAC-SHA-1
is a separate protocol use from RSA/SHA-1 signatures. Restrict management access
and remove compatibility settings when equipment supports modern SSH. This
policy is incompatible with FIPS-only operation.

## Platform evidence and remaining hardening

The Catalyst 3750-X / IOS 15.2(4)E guide documents `ssh-rsa` and
`x509v3-ssh-rsa` host algorithms without RSA/SHA-2 alternatives. Published
release notes end at E10 without a new SSH feature; security support ended in
2019 and all support in 2021. Cross-checking platform documentation, firmware
history and the lifecycle notice found no supported path to modern signatures
or key exchange. This establishes documented support limits, not the absence of
every possible undocumented feature or unsupported image.

Forcing SSH version 2 and using stronger RSA keys can still improve the server
baseline. Selecting group14's 2048-bit DH group and AES-CTR improves client
negotiation without modifying the server. Neither adds SHA-2 signatures or key
exchange. Generic IOS XE commands do not establish support on classic IOS.
Server configuration and key regeneration require a separate planned change.

References:

- [3750-X host algorithms](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3750x_3560x/software/release/15-2_4_e/configurationguide/b_1524e_consolidated_3750x_3560x_cg/b_1524e_consolidated_3750x_3560x_cg_chapter_01010010.html)
- [3750-X SSH version settings](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3750x_3560x/software/release/15-2_4_e/configurationguide/b_1524e_consolidated_3750x_3560x_cg/b_1524e_consolidated_3750x_3560x_cg_chapter_01001.html)
- [Firmware history](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3750x_3560x/software/release/15-2_4_e/releasenotes/rn-1524e-3750x3560x.html)
- [Platform lifecycle](https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-3560-x-series-switches/eos-eol-notice-c51-736139.html)
- [Ansible libssh settings](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/libssh_connection.html)
- [libssh 0.12.2 security fixes](https://www.libssh.org/2026/07/28/libssh-0-12-2-security-release/)
