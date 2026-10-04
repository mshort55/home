"""Create stable X25519 keys using the controller's unlocked Ansible Vault."""
from __future__ import annotations

import base64
import json
import ipaddress
import os
import re
import stat
from pathlib import Path
from typing import Any, cast

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase
from ansible.parsing.vault import VaultLib, match_encrypt_secret
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption


def keypair() -> dict[str, str]:
    raw = bytearray(X25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    raw[0] &= 248
    raw[31] = (raw[31] & 127) | 64
    key = X25519PrivateKey.from_private_bytes(bytes(raw))
    return {"private": base64.b64encode(raw).decode(), "public": base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()}


def protect(path: Path, mode: int, directory: bool = False) -> None:
    metadata = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode or metadata.st_uid != os.getuid():
        raise AnsibleActionFail("WireGuard artifacts must be owned, protected, and free of symlinks.")


def validate_pair(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"private", "public"}:
        raise AnsibleActionFail("Invalid saved WireGuard key pair; refusing replacement.")
    try:
        private = base64.b64decode(value["private"], validate=True)
        public = base64.b64decode(value["public"], validate=True)
        derived = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if len(public) != 32 or public != derived:
            raise ValueError("Key mismatch")
    except (ValueError, TypeError, KeyError) as error:
        raise AnsibleActionFail("Saved WireGuard keys do not match; refusing rotation.") from error


def validate_networks(settings: dict[str, Any]) -> None:
    try:
        tunnel = ipaddress.IPv4Network(settings['tunnel_subnet'])
        management = ipaddress.IPv4Network(settings['management_subnet'])
        home = ipaddress.IPv4Network(settings['endpoint'] + '/24', strict=False)
        server = ipaddress.IPv4Address(settings['server_address'])
        client = ipaddress.IPv4Address(settings['peer_address'])
        if any(network.prefixlen != 24 or not network.subnet_of(ipaddress.IPv4Network('10.0.0.0/8')) for network in (tunnel, management, home)):
            raise ValueError('Unsupported subnet')
        if tunnel.overlaps(management) or tunnel.overlaps(home) or management.overlaps(home):
            raise ValueError('Overlapping subnets')
        if server == client or any(address not in tunnel or address in (tunnel.network_address, tunnel.broadcast_address) for address in (server, client)):
            raise ValueError('Invalid tunnel addresses')
        for name in ('management_address', 'proxmox_address', 'switch_address'):
            address = ipaddress.IPv4Address(settings[name])
            if address not in management or address in (management.network_address, management.broadcast_address):
                raise ValueError('Invalid management target')
    except (ValueError, TypeError, KeyError) as error:
        raise AnsibleActionFail('WireGuard requires distinct private /24 networks and ordinary IPv4 target addresses.') from error


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _supports_check_mode = True

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = super().run(tmp, task_vars)
        args: dict[str, Any] = self._task.args
        if set(args) != {"directory", "identity", "settings"} or not isinstance(args["directory"], str) or not isinstance(args["identity"], str) or not isinstance(args['settings'], dict):
            raise AnsibleActionFail("Supply a controller directory and inventory identity.")
        validate_networks(args['settings'])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args["identity"]):
            raise AnsibleActionFail("Invalid WireGuard inventory identity.")
        directory = Path(args["directory"])
        if not directory.is_absolute():
            raise AnsibleActionFail("WireGuard artifact directory must be absolute.")
        path = directory / "keys.vault.yml"
        # Encryption uses the same secret Ansible already obtained for this run.
        vault = cast(VaultLib, self._loader._vault)
        if not vault.secrets:
            raise AnsibleActionFail("Unlock Ansible Vault for key preparation; no additional password is needed.")
        for parent in [directory, *directory.parents]:
            if parent.is_symlink():
                raise AnsibleActionFail("WireGuard artifact paths must not traverse symlinks.")
        exists = path.exists() or path.is_symlink()
        if directory.exists():
            protect(directory, 0o700, True)
        client_file = directory / 'home-admin.conf'
        if client_file.exists() or client_file.is_symlink():
            protect(client_file, 0o600)
            if not exists:
                raise AnsibleActionFail('Restore the original encrypted keys; refusing to replace an existing Mac client identity.')
        if exists:
            protect(path, 0o600)
            ciphertext = path.read_bytes()
            if not VaultLib.is_encrypted(ciphertext):
                raise AnsibleActionFail("Saved WireGuard keys must be Vault encrypted.")
            data = json.loads(vault.decrypt(ciphertext))
            if set(data) != {"version", "identity", "server", "client"} or data["version"] != 1 or data["identity"] != args["identity"]:
                raise AnsibleActionFail("Saved WireGuard identity conflicts; refusing replacement.")
            validate_pair(data["server"])
            validate_pair(data["client"])
            if data["server"]["public"] == data["client"]["public"]:
                raise AnsibleActionFail("WireGuard server and client keys must differ.")
        elif not self._task.check_mode:
            data = {"version": 1, "identity": args["identity"], "server": keypair(), "client": keypair()}
            vault_id, secret = match_encrypt_secret(vault.secrets)
            encrypted = vault.encrypt(json.dumps(data), secret=secret, vault_id=vault_id)
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            protect(directory, 0o700, True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
        result.update(changed=not exists, exists=exists or not self._task.check_mode, path=str(path))
        return result
