# Python checks

Python checks lint and format-check Git-visible Python and type stubs with Ruff, after the repository gate. The format command is `--check`, so a passing run does not rewrite source files.

## Sub-features

- `python-lint` reports Ruff lint clean.
- `python-format` reports that the tree is already formatted.
- `python-unchanged` leaves tracked git status unchanged.

## How to get to it (user POV)

- Run `python3 tools/run-validation.py --checks python` from the repository root.

## Driving it with verify-home-validation

Preconditions:

- `drive doctor` prints `doctor: ok`.
- No other verification drive is running in this checkout.

- **Lint and format.** Run `.agent/skills/verify-home-validation/scripts/drive run python-checks`. The command file ends with `tools/run-validation.py --checks python`. Exit code is `0`. Stdout contains `Checking python...`, `All checks passed!`, `already formatted`, and `Validation passed.`. Stderr is empty.
- **Confirm the tree was not rewritten.** `git-status-same.txt` is `yes`.
- **Confirm the narrow selection.** Stdout does not contain `Checking yaml...`, `Checking ansible...`, or `Checking tests...`.

## Gotchas

- The formatted-file count changes as the tree changes. Match `already formatted`, not a number.
- Saved `stdout.txt` has ANSI color sequences removed. Match `All checks passed!` there. A hand-run terminal may still color that line.
- Repository gate failures look like a Python failure but never print `Checking python...`.
- A format failure would have changed nothing only because `--check` refuses to write. `git-status-same.txt` of `no` means something else touched the tree during the run, so the proof is invalid.
