"""Write stage — generates narration script from research or topic.

Outputs script.yaml and marks it for human approval.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from narrascape.humanizer import HumanizerEngine
from narrascape.research import ResearchEngine, load_research_report
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_text, atomic_write_yaml
from narrascape.writer import ScriptWriter

logger = logging.getLogger("narrascape.stages.write")


class WriteStage(Stage):
    """AI writer stage that generates narration scripts.

    Can operate in two modes:
    1. Topic-driven: research + write in one go
    2. Research-driven: write from existing research report

    After writing, always runs humanizer pass and marks for approval.
    """

    name = "write"
    depends_on = []
    outputs = ["scripts/script.yaml", "scripts/script_raw.yaml", "scripts/script_approved.yaml"]

    def __init__(
        self,
        llm_client: Any = None,
        topic: str = "",
        segment_count: int = 12,
        style: str = "documentary",
        research_report: str = "",
        auto_humanize: bool = True,
    ):
        self.llm_client = llm_client
        self.topic = topic
        self.segment_count = segment_count
        self.style = style
        self.research_report = research_report
        self.auto_humanize = auto_humanize

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        project_dir = config.project_dir

        # Determine topic
        topic = self.topic or config.project.title or config.project.name

        # Ensure scripts directory exists
        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Load or generate research
        if self.research_report:
            report_path = Path(self.research_report)
            if not report_path.exists():
                return StageResult(
                    self.name,
                    False,
                    message=f"Research report not found: {self.research_report}",
                )
            research = load_research_report(self.research_report)
        else:
            research_engine = ResearchEngine(llm_client=self.llm_client)
            research = research_engine.research(topic, depth="standard")
            # Save research report for reference
            report_path = project_dir / "research_report.md"
            atomic_write_text(report_path, research.to_markdown())

        # Step 2: Write raw script
        writer = ScriptWriter(llm_client=self.llm_client, style=self.style)
        script = writer.write_from_research(research, self.segment_count)
        script = writer.write_ending(script, tone=config.ending.tone)

        # Step 3: Save raw script (before humanization)
        raw_path = scripts_dir / "script_raw.yaml"
        raw_data = {"segments": [seg.model_dump() for seg in script.segments]}
        atomic_write_yaml(raw_path, raw_data)
        logger.info(f"[write] Raw script saved: {raw_path}")

        # Step 4: Humanize (LLM-first, rule-based fallback)
        if self.auto_humanize:
            humanizer = HumanizerEngine(llm_client=self.llm_client, aggressive=False)
            for seg in script.segments:
                seg.text = humanizer.humanize(seg.text)

        # Step 5: Save humanized script (pending approval)
        script_path = scripts_dir / "script.yaml"
        if script_path.exists():
            backup_path = scripts_dir / f"script.yaml.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            atomic_write_text(backup_path, script_path.read_text(encoding="utf-8"))
        script_data = {"segments": [seg.model_dump() for seg in script.segments]}
        atomic_write_yaml(script_path, script_data)
        logger.info(f"[write] Humanized script saved: {script_path}")

        # Step 6: Create approval marker
        approval_path = project_dir / ".approval_pending"
        atomic_write_text(
            approval_path,
            f"Script generated on: {__import__('datetime').datetime.now().isoformat()}\n"
            f"Status: PENDING_APPROVAL\n"
            f"\n"
            f"Please review and edit: {script_path}\n"
            f"\n"
            f"After approval, run:\n"
            f"  narrascape design -p {project_dir}\n"
            f"  narrascape build -p {project_dir}\n",
        )

        # Step 7: Print summary
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print()
        console.print(
            Panel(
                f"[bold green]✍️ Script Generated[/]\n"
                f"Topic: {topic}\n"
                f"Segments: {script.segment_count}\n\n"
                f"[yellow]⏸️ PAUSED FOR APPROVAL[/]\n"
                f"Please review and edit:\n"
                f"  [cyan]{script_path}[/]\n\n"
                f"Files created:\n"
                f"  [dim]→ {raw_path} (AI raw)[/]\n"
                f"  [dim]→ {script_path} (humanized, EDIT THIS)[/]\n"
                f"  [dim]→ {project_dir / 'research_report.md'} (research)[/]\n\n"
                f"After you're satisfied, run:\n"
                f"  [bold]narrascape design -p {project_dir}[/]",
                title="Approval Required",
                border_style="yellow",
            )
        )

        return StageResult(
            stage_name=self.name,
            success=True,
            outputs={
                "script_raw": str(raw_path),
                "script": str(script_path),
                "approval_marker": str(approval_path),
            },
            metadata={
                "segment_count": script.segment_count,
                "status": "PENDING_APPROVAL",
                "topic": topic,
            },
        )
