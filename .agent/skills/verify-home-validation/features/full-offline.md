# Full offline validation

Full offline validation is the default local command and the command CI runs. It runs every offline check, including Ansible lint, a syntax-only import of every role task file, and unit tests with coverage floors. It does not apply device configuration.

## Sub-features

- `full-checks` runs repository, Python, YAML, Ansible, shell, PHP, containers, secrets, tests, and dependencies.
- `full-ansible-syntax` imports role tasks with `--syntax-check` and does not execute them.
- `full-coverage` enforces the focused coverage floors and prints the measured percentage.

## How to get to it (user POV)

- Run `python3 tools/run-validation.py` from the repository root with no extra arguments.

## Driving it with verify-home-validation

Preconditions:

- `drive doctor` prints `doctor: ok`.
- No other verification drive is running in this checkout. This run writes gitignored `.coverage` and `.pytest_cache/`.
- Allow several minutes. The runner's per-command timeout is 600 seconds.

- **Run the default command.** Run `.agent/skills/verify-home-validation/scripts/drive run full-offline`. The command file ends with `tools/run-validation.py` and does not contain `--checks` or `--audit`. Exit code is `0`. Stdout contains each of `Checking python...`, `Checking yaml...`, `Checking ansible...`, `Checking shell...`, `Checking php...`, `Checking containers...`, `Checking secrets...`, `Checking tests...`, and `Checking dependencies...`, then `Validated `, `entry points and all role task files`, `Focused branch-aware coverage:`, `no leaks found`, and `Validation passed.`. The repository gate prints no `Checking repository...` line. Stderr is empty.
- **Confirm tracked files stayed put.** `git-status-same.txt` is `yes`. Gitignored `.coverage` and `.pytest_cache/` may change; that is the test run's local data, not a device change.
- **Confirm Ansible did not apply.** Stdout contains `Validated ` from the syntax-check harness. It must not contain a play recap. The temporary Ansible config used `inventory.example.yml` and is gone when the process exits.

## Gotchas

- `--syntax-check` loads role task files and resolves modules. It is not a device run, and it is also not proof that a playbook would succeed against hardware.
- Coverage text includes a percentage. Match `Focused branch-aware coverage:` rather than a fixed number.
- Unit tests block sockets and external processes. A failure that mentions network access is a test bug, not a prompt to retry online.
- Two overlapping full runs in one checkout share `.coverage`. The harness rejects a second start only when the first pid file is still present.
- Passing this command does not pass `--audit`.
