import pytest


@pytest.mark.parametrize("url", ["http://source.example.test/file", "file:///private/file", "https:///missing-host"])
def test_fedora_download_rejects_unsafe_scheme_before_creating_files(load_module, tmp_path, url):
    module = load_module("scripts/prepare-fedora-cloud.py")
    with pytest.raises(ValueError, match="require an HTTPS URL"):
        module.download(url, tmp_path / "image")
    assert list(tmp_path.iterdir()) == []


def test_fedora_redirect_failure_leaves_no_partial_artifact(load_module, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    module = load_module("scripts/prepare-fedora-cloud.py")
    response = MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = "http://source.example.test/file"
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="redirected outside HTTPS"):
        module.download("https://source.example.test/file", tmp_path / "image")
    response.read.assert_not_called()
    assert list(tmp_path.iterdir()) == []
