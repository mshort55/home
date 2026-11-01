# Automated validation

Validation uses Python 3.12 and a separate pinned environment. Runtime playbooks
continue to use the environment and private inputs described in the README.

## Setup

Use the shared repository setup command with Python 3.12 or later:

```bash
python3 tools/setup.py
./just validate
```

Setup prepares both runtime and validation dependencies. It selects `.venv-validation`
on Linux and `.venv-validation-macos` on macOS, preserving the separate native
environments when sharing the repository. See the [setup prerequisites](../README.md#install-the-pinned-local-environment).
CI uses the same setup command and `./just validate` (or `./just audit`).
`python3 tools/run-validation.py` remains available as a direct entry point.
Pre-commit runs the full suite through `./just validate`. Validation itself never installs packages or configures devices.

PHP CLI with SimpleXML is included in setup. `tools/install-php.sh` remains available
for focused PHP repair on Ubuntu/Debian. ShellCheck comes from `shellcheck-py`.
The native tool installer verifies committed SHA-256 values before installing
Hadolint, Gitleaks and Just into `.cache/validation/bin`; setup reuses matching installed
versions. Linux and macOS on ARM64 and x86-64 are supported by those tools.
Setup needs internet access for missing dependencies; standard validation is offline.

## Checks

The full command checks repository privacy and whitespace, YAML/Python/Jinja and
embedded Python syntax, role actions/defaults, documentation tables and local
file links, ignore rules, and Ansible trust/privacy settings. It runs Ruff lint
and formatting, YAML lint, Ansible lint, shell syntax/ShellCheck, PHP syntax
(including the bootstrap builder's embedded PHP), Hadolint, Gitleaks on
Git-visible source, isolated unit tests with branch coverage, and installed
Python/collection version checks.

The PHP check also runs `tests/php/pilot-ownership.php` against the actual pilot
collection guard with synthetic vendor models and temporary protected artifacts.
It verifies exact UniFi rule/DNS retention, ownership and drift refusals, and
preservation of existing UUID-owned workflows without device or network access.

Ansible validation uses a temporary controller configuration, the public example
inventory, and a synthetic `vault_file` override. It clears inherited Ansible
environment overrides. Ansible lint syntax-checks every entry point; a separate
syntax-only harness imports every role task file in its owning role context.
These commands never invoke a playbook apply or verification run against devices.

The temporary config also removes any operational `vault_password_file` and
`vault_identity_list` settings; syntax validation neither invokes private Vault
helpers nor needs a Vault unlock password.

Unit tests block sockets, DNS resolution and external processes by default.
Fixtures contain synthetic inputs and ephemeral keys. Tests cover DHCP merge
preservation/conflicts, Vault-encrypted WireGuard identity preservation,
check-mode refusal paths, VM ownership/hardware guards, UniFi firewall policy
and update failures, and interrupted artifact completion. Coverage applies to
all maintained Python in `scripts`, `plugins` and `tools`, including unexecuted
modules and namespace directories. The whole-source branch-aware regression
floor is 29.5%; the four focused planner/guard files retain their separate 85%
aggregate floor and individual floors of 95%, 95%, 85% and 80%. The runner rejects
any Git-visible production Python missing from the coverage report, so adding a
new source directory requires adding it to coverage too. Many workflows still
need behavior tests; the focused percentage is not a whole-repository claim.

Ruff checks all Git-visible Python and type stubs, including root-level files,
with security, exception, logging, debugger and suppression rules enabled.
Pytest rejects warnings and unexpected xfail successes. The runner clears inherited
Ansible, Gitleaks, Hadolint, Ruff, pytest and coverage environment overrides so
operator settings cannot weaken the configured checks.

YAML rejects empty values, boolean-like keys, duplicate anchors and duplicate
merge keys. Workflow event names use quoted `'on'` and explicit empty mappings.
All Git-visible Dockerfiles, including nested and variant names, receive Hadolint
checks; external base images must have literal SHA-256 digests.

## Deliberate exceptions

- The bootstrap builder is excluded only from formatting because its bytes
  determine existing media identities. It receives normal linting with five
  documented rule exceptions for existing formatting/exception patterns and
  reviewed checksum-verified XML and subprocess inputs. A media recipe migration
  is required before editing this builder.
- Administrative subprocess calls, the SafeLoader subclass, infrastructure-only
  Jinja parser and CLI secret-redaction boundary have local, rule-specific Ruff
  exceptions. New call sites are checked normally. Test assertions are exempt
  only from `S101`; en dashes remain allowed in human-readable messages.
- Ansible retains role-variable prefix, name casing and task ordering exceptions
  to preserve shared outputs and avoid broad cosmetic changes. Safety is extended
  with fully qualified module names, ignored-error/change-reporting checks and
  opt-in password-logging/archive-owner checks; findings, including warnings,
  fail validation. The experimental `args` rule is deferred because it reports
  inherited group `module_defaults` as missing arguments. Immediate guarded
  reloads remain immediate rather than moving to deferred handlers.
- Distribution packages intentionally follow signed repositories. `DL3008`
  exceptions are attached only to the current installation instructions;
  future Dockerfiles must pin packages or document their own exception.
- Long lines, optional document-start markers, comment alignment and flexible
  brace/list spacing remain readability choices. Private inputs, environments,
  vendor downloads and device backups stay outside source validation.

## Source privacy and local hooks

Gitleaks scans a temporary copy of Git-visible source rather than the working
directory containing private inventories, keys and backups. Findings are redacted.
Tracked private artifacts are rejected before copying any source for scanning.

Run the full validation suite locally and enable the same check before commits:

```bash
./just validate
.venv-validation/bin/pre-commit install
.venv-validation/bin/pre-commit run --all-files
```

Use the macOS environment path for the pre-commit commands on a Mac. The hook
runs `./just validate` without modifying source files, matching CI.
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
