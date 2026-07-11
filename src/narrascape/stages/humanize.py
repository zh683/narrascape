"""Humanize stage — removes AI writing patterns from script.

Can be run standalone on an existing script or as part of the write pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from narrascape.artifacts import write_artifact
from narrascape.humanizer import HumanizerEngine
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_text

logger = logging.getLogger("narrascape.stages.humanize")


class HumanizeStage(Stage):
    """Post-process a script to remove AI writing patterns."""

    name = "humanize"
    depends_on = []
    outputs = ["scripts/script.yaml"]

    def __init__(self, llm_client: Any = None, aggressive: bool = False, score_only: bool = False):
        self.llm_client = llm_client
        self.aggressive = aggressive
        self.score_only = score_only

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        project_dir = config.project_dir
        script_path = project_dir / config.project.script_file

        if not script_path.exists():
            return StageResult(
                self.name,
                False,
                message=f"Script not found: {script_path}",
            )

        # Load script
        text = script_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)

        if "segments" not in data:
            return StageResult(
                self.name,
                False,
                message="Invalid script format: no 'segments' key",
            )

        humanizer = HumanizerEngine(llm_client=self.llm_client, aggressive=self.aggressive)

        # Score and optionally humanize
        total_ai_score = 0.0
        changed_segments = 0

        for seg in data["segments"]:
            if "text" not in seg:
                continue

            original = seg["text"]
            score = humanizer.score(original)
            total_ai_score += score["ai_likeness"]

            if self.score_only:
                logger.info(
                    f"[humanize] Seg {seg.get('id', '?')}: {score['verdict']} (score={score['ai_likeness']})"
                )
            else:
                humanized = humanizer.humanize(original)
                if humanized != original:
                    seg["text"] = humanized
                    changed_segments += 1
                    logger.info(
                        f"[humanize] Seg {seg.get('id', '?')}: humanized ({score['verdict']})"
                    )

        avg_score = total_ai_score / len(data["segments"]) if data["segments"] else 0

        # Save result if not score-only
        if not self.score_only:
            backup_path = script_path.with_suffix(".yaml.backup")
            atomic_write_text(backup_path, text)
            data["schema_version"] = "script.v1"
            write_artifact("script", script_path, data)
            logger.info(f"[humanize] Saved backup: {backup_path}")

        from rich.console import Console

        console = Console()

        if self.score_only:
            console.print(f"[bold]AI Score (avg):[/] {avg_score:.1f}/10")
            console.print("[dim]Lower is better. <2 = human-like, >5 = AI-like[/]")
        else:
            console.print(f"[bold green]Humanized {changed_segments} segments[/]")
            console.print(f"Average AI score: {avg_score:.1f}/10 → improved")
            console.print(f"[dim]Backup saved: {backup_path}[/]")

        return StageResult(
            self.name,
            True,
            outputs={"script": str(script_path)},
            metadata={
                "avg_ai_score": round(avg_score, 1),
                "changed_segments": changed_segments,
                "score_only": self.score_only,
            },
        )
