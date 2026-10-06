# Automated validation

Validation uses Python 3.12 and a separate pinned environment. Runtime playbooks
continue to use the environment and private inputs described in the README.

## Setup

Run from the repository root on Linux:

```bash
python3 -m venv .venv-validation
.venv-validation/bin/python tools/install-ssh.py
.venv-validation/bin/python -m pip install -r requirements-dev.txt
.venv-validation/bin/ansible-galaxy collection install -r collections/requirements.yml -p .collections
.venv-validation/bin/python tools/install-validation-tools.py
```

On macOS use `.venv-validation-macos` for these three environment commands. The
convenience runner and pre-commit hook select that native environment automatically.
Keep the Linux and macOS environments separate when sharing the repository.

Install PHP CLI through the operating system package manager. ShellCheck is
provided by `shellcheck-py`. The native tool installer downloads pinned Hadolint
and Gitleaks releases, verifies committed SHA-256 values, and installs them in
`.cache/validation/bin`. Linux and macOS on ARM64 and x86-64 are supported.

Install the SSH build prerequisites from the [README](../README.md) first.
Setup requires internet access. The standard validation command performs offline
checks after dependencies and collections are installed:

```bash
python3 tools/run-validation.py
```

## Checks

The full command checks repository privacy and whitespace, YAML/Python/Jinja and
embedded Python syntax, role actions/defaults, documentation tables and local
file links, ignore rules, and Ansible trust/privacy settings. It runs Ruff lint
and formatting, YAML lint, Ansible lint, shell syntax/ShellCheck, PHP syntax
(including the bootstrap builder's embedded PHP), Hadolint, Gitleaks on
Git-visible source, isolated unit tests with branch coverage, and installed
Python/collection version checks.

Ansible validation uses a temporary controller configuration, the public example
inventory, and a synthetic `vault_file` override. It clears inherited Ansible
environment overrides. Ansible lint syntax-checks every entry point; a separate
syntax-only harness imports every role task file in its owning role context.
These commands never invoke a playbook apply or verification run against devices.

Unit tests block sockets, DNS resolution and external processes by default.
Fixtures contain synthetic inputs and ephemeral keys. Tests cover DHCP merge
preservation/conflicts, Vault-encrypted WireGuard identity preservation,
check-mode refusal paths, VM ownership/hardware guards, UniFi firewall policy
and update failures, and interrupted artifact completion. Coverage applies to
the four focused planner/guard files, with an 85% branch-aware aggregate floor;
it is not a claim of coverage for all infrastructure workflows.

Gitleaks scans a temporary copy of Git-visible source rather than the working
directory containing private inventories, keys and backups. Findings are redacted.
Tracked private artifacts are rejected before copying any source for scanning.

Fast local checks omit Ansible lint and unit tests:

```bash
python3 tools/run-validation.py --quick
.venv-validation/bin/pre-commit install
.venv-validation/bin/pre-commit run --all-files
```

Use the macOS environment path for the pre-commit commands on a Mac. The hook
runs the fast command without modifying source files. CI runs the full command.
Selected checks can be run with `--checks python tests`, for example. Repository
privacy and contract checks always run first.

## Security audit

Run online vulnerability checks for runtime, validation and isolated SSH build dependencies and a redacted
scan of all local Git refs with:

```bash
python3 tools/run-validation.py --checks repository secrets --audit
```

The separate security workflow runs on pushes, pull requests and Mondays. It
fetches complete Git history. Audit findings and unavailable services produce a
failed status; they are not silently ignored.

The Paramiko dependency previously reported under
[CVE-2026-44405](https://github.com/advisories/GHSA-r374-rxx8-8654) has been removed.
The [SSH transport guide](ssh-transport.md) documents its replacement with pinned
native libssh and the explicit Cisco compatibility policy. Both dependency checks
and the security audit verify the Python/native SSH versions and policy-file
support; a Python package scan alone would miss outdated embedded native code.
The switch connection still requires legacy signatures/key exchange. Passing the
package audit does not establish modern cryptography on that connection.

## Maintenance and intentional exceptions

Refresh the existing role and entry-point tables after adding actions/playbooks:

```bash
.venv-validation/bin/python tools/update-validation-docs.py
```

Direct validation-tool dependencies live in `requirements-dev.in`; their resolved
dependencies live in `requirements-dev.txt`, constrained by runtime pins. Update
the lock with:

```bash
.venv-validation/bin/pip-compile --allow-unsafe --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements-dev.txt requirements-dev.in
```

Native binary versions and release asset hashes live in `tools/native-tools.json`.
Review upstream release checksums before changing them. CI actions are pinned to
commit hashes. Repository settings must separately require `Offline validation`
as a merge check if desired; adding the workflow does not change branch protection.

The following exceptions preserve established behavior:

- Ansible lint allows existing host-scoped workflow variable prefixes, lowercase
  `role: action` play names, and task key ordering. Other naming, schema,
  correctness and safety rules remain enabled.
- YAML lint accepts consistent sequence indentation and long assertions/code.
- Hadolint allows distribution package versions to follow signed repositories.
  The base image is digest-pinned and the Proxmox assistant is version-pinned.
- ShellCheck permits separate redirects for the recorded installer stages via
  `.shellcheckrc`, preserving the installer's exact bytes and seed identity.
- `prepare-opnsense-bootstrap.py` keeps its exact source bytes because they form
  part of existing seed identities. It still receives AST checks, correctness
  lint and embedded PHP syntax checks; formatting/import-order checks exclude it.

VM boot tests, live firmware/API integration, rendered cloud-init/service parser
validation, full restore rehearsals and complete workflow recovery coverage are
subsequent additions. This suite establishes offline lint and focused regression
coverage; runtime assertions remain necessary during actual infrastructure work.
