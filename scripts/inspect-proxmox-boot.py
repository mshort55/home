"""Read-only maintenance preflight for the installed standalone firewall host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import cast


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout.strip()


def mapping(value: object) -> dict[str, object]:
    require(isinstance(value, dict), 'Expected a JSON object')
    result = cast(dict[object, object], value)
    require(all(isinstance(key, str) for key in result), 'Expected string keys')
    return cast(dict[str, object], result)


def protected(path: Path, mode: int | None = None) -> None:
    require(path.exists() and not path.is_symlink(), f'Missing or symlink path: {path}')
    info = path.stat()
    require(info.st_uid == 0 and not info.st_mode & 0o022, f'Unprotected path: {path}')
    if mode is not None:
        require(info.st_mode & 0o777 == mode, f'Unexpected permissions: {path}')


def main() -> None:
    node, vmid, guest, kernel, lab_payload = sys.argv[1:]
    lab = mapping(json.loads(lab_payload))
    require(lab.get('action') in ['startup', 'reboot'], 'Unexpected host maintenance action')
    require(os.geteuid() == 0 and socket.gethostname().split('.')[0] == node, 'Wrong maintenance host')
    require(vmid == '100' and re.fullmatch(r'[A-Za-z0-9_-]+', guest) is not None, 'Unexpected firewall identity')
    require(run('systemctl', 'is-enabled', 'pve-guests') == 'enabled', 'Guest boot service is not enabled')
    require(run('systemctl', 'is-active', 'pve-guests', 'pveproxy', 'pvedaemon', 'pvestatd').splitlines() == ['active'] * 4,
            'Proxmox services are not active')
    require(json.loads(run('pvesh', 'get', '/nodes/localhost/tasks', '--source', 'active', '--output-format', 'json')) == [],
            'Active Proxmox tasks require finishing before maintenance')
    require(json.loads(run('pvesh', 'get', '/cluster/ha/resources', '--output-format', 'json')) == [],
            'HA guests require a separate maintenance workflow')
    guests: object = json.loads(run('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'))
    require(isinstance(guests, list), 'Expected a complete guest allocation list')
    allocations = [mapping(item) for item in cast(list[object], guests)]
    require(len({item.get('vmid') for item in allocations}) == len(allocations), 'Duplicate guest allocation identity')
    firewalls = [item for item in allocations if item.get('vmid') == 100]
    require(len(firewalls) == 1, 'Missing or duplicate firewall allocation')
    allocation = firewalls[0]
    require(allocation.get('node') == node and allocation.get('vmid') == 100 and allocation.get('type') == 'qemu'
            and allocation.get('name') == guest and allocation.get('status') == 'running', 'Firewall allocation conflicts')
    for extra in [item for item in allocations if item.get('vmid') != 100]:
        controller = extra.get('vmid') == 110
        allocation_key, probe_key = ('unifi_allocation', 'unifi_probe') if controller else ('allocation', 'probe')
        require(extra.get('vmid') in [110, 200] and extra.get('node') == node and extra.get('type') == 'qemu'
                and lab.get(allocation_key) is not None, 'Unowned additional guest requires separate maintenance review')
        inspected = mapping(json.loads(run(sys.executable, '-c', str(lab[probe_key]), json.dumps(lab[allocation_key]), node)))
        previous = mapping(inspected['previous'])
        require(inspected.get('exists') is True and previous.get('phase') == 'complete', 'Complete the owned guest installation before host maintenance')
        require(controller or lab.get('action') != 'reboot' or inspected.get('state') == 'stopped',
                'Stop the development VM with stop-fedora-dev-vm.yml before host reboot; it has manual startup policy')

    directory = Path('/var/lib/home-automation/opnsense-100')
    record = directory / 'install.json'
    protected(directory, 0o700)
    protected(record, 0o600)
    require(directory.is_dir() and record.is_file(), 'Unexpected installation record type')
    installed = mapping(json.loads(record.read_text()))
    intent = mapping(installed['intent'])
    config = mapping(json.loads(run('pvesh', 'get', '/nodes/localhost/qemu/100/config', '--current', '1', '--output-format', 'json')))
    require(installed.get('phase') == 'complete' and intent.get('guest') == guest
            and str(config.get('scsi0', '')).split(',')[0] == intent.get('disk_volume'), 'Installation is incomplete or disk identity conflicts')
    require(config.get('ide2') == 'none,media=cdrom' and config.get('acpi', 1) == 1,
            'Eject installation media and retain ACPI shutdown before maintenance')

    # Bound reboot support to the unpinned GRUB layout created by this installer.
    for pin in ('/etc/kernel/proxmox-boot-pin', '/etc/kernel/proxmox-boot-next'):
        require(not os.path.lexists(pin), 'Pinned kernels require separate boot selection review')
    uuids = Path('/etc/kernel/proxmox-boot-uuids')
    require(not uuids.exists() or not uuids.read_text().strip(), 'Managed ESP boot selection requires a separate workflow')
    grub_environment = dict(line.split('=', 1) for line in run('grub-editenv', 'list').splitlines())
    require(not grub_environment.get('saved_entry') and not grub_environment.get('next_entry'),
            'GRUB saved or one-time selections require separate review')
    grub_defaults = [Path('/etc/default/grub'), *sorted(Path('/etc/default/grub.d').glob('*.cfg'))]
    for path in grub_defaults:
        protected(path)
        for line in path.read_text().splitlines():
            if re.match(r'^\s*GRUB_DEFAULT=', line):
                require(line.strip() in ('GRUB_DEFAULT=0', 'GRUB_DEFAULT="0"', "GRUB_DEFAULT='0'"), 'Non-default GRUB kernel selection')
    grub = Path('/boot/grub/grub.cfg')
    protected(grub)
    first_kernel = re.search(r'^\s*linux\s+/boot/vmlinuz-(\S+)', grub.read_text(), re.MULTILINE)
    require(first_kernel is not None and first_kernel.group(1) == kernel, 'Newest installed kernel is not the default GRUB kernel')
    require(Path('/boot/vmlinuz-' + kernel).is_file() and Path('/boot/initrd.img-' + kernel).is_file(), 'Missing selected kernel or initramfs')
    print(json.dumps({'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'default_kernel': kernel,
                      'installed_guest': guest, 'guest_start_service': 'enabled'}))


if __name__ == '__main__':
    main()
