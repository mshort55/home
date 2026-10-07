# Secrets scan

Secrets scan copies Git-visible source into a temporary directory and runs gitleaks there with redacted output. It does not scan `inventory.private.yml`, `secrets/`, `backups/`, or the rest of the ignored working tree.

## Sub-features

- `secrets-copy` scans a copy of tracked source rather than the working directory.
- `secrets-clean` reports that the copy has no leaks.
- `secrets-private-untouched` leaves private ignored files out of the scan and leaves git status unchanged.

## How to get to it (user POV)

- Run `python3 tools/run-validation.py --checks secrets` from the repository root.

## Driving it with verify-home-validation

Preconditions:

- `drive doctor` prints `doctor: ok`, including an executable gitleaks path.
- No other verification drive is running in this checkout.

- **Scan the public copy.** Run `.agent/skills/verify-home-validation/scripts/drive run secrets-scan`. The command file ends with `tools/run-validation.py --checks secrets`. Exit code is `0`. Stdout contains `Checking secrets...`, `no leaks found`, and `Validation passed.`. Stderr is empty. `git-status-same.txt` is `yes`.
- **Confirm the copy was temporary.** The evidence directory is `.cache/verification/<run-id>/`. It must not contain a `public-source` tree. The runner deletes its `home-validation-*` directory, including that copy, when the process exits.

## Gotchas

- Gitleaks prints a timestamp and a byte count. Match `no leaks found`, not those numbers.
- A finding on the working tree's private files is not what this check reports. Those paths are excluded on purpose. `--audit` scans Git history and is a different command.
- `Refusing to scan private or unsafe source path` on stderr is a failed gate inside the copier, not a clean scan.
- Do not point gitleaks at the repository root yourself. That would read ignored secrets.
