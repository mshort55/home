#!/bin/sh
# Use the repository-pinned runner without installing a global command.
set -eu
repo=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
runner="$repo/.cache/validation/bin/just"
if [ ! -x "$runner" ]; then
    echo 'Run python3 tools/setup.py first to install the pinned Just runner.' >&2
    exit 1
fi
exec "$runner" --justfile "$repo/justfile" "$@"
