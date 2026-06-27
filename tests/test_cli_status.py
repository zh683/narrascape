from __future__ import annotations


def test_status_stage_names_include_film_timeline_default_path():
    from narrascape.cli import _status_stage_names

    names = _status_stage_names()

    assert "film_timeline" in names
    assert "film_assemble" in names
    assert "qa" in names
    assert "director_review" in names
