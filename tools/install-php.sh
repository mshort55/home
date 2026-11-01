#!/usr/bin/env bash
# Provision the PHP runtime for offline validation; safe to repeat per container.
set -euo pipefail

php_ready() {
  command -v php >/dev/null 2>&1 &&
    php -r 'exit(class_exists("SimpleXMLElement") ? 0 : 1);'
}

if php_ready; then
  echo 'PHP CLI and SimpleXML are already available.'
  exit 0
fi

if [[ ! -r /etc/os-release ]]; then
  echo 'Install PHP CLI with SimpleXML using your OS package manager.' >&2
  exit 1
fi
# shellcheck source=/dev/null
. /etc/os-release
if [[ "${ID:-}" != ubuntu && "${ID:-}" != debian ]]; then
  echo 'Automatic PHP installation supports Ubuntu/Debian; install PHP with SimpleXML using your OS package manager.' >&2
  exit 1
fi

privilege=()
if [[ $EUID -ne 0 ]]; then
  privilege=(sudo)
fi
"${privilege[@]}" apt-get update
"${privilege[@]}" apt-get install --yes --no-install-recommends php-cli php-xml

if ! php_ready; then
  echo 'The active PHP CLI still lacks SimpleXML. Check php --ini and whether PATH selects a different PHP installation.' >&2
  exit 1
fi
echo 'PHP CLI and SimpleXML are ready for validation.'
