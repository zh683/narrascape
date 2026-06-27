from __future__ import annotations

import json

import pytest


def test_atomic_json_write_and_load_mapping(tmp_path):
    from narrascape.utils.safe_io import atomic_write_json, load_json_mapping

    path = tmp_path / "state.json"
    atomic_write_json(path, {"done": ["a"]})

    assert json.loads(path.read_text(encoding="utf-8")) == {"done": ["a"]}
    assert load_json_mapping(path)["done"] == ["a"]
    assert not (tmp_path / "state.json.lock").exists()


def test_json_loader_treats_empty_file_as_default_mapping(tmp_path):
    from narrascape.utils.safe_io import load_json_mapping

    path = tmp_path / "state.json"
    path.write_text("", encoding="utf-8")

    assert load_json_mapping(path, default={"done": []}) == {"done": []}


def test_yaml_loader_rejects_non_mapping(tmp_path):
    from narrascape.utils.safe_io import ArtifactLoadError, load_yaml_mapping

    path = tmp_path / "bad.yaml"
    path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(ArtifactLoadError, match="expected mapping"):
        load_yaml_mapping(path)


def test_download_to_path_removes_partial_file_on_failure(tmp_path, monkeypatch):
    from narrascape.utils.safe_io import download_to_path

    target = tmp_path / "video.mp4"

    def fail_urlopen(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(OSError):
        download_to_path("https://example.invalid/video.mp4", target)

    assert not target.exists()
    assert not list(tmp_path.glob("*.download"))
    assert not list(tmp_path.glob(".*.download"))


def test_download_to_path_rejects_unexpected_content_type_for_media(tmp_path, monkeypatch):
    from io import BytesIO

    import pytest

    from narrascape.utils.safe_io import download_to_path

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

        def getcode(self):
            return 200

        def headers(self):
            return {}

        def getheader(self, name, default=None):
            return "text/html" if name.lower() == "content-type" else default

    def fake_urlopen(*args, **kwargs):
        return FakeResponse(b"<html>not a video</html>")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    target = tmp_path / "video.mp4"
    with pytest.raises(RuntimeError, match="Unexpected content type"):
        download_to_path(
            "https://example.test/video.mp4", target, expected_content_prefixes=("video/",)
        )

    assert not target.exists()
