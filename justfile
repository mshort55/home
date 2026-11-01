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

# Verify migration status in the reviewed order against the live network.
verify-migration *args:
    @python3 tools/run-playbook.py \
        playbooks/verify-opnsense-vm.yml \
        playbooks/verify-opnsense-wireguard.yml \
        playbooks/verify-opnsense-wireguard-wifi.yml \
        playbooks/verify-opnsense-bmc.yml \
        playbooks/verify-opnsense-dev.yml \
        playbooks/verify-opnsense-unifi.yml \
        playbooks/verify-idrac-bmc-route.yml \
        playbooks/verify-unifi-vm.yml \
        playbooks/verify-unifi-config-ready.yml \
        playbooks/verify-unifi-site.yml \
        playbooks/verify-fedora-dev-vm.yml \
        playbooks/verify-fedora-dev-host.yml \
        playbooks/verify-fedora-dev-connectivity.yml \
        --limit 'pve01,opnsense01,unifi01,idrac01,dev01' "$@"
