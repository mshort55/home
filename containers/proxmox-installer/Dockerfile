FROM debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The Proxmox package is pinned; APT checks the signed repository metadata.
RUN set -eu; \
    apt-get update; \
    apt-get install --yes --no-install-recommends ca-certificates curl python3 whois xorriso; \
    curl --fail --silent --show-error --location \
      https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg \
      --output /usr/share/keyrings/proxmox-archive-keyring.gpg; \
    echo '136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45  /usr/share/keyrings/proxmox-archive-keyring.gpg' | sha256sum --check; \
    printf '%s\n' 'deb [signed-by=/usr/share/keyrings/proxmox-archive-keyring.gpg] http://download.proxmox.com/debian/pve trixie pve-no-subscription' > /etc/apt/sources.list.d/proxmox.list; \
    apt-get update; \
    apt-get install --yes --no-install-recommends proxmox-auto-install-assistant=9.2.8; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work
