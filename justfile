set positional-arguments
set default-list

# Prepare all repository dependencies; safe to repeat.
setup:
    python3 tools/setup.py

# Run the full offline validation suite; optional arguments are forwarded.
validate *args:
    @python3 tools/run-validation.py "$@"

# Audit dependency locks, the SSH build, and complete Git history (online).
audit:
    python3 tools/run-validation.py --checks repository secrets --audit

# Run Ansible with the native runtime environment; preserves interactive prompts.
playbook +args:
    @python3 tools/run-playbook.py "$@"
