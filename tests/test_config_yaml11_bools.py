"""YAML 1.1 bare off/on/yes/no normalization for enum string fields.

YAML 1.1 parses unquoted ``off``/``on``/``yes``/``no`` as booleans, so an
enum string field such as ``pipeline.video_generation: off`` arrives as
``False`` and previously failed pydantic validation with a raw enum error.
``load_config`` normalizes booleans back to enum strings for exactly the
declared fields before validation; real boolean fields are untouched.
"""

from pathlib import Path

import pytest

from narrascape.config import load_config

_MINIMAL_HEADER = """\
project:
  name: yaml11-test
  title: YAML11 Test
  script_file: scripts/script.yaml
"""


def _write_config(tmp_path: Path, body: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_MINIMAL_HEADER + body, encoding="utf-8")
    return config_path


def test_bare_off_video_generation_normalized(tmp_path):
    config_path = _write_config(tmp_path, "pipeline:\n  video_generation: off\n")

    cfg = load_config(config_path)

    assert cfg.pipeline.video_generation == "off"


def test_bare_off_storyboard_conditioning_normalized(tmp_path):
    config_path = _write_config(tmp_path, "video:\n  storyboard_conditioning: off\n")

    cfg = load_config(config_path)

    assert cfg.video.storyboard_conditioning == "off"


def test_bare_on_video_generation_raises_with_valid_values(tmp_path):
    config_path = _write_config(tmp_path, "pipeline:\n  video_generation: on\n")

    with pytest.raises(ValueError) as excinfo:
        load_config(config_path)

    message = str(excinfo.value)
    assert "'auto'" in message
    assert "'required'" in message
    assert "'off'" in message
    assert "pipeline.video_generation" in message


def test_bare_yes_storyboard_conditioning_raises_with_valid_values(tmp_path):
    config_path = _write_config(tmp_path, "video:\n  storyboard_conditioning: yes\n")

    with pytest.raises(ValueError) as excinfo:
        load_config(config_path)

    message = str(excinfo.value)
    assert "'off'" in message
    assert "'auto'" in message
    assert "video.storyboard_conditioning" in message


def test_real_boolean_fields_untouched(tmp_path):
    config_path = _write_config(
        tmp_path,
        "pipeline:\n  design_overwrite: false\n  strict_director: true\n",
    )

    cfg = load_config(config_path)

    assert cfg.pipeline.design_overwrite is False
    assert cfg.pipeline.strict_director is True


def test_quoted_off_string_untouched(tmp_path):
    config_path = _write_config(tmp_path, 'pipeline:\n  video_generation: "off"\n')

    cfg = load_config(config_path)

    assert cfg.pipeline.video_generation == "off"


def test_quoted_on_string_still_invalid_enum(tmp_path):
    config_path = _write_config(tmp_path, 'pipeline:\n  video_generation: "on"\n')

    with pytest.raises(ValueError):
        load_config(config_path)
