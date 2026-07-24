from __future__ import annotations

import pytest

from narrascape.pipeline_approval import PipelineApproval
from narrascape.stages.base import StageResult


class DummyConsole:
    def print(self, *args, **kwargs):
        return None


def test_prompt_interactive_saves_pending_review_on_eof(tmp_path, monkeypatch):
    approval = PipelineApproval(tmp_path / "pipeline")
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError()))

    action = approval.prompt_interactive(
        "design",
        StageResult("design", True, message="done"),
        DummyConsole(),
    )

    assert action == "rejected"
    assert (tmp_path / "pipeline" / "approvals" / "design.pending").exists()


@pytest.mark.parametrize("stage_name", ["../design", "bad/stage", "C:\\outside"])
def test_approval_rejects_stage_paths(tmp_path, stage_name):
    approval = PipelineApproval(tmp_path / "pipeline")

    with pytest.raises(ValueError, match="stage name"):
        approval.approve(stage_name)
