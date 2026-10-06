import hashlib
import io
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def installer(load_module):
    return load_module("tools/install-ssh.py")


def archive(name, content=b"synthetic source"):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        member = tarfile.TarInfo(name)
        member.size = len(content)
        output.addfile(member, io.BytesIO(content))
    return stream.getvalue()


def test_unverified_native_source_is_rejected_before_extraction(installer, tmp_path):
    data = archive("source/file")
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.extract_source(data, "0" * 64, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_source_archive_cannot_write_outside_build_directory(installer, tmp_path):
    destination = tmp_path / "build"
    destination.mkdir()
    data = archive("../escape")
    with pytest.raises(tarfile.FilterError):
        installer.extract_source(data, hashlib.sha256(data).hexdigest(), destination)
    assert not (tmp_path / "escape").exists()


def test_verified_source_extracts_into_its_own_directory(installer, tmp_path):
    data = archive("source/file")
    root = installer.extract_source(data, hashlib.sha256(data).hexdigest(), tmp_path)
    assert root == tmp_path / "source"
    assert (root / "file").read_bytes() == b"synthetic source"


def test_legacy_signatures_and_key_exchange_require_opt_in():
    from pylibsshext.session import Session

    session = Session()
    assert "ssh-rsa" not in session.get_ssh_options("hostkeys").split(",")
    assert all(not name.endswith("sha1") for name in session.get_ssh_options("key_exchange_algorithms").split(","))


def test_missing_device_policy_is_rejected_before_dns_or_connection(tmp_path):
    from pylibsshext.errors import LibsshSessionException
    from pylibsshext.session import Session

    with pytest.raises(LibsshSessionException, match="SSH config file does not exist"):
        Session().connect(host="unused.example.test", config_file=str(tmp_path / "missing"))


def test_source_patch_refuses_an_unexpected_upstream_layout(installer, tmp_path):
    path = tmp_path / "src/pylibsshext/includes/libssh.pxd"
    path.parent.mkdir(parents=True)
    path.write_text("unexpected upstream source\n")
    with pytest.raises(ValueError, match="source changed unexpectedly"):
        installer.enable_config_file(tmp_path)
    assert path.read_text() == "unexpected upstream source\n"


@pytest.mark.parametrize(
    "unsafe", ["StrictHostKeyChecking no", "Include /private/policy", "ProxyCommand arbitrary-command"]
)
def test_compatibility_file_cannot_disable_trust_or_run_external_commands(load_module, tmp_path, unsafe):
    checks = load_module("tools/repository_checks.py")
    path = tmp_path / "files/ssh/cisco-legacy.conf"
    path.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parent.parent / "files/ssh/cisco-legacy.conf"
    path.write_text(source.read_text() + unsafe + "\n")
    assert any("beyond the reviewed" in message for message in checks.ssh_policy_errors(tmp_path))


@pytest.mark.parametrize("url", ["http://source.example.test/file", "file:///private/file", "https:///missing-host"])
def test_native_source_scheme_is_rejected_before_network_access(installer, url):
    with pytest.raises(ValueError, match="require an HTTPS URL"):
        installer.download_source(url)


def test_native_source_redirect_outside_https_is_rejected_before_read(installer, monkeypatch):
    from unittest.mock import MagicMock

    response = MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = "http://source.example.test/file"
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="left HTTPS"):
        installer.download_source("https://source.example.test/file")
    response.read.assert_not_called()
