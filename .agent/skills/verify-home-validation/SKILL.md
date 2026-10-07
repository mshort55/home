---
name: verify-home-validation
description: Drive the home infrastructure repo's offline validation CLI and capture exit status, logs, and git status. Use when proving validation, lint, privacy, or test behavior without applying Ansible playbooks or reading inventory.private.yml.
---

# Verify home validation

The user-facing surface of this repo is the command line. People run `python3 tools/run-validation.py` from the repository root to prove the tree, and they run `ansible-playbook` only when they intend to change a device. This skill drives the validation CLI only.

`ansible.cfg` sets `inventory = inventory.private.yml` and `ask_vault_pass = True`. Do not run `ansible-playbook`, `ansible-vault`, or any file under `playbooks/` from this skill. The validation runner builds a temporary controller config that points at `inventory.example.yml` and a synthetic vault fixture, then deletes that config when the process exits. Device apply, check mode, and live read-back stay outside verification.

There is no server to keep up. Each drive is one short-lived process.

## Launch

From the repository root. Doctor prints that path as `root:`. This checkout resolves to `/Repos/home` (`/UbuntuSync/Repos/home` is the same tree):

```bash
.agent/skills/verify-home-validation/scripts/drive doctor
.agent/skills/verify-home-validation/scripts/drive run <feature>
```

`<feature>` is one of `repository-gate`, `python-checks`, `quick-validation`, `secrets-scan`, `full-offline`. The script refuses any other name, including `--audit`.

Ready means `doctor: ok` before the run, then a process that exits and writes `exit-code.txt`. A passing run prints `Validation passed.` on stdout and exits `0`. The runner is ready to be driven when doctor finds Python 3.12 in `.venv-validation` (`.venv-validation-macos` on Darwin), `php` on `PATH`, and executable `.cache/validation/bin/gitleaks` and `hadolint`.

One drive at a time in this checkout. The script refuses to start when a recorded verification pid is still alive. A second git worktree can run its own drive. Do not start `full-offline` beside another `full-offline`: both write the gitignored `.coverage` file and `.pytest_cache/` in the same tree.

The runner clears inherited `ANSIBLE_`, `GITLEAKS_`, `HADOLINT_`, `PYTEST_`, `COVERAGE_`, and `RUFF_` variables for the child. The harness sets `NO_COLOR=1` and `TERM=dumb`. Ruff in this environment still emits color on a pipe, so the harness removes ANSI CSI sequences from the saved logs. It does not export a vault password or `ANSIBLE_CONFIG`.

## Doctor

Run this first whenever a drive looks wrong:

```bash
.agent/skills/verify-home-validation/scripts/drive doctor
```

Pass output is exactly these labels: `doctor: ok`, `root:`, `python:` starting with `3.12`, `php:`, `gitleaks:`, `hadolint:`, and `scope: offline validation only; playbooks and inventory.private.yml are not driven`. Failure prints `doctor: fail` on stderr and exits `1`. Doctor does not start validation and does not contact the network.

## Drive

Read `.agent/skills/verify-home-validation/features/README.md`, then the feature file. Run:

```bash
.agent/skills/verify-home-validation/scripts/drive run <feature>
```

The script invokes `python3 tools/run-validation.py` with only that feature's arguments:

| Feature | Arguments |
|---|---|
| `repository-gate` | `--checks shell` |
| `python-checks` | `--checks python` |
| `quick-validation` | `--quick` |
| `secrets-scan` | `--checks secrets` |
| `full-offline` | none |

Repository contract checks always run before the named check and print nothing when they pass. The first `Checking ...` line is the signal that the gate allowed the run to continue. `--checks` wins over `--quick` inside the runner; this harness never passes both.

Treat stdout, stderr, the exit code, and `git-status-same.txt` as the result. Search the log text named in the feature file. Do not pin gitleaks timestamps, byte counts, or the ruff "N files already formatted" count.

## Evidence

Proof is written under `.cache/verification/<UTC-timestamp>/`, which is gitignored with the rest of `.cache/`. Cleanup must leave this directory in place.

Each run writes:

- `feature` — the feature id
- `command.txt` — the exact runner command
- `stdout.txt` and `stderr.txt` — the full streams
- `exit-code.txt` — the runner's exit code
- `git-status-before.txt`, `git-status-after.txt`, and `git-status-same.txt` — `git status --porcelain` around the run

A passing proof shows the user action (the command file), the resulting validator state (`Validation passed.` and the feature's `Checking` line), and the side effect (`git-status-same.txt` is `yes` for every feature except the extra gitignored coverage files called out on `full-offline`). A stderr line `Validation failed:` or a missing `Checking` line is a failed run, not a skip. Do not report a feature verified through a different feature's command.

`--audit` is a real user command and is not a drive target. It fetches vulnerability data and scans all Git history. Do not infer that an offline pass skipped the network unless the captured command has no `--audit` and the run did not print `Security audit failed`.

## Cleanup

```bash
.agent/skills/verify-home-validation/scripts/drive cleanup
```

Cleanup reads pid files under `.cache/verification/*/pid` and signals that process group (the session the harness started). It does not kill by process name. A finished run already removes its pid file, so cleanup then prints `cleanup: no verification process to stop`. Either way it prints `evidence retained under` the evidence root and does not delete logs.

The runner's own `home-validation-*` temporary directory is removed by that process when it exits. That directory is not the proof.

## Helpers

`scripts/drive` is the only helper. Invoke it by the paths in Launch, Doctor, Drive, and Cleanup. `drive` with no arguments prints usage and the feature names and exits `2`.
