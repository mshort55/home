"""Stage an isolated HOME network and disabled WLAN using the official local API.

Network 10.6.106 contract: https://developer.ui.com/network/v10.6.106/openapi.json
No adoption, device actions, firmware, gateway configuration or WLAN activation.
"""

from __future__ import annotations

import fcntl
import http.client
import ipaddress
import json
import os
import re
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

VERSION = "10.6.106"
BASE = "/proxy/network/integration"

# Error bodies may echo the submitted SSID/PSK. Report only these documented
# field/constraint names; never a vendor message, rejected value or response body.
VALIDATION_FIELDS = {
    "type",
    "name",
    "enabled",
    "network",
    "networkId",
    "management",
    "vlanId",
    "dhcpGuarding",
    "securityConfiguration",
    "passphrase",
    "presharedKeys",
    "pmfMode",
    "fastRoamingEnabled",
    "wpa3FastRoamingEnabled",
    "saeConfiguration",
    "anticloggingThresholdSeconds",
    "syncTimeSeconds",
    "groupRekeyIntervalSeconds",
    "radiusConfiguration",
    "broadcastingFrequenciesGHz",
    "broadcastingDeviceFilter",
    "deviceIds",
    "deviceTagIds",
    "hideName",
    "clientIsolationEnabled",
    "multicastToUnicastConversionEnabled",
    "uapsdEnabled",
    "channel2gLockedTo6",
    "dtimPeriod2gLockedTo3",
    "advertiseDeviceName",
    "arpProxyEnabled",
    "bandSteeringEnabled",
    "bssTransitionEnabled",
    "mloEnabled",
    "hotspotConfiguration",
    "blackoutScheduleConfiguration",
    "clientFilteringPolicy",
    "multicastFilteringPolicy",
    "mdnsProxyConfiguration",
    "handoffSuggestionsConfiguration",
    "dnsAssistanceConfiguration",
    "dtimPeriodByFrequencyGHzOverride",
    "basicDataRateKbpsByFrequencyGHz",
}
VALIDATION_REASONS = {
    "NotNull",
    "NotBlank",
    "NotEmpty",
    "Size",
    "Min",
    "Max",
    "required",
    "must not be null",
    "INVALID_REQUEST",
    "INVALID_PAYLOAD",
    "VALIDATION_FAILED",
    "api.err.InvalidPayload",
    "api.err.InvalidValue",
}
API_ERROR_CODES = {
    "api.request.error",
    "api.authentication.missing-credentials",
    "api.authentication.invalid-credentials",
}


def rejection_summary(encoded: bytes) -> str:
    try:
        error = json.loads(encoded)
    except (ValueError, UnicodeDecodeError):
        return "validation details unavailable"
    text = json.dumps(error)
    fields = sorted(
        field
        for field in VALIDATION_FIELDS
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", text)
    )
    reasons = sorted(
        reason
        for reason in VALIDATION_REASONS
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(reason) + r"(?![A-Za-z0-9_])", text)
    )
    if isinstance(error, dict):
        if isinstance(error.get("code"), str) and error["code"] in API_ERROR_CODES:
            reasons.append(error["code"])
        if error.get("message") == "MLO setting requires all of [broadcasting on multiple bands, WPA3 security]":
            reasons.append("MLO setting requires multiple bands and WPA3 security")
    return (
        "validation fields: "
        + (", ".join(fields) or "unspecified")
        + "; constraints: "
        + (", ".join(reasons) or "unspecified")
    )


def protected(path: Path, directory: bool = False) -> None:
    if path.is_symlink() or not path.exists():
        raise ValueError("Missing or symlinked private UniFi input; follow the enrollment runbook")
    expected = 0o700 if directory else 0o600
    if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o777 != expected:
        raise ValueError("Private UniFi input must be owned by the controller user with mode 0700/0600")
    if (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise ValueError("Unexpected private UniFi input type")


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Unexpected UniFi API object")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Unexpected UniFi resource identifier")
    return value


class Api:
    def __init__(self, endpoint: str, key: str, certificate_file: Path, timeout: int) -> None:
        if not ipaddress.ip_address(endpoint).is_private or ":" in endpoint:
            raise ValueError("Only the enrolled private IPv4 controller is supported")
        protected(certificate_file)
        self.endpoint = endpoint
        self.key = key.strip() if isinstance(key, str) else ""
        if not self.key or any(character.isspace() for character in self.key):
            raise ValueError("The vaulted local API key must contain one nonempty token")
        certificate = certificate_file.read_text()
        self.certificate = ssl.PEM_cert_to_DER_cert(certificate)
        self.context = ssl.create_default_context(cafile=str(certificate_file))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.timeout = timeout
        self.writes = False

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in ["GET", "POST", "PUT"] or not path.startswith("/v1/"):
            raise ValueError("Unsupported UniFi API operation")
        connection = http.client.HTTPSConnection(self.endpoint, 11443, context=self.context, timeout=self.timeout)
        try:
            connection.connect()
            if connection.sock is None or connection.sock.getpeercert(binary_form=True) != self.certificate:
                raise ValueError("UniFi API certificate differs from the prepared identity")
            # Connect and pin before transmitting the key; never follow redirects or use environment proxies.
            if method != "GET":
                self.writes = True
            connection.request(
                method,
                BASE + path,
                body=json.dumps(body) if body is not None else None,
                headers={"X-API-Key": self.key, "Accept": "application/json", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            encoded = response.read(5 * 1024 * 1024 + 1)
            if len(encoded) > 5 * 1024 * 1024:
                raise ValueError("UniFi API response exceeds the bounded collection size")
            if response.status != (201 if method == "POST" else 200):
                resource = "WLAN" if "/wifi/broadcasts" in path else "network" if "/networks" in path else "read"
                if response.status in [400, 422]:
                    detail = rejection_summary(encoded)
                elif response.status in [401, 403]:
                    detail = "inspect local Integrations key/permissions"
                else:
                    detail = "request rejected; vendor response values withheld"
                raise ValueError(f"UniFi API {method} {resource} returned HTTP {response.status}; {detail}")
            return object_value(json.loads(encoded))
        finally:
            connection.close()

    def collection(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        total: int | None = None
        while True:
            page = self.request("GET", f"{path}?offset={len(rows)}&limit=200")
            count, reported_total, data = page.get("count"), page.get("totalCount"), page.get("data")
            if (
                type(count) is not int
                or type(reported_total) is not int
                or reported_total < 0
                or reported_total > 2000
                or not isinstance(data, list)
                or count != len(data)
                or page.get("offset") != len(rows)
                or (total is not None and total != reported_total)
            ):
                raise ValueError("Incomplete or concurrently changed UniFi API collection")
            total = reported_total
            rows.extend(object_value(row) for row in data)
            if len(rows) == total:
                ids = [identifier(row.get("id")) for row in rows]
                if len(set(ids)) != len(ids):
                    raise ValueError("Duplicate UniFi resource identifiers")
                return rows
            if not data or len(rows) > total:
                raise ValueError("Incomplete UniFi API pagination")


def snapshot(api: Api, site_id: str) -> dict[str, Any]:
    prefix = f"/v1/sites/{site_id}"
    return {
        "devices": api.collection(prefix + "/devices"),
        "networks": [
            api.request("GET", prefix + "/networks/" + identifier(row["id"]))
            for row in api.collection(prefix + "/networks")
        ],
        "wifi": [
            api.request("GET", prefix + "/wifi/broadcasts/" + identifier(row["id"]))
            for row in api.collection(prefix + "/wifi/broadcasts")
        ],
    }


def wifi_inputs(value: Any) -> dict[str, str]:
    value = object_value(value)
    if set(value) != {"ssid", "passphrase"} or not all(isinstance(item, str) for item in value.values()):
        raise ValueError("Vaulted Wi-Fi inputs must contain only string ssid and passphrase fields")
    if not 1 <= len(value["ssid"].encode()) <= 32 or any(ord(c) < 32 for c in value["ssid"]):
        raise ValueError("SSID must contain 1–32 UTF-8 bytes without control characters")
    if not 8 <= len(value["passphrase"]) <= 63 or any(not 32 <= ord(c) <= 126 for c in value["passphrase"]):
        raise ValueError("Use an 8–63 character printable ASCII Wi-Fi passphrase")
    return value


def desired_wifi(inputs: dict[str, str], network_id: str) -> dict[str, Any]:
    return {
        "type": "STANDARD",
        "name": inputs["ssid"],
        "enabled": False,
        "network": {"type": "SPECIFIC", "networkId": network_id},
        "securityConfiguration": {
            "type": "WPA2_WPA3_PERSONAL",
            "passphrase": inputs["passphrase"],
            "pmfMode": "OPTIONAL",
            "fastRoamingEnabled": False,
            "wpa3FastRoamingEnabled": False,
            "saeConfiguration": {"anticloggingThresholdSeconds": 5, "syncTimeSeconds": 5},
        },
        "broadcastingFrequenciesGHz": [2.4, 5],
        "broadcastingDeviceFilter": None,
        "hideName": False,
        "clientIsolationEnabled": False,
        "multicastToUnicastConversionEnabled": False,
        "uapsdEnabled": False,
        "channel2gLockedTo6": False,
        "dtimPeriod2gLockedTo3": False,
        "advertiseDeviceName": False,
        "arpProxyEnabled": False,
        "bandSteeringEnabled": False,
        # Network 10.6.106 validates MLO prerequisites when this optional field
        # is present, even for false. Omit it for the compatibility profile;
        # readback checks below
        # still require the feature to be absent or explicitly disabled.
        "bssTransitionEnabled": False,
        "hotspotConfiguration": None,
        "blackoutScheduleConfiguration": None,
        "clientFilteringPolicy": None,
        "multicastFilteringPolicy": None,
        "mdnsProxyConfiguration": None,
        "handoffSuggestionsConfiguration": None,
    }


def matches(actual: dict[str, Any], desired: dict[str, Any]) -> bool:
    for key, expected in desired.items():
        value = actual.get(key)
        if isinstance(expected, dict):
            if not isinstance(value, dict) or not matches(value, expected):
                return False
        elif (isinstance(expected, bool) and type(value) is not bool) or value != expected:
            return False
    return True


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    protected(path.parent, True)
    if path.exists() or path.is_symlink():
        protected(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".unifi-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def plan(
    current: dict[str, Any], record: dict[str, Any], inputs: dict[str, str]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    if current["devices"]:
        raise ValueError("Isolated staging requires zero adopted devices; AP migration is a separate action")
    network: dict[str, Any] | None = None
    wifi: dict[str, Any] | None = None
    for field, rows in [("network_id", current["networks"]), ("wifi_id", current["wifi"])]:
        recorded = record.get(field)
        selected = [row for row in rows if row["id"] == recorded] if recorded else []
        if recorded and len(selected) != 1:
            raise ValueError("An owned UniFi resource was removed; refusing automatic recreation")
        if field == "network_id":
            network = selected[0] if selected else None
        else:
            wifi = selected[0] if selected else None
    if any(
        row is not network and (row.get("name") == "HOME" or row.get("vlanId") == 20) for row in current["networks"]
    ):
        raise ValueError("An unowned HOME name or VLAN 20 exists; no automatic resource takeover")
    if any(row is not wifi for row in current["wifi"]):
        raise ValueError("An unowned WLAN exists; inspect the clean-controller baseline before staging")
    if network and (
        network.get("default") is not False
        or network.get("management") != "UNMANAGED"
        or network.get("metadata", {}).get("origin") != "USER_DEFINED"
    ):
        raise ValueError("Owned HOME network type or ownership differs")
    if wifi and (
        wifi.get("enabled") is not False
        or wifi.get("type") != "STANDARD"
        or wifi.get("metadata", {}).get("origin") != "USER_DEFINED"
    ):
        raise ValueError("Owned WLAN is active or its type/ownership differs; staging cannot alter it")
    if wifi and wifi.get("mloEnabled") is not None and wifi.get("mloEnabled") is not False:
        raise ValueError("Owned WLAN has an unexpected MLO setting; inspect before staging")
    changes: list[str] = []
    desired_network = {"management": "UNMANAGED", "name": "HOME", "vlanId": 20, "enabled": True, "dhcpGuarding": None}
    if network is None or not matches(network, desired_network):
        changes.append("HOME VLAN 20 definition")
    if wifi is None or not matches(wifi, desired_wifi(inputs, identifier(network["id"]) if network else "unallocated")):
        changes.append("disabled household WLAN")
    # Fail closed if an API masks the password; never pretend a masked secret is verified.
    if wifi:
        saved_secret = wifi.get("securityConfiguration", {}).get("passphrase")
        if not isinstance(saved_secret, str) or (
            saved_secret != inputs["passphrase"] and saved_secret and set(saved_secret) <= {"*", "•"}
        ):
            raise ValueError("API omits or masks the WLAN passphrase; exact secret drift verification is unavailable")
    return network, wifi, changes


def reconcile(api: Api, mode: str, settings: dict[str, Any]) -> dict[str, Any]:
    installed_version = api.request("GET", "/v1/info").get("applicationVersion")
    if installed_version != VERSION:
        observed = (
            installed_version
            if isinstance(installed_version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", installed_version)
            else "missing or malformed"
        )
        raise ValueError(
            f"Installed UniFi Network version {observed} differs from the pinned {VERSION} API contract; no API writes performed"
        )
    sites = api.collection("/v1/sites")
    selected = [row for row in sites if row["id"] == settings.get("site_id")] if settings.get("site_id") else sites
    if len(selected) != 1:
        raise ValueError("Select one exact site ID when the controller has multiple sites")
    site_id = identifier(selected[0]["id"])
    current = snapshot(api, site_id)
    result: dict[str, Any] = {
        "changed": False,
        "application_version": VERSION,
        "site_id": site_id,
        "adopted_devices": len(current["devices"]),
        "network_count": len(current["networks"]),
        "wlan_count": len(current["wifi"]),
        "action": mode,
    }
    if mode == "inspect":
        return result
    inputs = wifi_inputs(settings["wifi"])
    directory = Path(settings["state_directory"])
    record_path = directory / "ownership.json"
    record: dict[str, Any] = {}
    if directory.exists() or directory.is_symlink():
        protected(directory, True)
    if record_path.exists() or record_path.is_symlink():
        protected(record_path)
        record = object_value(json.loads(record_path.read_text()))
        if (
            record.get("version") != 1
            or record.get("endpoint") != api.endpoint
            or record.get("site_id") != site_id
            or record.get("phase") not in ["pending", "complete"]
        ):
            raise ValueError("UniFi staging ownership record conflicts")
        protected(directory / "before.json")
    network, wifi, changes = plan(current, record, inputs)
    result["changes"] = changes
    result["wlan_enabled"] = False
    result["home_vlan"] = 20
    if mode == "verify":
        if changes or record.get("phase") != "complete":
            raise ValueError("Desired isolated UniFi staging is incomplete or has drifted")
        return result
    if mode == "plan":
        result["changed"] = bool(changes) or record.get("phase") != "complete"
        return result
    if not changes and record.get("phase") == "complete":
        return result
    if snapshot(api, site_id) != current:
        raise ValueError("UniFi configuration changed during preparation; no writes performed")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    protected(directory, True)
    # Exports may contain WLAN secrets and remain private. Preserve the original once.
    backup_path = directory / "before.json"
    if not backup_path.exists():
        atomic_json(backup_path, current)
    protected(backup_path)
    record = record or {"version": 1, "endpoint": api.endpoint, "site_id": site_id}
    record["phase"] = "pending"
    atomic_json(record_path, record)
    prefix = f"/v1/sites/{site_id}"
    desired_network = {"management": "UNMANAGED", "name": "HOME", "vlanId": 20, "enabled": True, "dhcpGuarding": None}
    if "HOME VLAN 20 definition" in changes:
        network = api.request(
            "PUT" if network else "POST",
            prefix + "/networks" + ("/" + identifier(network["id"]) if network else ""),
            desired_network,
        )
        record["network_id"] = identifier(network["id"])
        atomic_json(record_path, record)
    if network is None:
        raise ValueError("HOME allocation did not return a resource")
    # Refuse an adopted device or concurrent unrelated change before the second write.
    latest = snapshot(api, site_id)
    expected = {
        **current,
        "networks": [row for row in current["networks"] if row["id"] != record["network_id"]] + [network],
    }
    if (
        latest["devices"]
        or latest["wifi"] != current["wifi"]
        or sorted(latest["networks"], key=lambda r: r["id"]) != sorted(expected["networks"], key=lambda r: r["id"])
    ):
        raise ValueError("UniFi changed during staged allocation; inspect protected pending ownership before resuming")
    if "disabled household WLAN" in changes:
        payload = desired_wifi(inputs, identifier(network["id"]))
        wifi = api.request(
            "PUT" if wifi else "POST",
            prefix + "/wifi/broadcasts" + ("/" + identifier(wifi["id"]) if wifi else ""),
            payload,
        )
        record["wifi_id"] = identifier(wifi["id"])
        atomic_json(record_path, record)
    _, _, remaining = plan(snapshot(api, site_id), record, inputs)
    if remaining:
        raise ValueError("UniFi did not save the exact staging payload; inspect the protected pending record")
    record["phase"] = "complete"
    atomic_json(record_path, record)
    result["changed"] = True
    result["backup"] = str(backup_path)
    return result


def main() -> None:
    api: Api | None = None
    lock: Any = None
    try:
        mode = sys.argv[1]
        if mode not in ["inspect", "plan", "apply", "verify"]:
            raise ValueError("An explicit supported UniFi staging action is required")
        settings = object_value(json.load(sys.stdin))
        timeout = settings["timeout"]
        if type(timeout) is not int or not 1 <= timeout <= 60:
            raise ValueError("Timeout must be 1–60 seconds")
        api = Api(settings["endpoint"], settings["api_key"], Path(settings["certificate_file"]), timeout)
        if mode == "apply":
            directory = Path(settings["state_directory"])
            if directory.exists() or directory.is_symlink():
                protected(directory, True)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            protected(directory, True)
            lock_path = directory / "operation.lock"
            if lock_path.exists() or lock_path.is_symlink():
                protected(lock_path)
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            lock = os.fdopen(descriptor, "r+")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another controller process is already applying this UniFi site") from None
        print(json.dumps(reconcile(api, mode, settings)))
    except Exception as error:
        # Vendor responses, payloads and tracebacks can contain keys/passwords.
        safe = (
            str(error)
            if type(error) is ValueError and not isinstance(error, json.JSONDecodeError)
            else "UniFi staging failed; inspect protected inputs and local API/TLS reachability"
        )
        print(json.dumps({"changed": bool(api and api.writes), "error": safe}))
        print(safe, file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    main()
