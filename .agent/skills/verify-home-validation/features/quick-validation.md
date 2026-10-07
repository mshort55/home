# Quick validation

Quick validation is the fast offline pass used before commit. It skips Ansible lint and unit tests and still runs the repository gate plus Python, YAML, shell, PHP, container, secrets, and dependency checks.

## Sub-features

- `quick-set` runs the seven checks below and then stops.
- `quick-skips` does not run Ansible lint or pytest.
- `quick-offline` does not add `--audit`.

## How to get to it (user POV)

- Run `python3 tools/run-validation.py --quick` from the repository root.
- Run `.venv-validation/bin/pre-commit run --all-files` after `pre-commit install`. That hook calls the same quick command. Drive the runner directly so the evidence is the validator output, not hook framing.

## Driving it with verify-home-validation

Preconditions:

- `drive doctor` prints `doctor: ok`.
- No other verification drive is running in this checkout.
- PHP CLI is the `php` doctor printed. The check syntax-checks `scripts/*.php` and the bootstrap builder's embedded PHP.

- **Run the fast set.** Run `.agent/skills/verify-home-validation/scripts/drive run quick-validation`. The command file ends with `tools/run-validation.py --quick`. Exit code is `0`. Stdout contains, in order, `Checking python...`, `Checking yaml...`, `Checking shell...`, `Checking php...`, `Checking containers...`, `Checking secrets...`, `Checking dependencies...`, `no leaks found`, `Verified ansible-pylibssh`, and `Validation passed.`. Stderr is empty. `git-status-same.txt` is `yes`.
- **Confirm the skips.** Stdout does not contain `Checking ansible...` or `Checking tests...`. The command file does not contain `--audit`.

## Gotchas

- `--checks` overrides `--quick` inside the runner. This feature's command passes `--quick` alone.
- `Checking php...` is followed by `No syntax errors detected` lines. Those lines are the PHP syntax result, not a network call.
- Dependency success includes the `Verified ansible-pylibssh` line from `tools/check-ssh.py`. That script opens a local session against a nonexistent policy file and expects the missing-file error. It does not log into a device.
- Quick mode is not the full suite. Ansible syntax import and coverage floors are `full-offline`.
