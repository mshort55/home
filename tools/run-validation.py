#!/usr/bin/env python3
"""Select the native validation environment for local hooks and convenience."""

import os
import platform
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
environment = ".venv-validation-macos" if platform.system() == "Darwin" else ".venv-validation"
python = root / environment / "bin/python"
if not python.is_file():
    raise SystemExit(f"Create {environment} using docs/validation.md before running validation")
os.execv(str(python), [str(python), str(root / "tools/validate.py"), *sys.argv[1:]])  # noqa: S606 -- Fixed local runner.
