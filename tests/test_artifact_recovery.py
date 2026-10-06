import base64
import bz2
import hashlib
import json

import pytest


@pytest.fixture
def media(load_module, tmp_path):
    module = load_module("scripts/prepare-opnsense-iso.py")
    image = b"synthetic-ISO-bytes-for-recovery-tests"
    archive = tmp_path / "fixture.iso.bz2"
    archive.write_bytes(bz2.compress(image))
    key = tmp_path / "signing-public.txt"
    key.write_text("synthetic-public-key")
    (tmp_path / "fixture.iso.sig").write_bytes(base64.b64encode(b"synthetic-signature"))
    arguments = (
        tmp_path,
        "fixture.iso",
        "fixture",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        key,
        hashlib.sha256(key.read_bytes()).hexdigest(),
        "openssl",
    )
    return module, arguments, image


def test_completion_is_written_only_after_verified_bytes(media, monkeypatch):
    module, args, image = media
    monkeypatch.setattr(module, "verify", lambda path, *args: None)
    manifest, changed = module.prepare(*args)
    assert changed is True
    directory = args[0]
    assert (directory / "fixture.iso").read_bytes() == image
    assert manifest["iso_sha256"] == hashlib.sha256(image).hexdigest()
    assert json.loads((directory / "completion.json").read_text()) == manifest
    assert module.prepare(*args)[1] is False


def test_signature_failure_preserves_old_image_and_no_completion(media, monkeypatch):
    module, args, _ = media
    directory = args[0]
    old = directory / "fixture.iso"
    old.write_bytes(b"original-cached-bytes")

    def reject(*args):
        raise ValueError("signature failed")

    monkeypatch.setattr(module, "verify", reject)
    with pytest.raises(ValueError, match="signature failed"):
        module.prepare(*args)
    assert old.read_bytes() == b"original-cached-bytes"
    assert not (directory / "completion.json").exists()
    assert not list(directory.glob(".verify-*"))


def test_interrupted_completion_can_be_reconciled(media, monkeypatch):
    module, args, _ = media
    monkeypatch.setattr(module, "verify", lambda *args: None)
    original = module.os.replace

    def interrupt(source, target):
        if target.name == "completion.json":
            raise OSError("injected interrupted manifest write")
        original(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", interrupt)
        with pytest.raises(OSError):
            module.prepare(*args)
    assert (args[0] / "fixture.iso").exists()
    assert not (args[0] / "completion.json").exists()
    assert module.prepare(*args)[1] is True
    assert module.prepare(*args)[1] is False


@pytest.mark.parametrize("kind", ["archive", "public_key", "signature", "image_symlink", "manifest_symlink"])
def test_tampered_inputs_never_produce_completion(media, monkeypatch, kind):
    module, args, _ = media
    directory = args[0]
    monkeypatch.setattr(module, "verify", lambda *args: None)
    if kind == "archive":
        (directory / "fixture.iso.bz2").write_bytes(b"corrupt")
    elif kind == "public_key":
        args[4].write_text("different-key")
    elif kind == "signature":
        (directory / "fixture.iso.sig").write_bytes(b"not-base64!")
    else:
        name = "fixture.iso" if kind == "image_symlink" else "completion.json"
        (directory / name).symlink_to(args[4])
    with pytest.raises(ValueError):
        module.prepare(*args)
    assert args[4].read_text() in {"synthetic-public-key", "different-key"}
