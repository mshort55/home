# Home validation verification map

This directory is the maintained source for verifying the offline validation CLI. Read this index before driving a feature, then use that feature's file as the recipe.

Playbook applies are not features of this map. `ansible.cfg` points at `inventory.private.yml`.

## Baseline preconditions

- Working directory is the repository root, the directory that contains `tools/run-validation.py` and `ansible.cfg`.
- `.agent/skills/verify-home-validation/scripts/drive doctor` prints `doctor: ok` and Python `3.12`.
- No verification pid file under `.cache/verification/*/pid` refers to a live process.
- Drive only the feature ids listed below. Do not pass `--audit`, a playbook path, or `inventory.private.yml`.

## Driving conventions

- Start from the repository root.
- Run `.agent/skills/verify-home-validation/scripts/drive run <feature>`.
- One drive at a time in this checkout.
- Read `command.txt`, `stdout.txt`, `stderr.txt`, `exit-code.txt`, and `git-status-same.txt` in the printed evidence directory.
- Keep those files. Cleanup stops a live process and does not delete evidence.
- A gate failure exits `1` with messages on stderr and never prints `Checking`.

## Proof and skip reporting

- Record the feature id, the evidence directory, the exit code, and whether git status was unchanged.
- A pass needs `exit-code.txt` of `0`, stdout containing `Validation passed.`, the feature's `Checking` line, and empty stderr.
- `repository-gate`, `python-checks`, `quick-validation`, and `secrets-scan` also need `git-status-same.txt` of `yes`.
- `full-offline` may refresh gitignored `.coverage` and `.pytest_cache/`. Tracked porcelain must still match.
- Do not treat a skipped feature as verified by another feature's run.

## Feature entry contract

Each feature file has an H1, one introductory paragraph, then four H2 sections: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify-home-validation`, and `Gotchas`.

## Features

- [Repository gate](./repository-gate.md) covers the contract checks that run before every validation command.
- [Python checks](./python-checks.md) covers Ruff lint and format check on Git-visible Python.
- [Quick validation](./quick-validation.md) covers the fast offline set that omits Ansible lint and unit tests.
- [Secrets scan](./secrets-scan.md) covers the redacted gitleaks scan of a Git-visible source copy.
- [Full offline validation](./full-offline.md) covers the default command, including Ansible syntax import and unit tests.
