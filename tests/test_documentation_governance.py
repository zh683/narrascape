from __future__ import annotations

from pathlib import Path

from narrascape.catalog import STAGE_DOC_PATHS
from narrascape.pipeline import get_stage_map


def test_every_registered_stage_has_an_agent_stage_document():
    stages = set(get_stage_map())

    assert set(STAGE_DOC_PATHS) == stages
    for stage in sorted(stages):
        path = Path(STAGE_DOC_PATHS[stage])
        assert path.is_file(), stage
        text = path.read_text(encoding="utf-8")
        for heading in ("## Inputs", "## Outputs", "## Procedure", "## Do Not"):
            assert heading in text, f"{stage}: missing {heading}"


def test_roadmap_does_not_list_implemented_director_loops_as_future():
    roadmap = Path("docs/film-capability-roadmap.md").read_text(encoding="utf-8")
    future_section = roadmap.split("## Remaining Capability Layers", maxsplit=1)[1]

    assert "Multi-take generated-video integration" not in future_section
    assert "Automated rework execution" not in future_section
    assert "Continuity bible" not in future_section
