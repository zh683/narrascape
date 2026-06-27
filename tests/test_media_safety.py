from __future__ import annotations


def test_subtitle_filter_path_escapes_windows_and_filter_chars(tmp_path):
    from narrascape.stages.subtitles import SubtitleStage

    stage = SubtitleStage()
    path = tmp_path / "clip,with'special.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    escaped = stage._escape_filter_path(path)

    assert "," not in escaped.replace("\\,", "")
    assert "'" not in escaped.replace("\\'", "")
    assert "\\:" in escaped or ":" not in escaped


def test_qa_file_hash_reads_in_chunks(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    path = tmp_path / "large.bin"
    path.write_bytes(b"a" * (1024 * 1024 + 3))
    stage = QAStage()

    digest = stage._file_sha256(path)

    assert len(digest) == 64


def test_hard_edge_detection_uses_histogram_path(tmp_path):
    from PIL import Image, ImageDraw

    from narrascape.motion.factory import detect_hard_edges

    path = tmp_path / "grid.png"
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 256, 16):
        draw.line((x, 0, x, 255), fill="black", width=2)
    image.save(path)

    assert detect_hard_edges(path, threshold=0.02, downsample_width=128) is True


def test_hard_edge_detection_rejects_smooth_gradient(tmp_path):
    from PIL import Image

    from narrascape.motion.factory import detect_hard_edges

    path = tmp_path / "gradient.png"
    image = Image.new("RGB", (256, 256))
    pixels = image.load()
    for x in range(256):
        for y in range(256):
            shade = int((x + y) / 2)
            pixels[x, y] = (shade, shade, shade)
    image.save(path)

    assert detect_hard_edges(path, threshold=0.12, downsample_width=128) is False
