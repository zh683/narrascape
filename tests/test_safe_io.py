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


def test_atomic_yaml_write_preserves_unicode(tmp_path):
    from narrascape.utils.safe_io import atomic_write_yaml

    path = tmp_path / "config.yaml"

    atomic_write_yaml(path, {"project": {"title": "罪与罚"}})

    text = path.read_text(encoding="utf-8")
    assert "罪与罚" in text
    assert "\\u7f6a" not in text


def test_atomic_json_write_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    import os

    from narrascape.utils.safe_io import atomic_write_json, load_json_mapping

    path = tmp_path / "state.json"
    attempts = 0
    real_replace = os.replace

    def flaky_replace(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    atomic_write_json(path, {"done": ["b"]})

    assert attempts == 2
    assert load_json_mapping(path)["done"] == ["b"]


def test_atomic_copy_file_overwrites_atomically_and_cleans_temp(tmp_path):
    from narrascape.utils.safe_io import atomic_copy_file

    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"
    source.write_bytes(b"new-video")
    target.write_bytes(b"old-video")

    atomic_copy_file(source, target)

    assert target.read_bytes() == b"new-video"
    assert not list(tmp_path.glob("*.copy"))
    assert not list(tmp_path.glob(".*.copy"))
    assert not (tmp_path / "target.mp4.lock").exists()


def test_atomic_copy_file_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    import os

    from narrascape.utils.safe_io import atomic_copy_file

    source = tmp_path / "source.mp3"
    target = tmp_path / "target.mp3"
    source.write_bytes(b"audio")
    attempts = 0
    real_replace = os.replace

    def flaky_replace(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    atomic_copy_file(source, target)

    assert attempts == 2
    assert target.read_bytes() == b"audio"


def test_atomic_promote_file_retries_and_removes_source(tmp_path, monkeypatch):
    import os

    from narrascape.utils.safe_io import atomic_promote_file

    temp_path = tmp_path / ".storyboard.png.tmp"
    target = tmp_path / "storyboard.png"
    temp_path.write_bytes(b"png")
    attempts = 0
    real_replace = os.replace

    def flaky_replace(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    atomic_promote_file(temp_path, target)

    assert attempts == 2
    assert target.read_bytes() == b"png"
    assert not temp_path.exists()


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


def test_download_to_path_rejects_html_when_content_type_is_missing(tmp_path, monkeypatch):
    from io import BytesIO

    from narrascape.utils.safe_io import download_to_path

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

        def getcode(self):
            return 200

        def getheader(self, name, default=None):
            return default

    def fake_urlopen(*args, **kwargs):
        return FakeResponse(b"<!doctype html><html>not media</html>")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    target = tmp_path / "video.mp4"
    with pytest.raises(RuntimeError, match="HTML/XML"):
        download_to_path(
            "https://example.test/video.mp4", target, expected_content_prefixes=("video/",)
        )

    assert not target.exists()


def test_download_to_path_rejects_riff_file_when_image_webp_expected(tmp_path, monkeypatch):
    from io import BytesIO

    from narrascape.utils.safe_io import download_to_path

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

        def getcode(self):
            return 200

        def getheader(self, name, default=None):
            return default

    def fake_urlopen(*args, **kwargs):
        return FakeResponse(b"RIFF\x10\x00\x00\x00WAVEfmt ")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    target = tmp_path / "image.webp"
    with pytest.raises(RuntimeError, match="does not look like an image"):
        download_to_path(
            "https://example.test/image.webp", target, expected_content_prefixes=("image/",)
        )

    assert not target.exists()
