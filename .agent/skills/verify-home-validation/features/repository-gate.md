# Repository gate

Every validation command checks privacy, whitespace, source syntax, documentation tables, ignore rules, and Ansible trust settings before it prints a check name. A failing gate stops the run with exit code 1 and does not start the selected check.

## Sub-features

- `gate-pass` lets the selected check start after a clean contract check.
- `gate-block` stops on stderr before any `Checking` line when a contract fails.

## How to get to it (user POV)

- Run `python3 tools/run-validation.py` from the repository root.
- Run `python3 tools/run-validation.py --quick`.
- Run `python3 tools/run-validation.py --checks <name>`.

The gate has no separate flag. It runs first on each of those commands.

## Driving it with verify-home-validation

Preconditions:

- `drive doctor` prints `doctor: ok`.
- No other verification drive is running in this checkout.

- **Pass the gate.** Run `.agent/skills/verify-home-validation/scripts/drive run repository-gate`. The command file ends with `tools/run-validation.py --checks shell`. Exit code is `0`. Stdout contains `Checking shell...` and `Validation passed.`. Stderr is empty. `git-status-same.txt` is `yes`.
- **Observe the block shape without planting a fault.** Do not add a private file, conflict marker, or bad symlink to force a failure. A real failure prints one or more contract lines on stderr (for example `forbidden source artifact:`, `whitespace/newline violation:`, `outdated documentation table:`, or `Ansible trust/privacy configuration changed:`) and does not print `Checking`. Exit code is `1`.

## Gotchas

- Success is silent. Reaching `Checking shell...` is the proof the gate returned no errors.
- `--checks shell` is only the smallest command that still must pass the gate. It does not prove Ruff, gitleaks, Ansible, or tests.
- The committed `ansible.cfg` still names `inventory.private.yml`. This run does not invoke Ansible.
- Injecting a forbidden path to watch the gate fail dirties the tree the next run will judge. Report a live failure if one appears; do not create one.
