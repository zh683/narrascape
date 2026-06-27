"""Research stage — gather background information before writing.

This stage can be run standalone or as part of the pipeline.
Outputs a research_report.md for human review and writer input.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from narrascape.config import NarrascapeConfig, Script, load_config
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.research import ResearchEngine

logger = logging.getLogger("narrascape.stages.research")


class ResearchStage(Stage):
    """AI research stage that gathers background on the video topic."""

    name = "research"
    depends_on = []
    outputs = ["research_report.md"]

    def __init__(self, llm_client: Any = None, topic: str = "", depth: str = "standard"):
        self.llm_client = llm_client
        self.topic = topic
        self.depth = depth

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        topic = self.topic or config.project.title

        logger.info(f"[research] Researching topic: {topic}")

        engine = ResearchEngine(llm_client=self.llm_client)
        result = engine.research(topic, depth=self.depth)

        # Write report
        report_path = config.project_dir / "research_report.md"
        report_path.write_text(result.to_markdown(), encoding="utf-8")
        logger.info(f"[research] Wrote report: {report_path}")

        # Print summary
        from rich.console import Console
        console = Console()
        console.print(f"[bold green]Research complete![/]")
        console.print(f"  Topic: {topic}")
        console.print(f"  Sections: {len(result.findings)}")
        console.print(f"  [cyan]→ {report_path}[/]")

        return StageResult(
            stage_name=self.name,
            success=True,
            outputs={"research_report": str(report_path)},
            metadata={"topic": topic, "sections": len(result.findings)},
        )
