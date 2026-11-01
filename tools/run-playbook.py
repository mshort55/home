#!/usr/bin/env python3
"""Run Ansible from the native runtime environment, preserving argv and terminal IO."""

import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    environment = ".venv-macos" if platform.system() == "Darwin" else ".venv"
    executable = ROOT / environment / "bin/ansible-playbook"
    if not executable.is_file():
        raise SystemExit("Run python3 tools/setup.py before running playbooks.")
    if not sys.argv[1:]:
        raise SystemExit("Supply a playbook and its Ansible arguments.")
    os.chdir(ROOT)
    os.execv(str(executable), [str(executable), *sys.argv[1:]])  # noqa: S606 -- Explicit native Ansible executable; user arguments remain separate argv entries.


if __name__ == "__main__":
    main()
