from __future__ import annotations

from narrascape.catalog import core_artifact_templates
from narrascape.dashboard_i18n import (
    ARTIFACT_LABELS_ZH,
    STAGE_LABELS_ZH,
    zh_edge_label,
    zh_source,
    zh_stage_label,
    zh_status,
)
from narrascape.dashboard_workbench import REWORK_QUEUE_SPECS
from narrascape.pipeline import get_stage_map


def test_chinese_stage_labels_cover_pipeline_registry():
    missing = sorted(set(get_stage_map()) - set(STAGE_LABELS_ZH))

    assert not missing
    assert zh_stage_label("generate_video") == "生成视频"
    assert zh_stage_label("assistant_handoff") == "Agent 交接包"


def test_chinese_artifact_labels_cover_workbench_artifacts():
    queue_ids = {str(spec["id"]) for spec in REWORK_QUEUE_SPECS}
    missing = sorted((set(core_artifact_templates()) | queue_ids) - set(ARTIFACT_LABELS_ZH))

    assert not missing
    assert ARTIFACT_LABELS_ZH["director_contract"] == "导演契约"
    assert ARTIFACT_LABELS_ZH["video_regen_queue"] == "视频重生成队列"


def test_chinese_status_source_and_edge_labels_are_native():
    assert zh_status("needs_rework") == "需要返工"
    assert zh_status(True) == "是"
    assert zh_source("handoff") == "交接包"
    assert zh_edge_label("feeds") == "回流"
