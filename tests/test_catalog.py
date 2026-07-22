#!/usr/bin/env python3
"""Regression tests for catalog artifact templates."""

from __future__ import annotations

import yaml

from narrascape.catalog import core_artifact_templates
from narrascape.config import NarrascapeConfig, ProjectConfig
from narrascape.stages.assistant_handoff import AssistantHandoffStage


def _make_config(tmp_path, name: str = "catalog-test") -> NarrascapeConfig:
    return NarrascapeConfig(
        project=ProjectConfig(
            name=name,
            title="Catalog Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )


class TestDesignReportTemplate:
    def test_template_matches_design_stage_write_path(self, tmp_path):
        """catalog's design_report template must resolve to the real output.

        DesignStage writes to config.pipeline_dir / "design_report.yaml"
        (i.e. pipeline/<name>/design_report.yaml), not the project root.
        """
        config = _make_config(tmp_path)
        template = core_artifact_templates()["design_report"]

        resolved = config.project_dir / template.format(name=config.project.name)

        assert resolved == config.pipeline_dir / "design_report.yaml"

    def test_handoff_summary_does_not_report_existing_design_report_as_missing(self, tmp_path):
        config = _make_config(tmp_path)
        config.pipeline_dir.mkdir(parents=True)
        (config.pipeline_dir / "design_report.yaml").write_text(
            yaml.safe_dump({"status": "draft", "segments": []}),
            encoding="utf-8",
        )

        summary = AssistantHandoffStage()._artifact_summary(config)
        entry = next(item for item in summary if item["id"] == "design_report")

        assert entry["exists"] is True
        assert entry["status"] != "missing"

    def test_handoff_summary_reports_missing_design_report_as_missing(self, tmp_path):
        config = _make_config(tmp_path)

        summary = AssistantHandoffStage()._artifact_summary(config)
        entry = next(item for item in summary if item["id"] == "design_report")

        assert entry["exists"] is False
        assert entry["status"] == "missing"
