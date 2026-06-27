"""Pipeline approval system — stage-by-stage human review before proceeding.

This module implements an approval gate mechanism where each pipeline stage
must be manually approved before the next stage can run. This ensures human
oversight at every step of the AI-assisted video production pipeline.

Files created in pipeline/{name}/approvals/:
  {stage}.pending      — Stage completed, awaiting review
  {stage}.approved     — Stage approved, can proceed
  {stage}.rejected     — Stage rejected, needs revision
  {stage}.skipped      — Stage explicitly skipped

Usage in Pipeline.run():
    approval = PipelineApproval(pipeline_dir)
    if approval.is_approved(stage_name):
        # Already approved, skip review
        continue
    elif approval.is_rejected(stage_name):
        # Previously rejected, warn and stop
        logger.error(f"Stage {stage_name} was rejected. Fix and retry.")
        break
    elif interactive:
        # Pause and wait for user input
        result = approval.request_approval(stage_name, stage_result, ...)
        if not result:
            break  # User rejected
    else:
        # Non-interactive: require pre-existing approval
        if not auto_approve:
            logger.error(f"Stage {stage_name} not approved. Run: narrascape approve -p . -s {stage_name}")
            break
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from narrascape.stages.base import StageResult

logger = logging.getLogger("narrascape.approval")


class PipelineApproval:
    """Manages stage-by-stage approval gates for the pipeline.

    Each stage creates a "pending" review request. A human must review
    the generated assets and either approve, reject, or skip.
    """

    def __init__(self, pipeline_dir: Path):
        self.pipeline_dir = Path(pipeline_dir)
        self.approvals_dir = self.pipeline_dir / "approvals"
        self.approvals_dir.mkdir(parents=True, exist_ok=True)

    # ── Status checks ───────────────────────────────────────────────

    def is_pending(self, stage_name: str) -> bool:
        return (self.approvals_dir / f"{stage_name}.pending").exists()

    def is_approved(self, stage_name: str) -> bool:
        return (self.approvals_dir / f"{stage_name}.approved").exists()

    def is_rejected(self, stage_name: str) -> bool:
        return (self.approvals_dir / f"{stage_name}.rejected").exists()

    def is_skipped(self, stage_name: str) -> bool:
        return (self.approvals_dir / f"{stage_name}.skipped").exists()

    def get_status(self, stage_name: str) -> str:
        """Return one of: pending, approved, rejected, skipped, unknown."""
        if self.is_approved(stage_name):
            return "approved"
        if self.is_rejected(stage_name):
            return "rejected"
        if self.is_skipped(stage_name):
            return "skipped"
        if self.is_pending(stage_name):
            return "pending"
        return "unknown"

    # ── Request review ──────────────────────────────────────────────

    def request_review(
        self,
        stage_name: str,
        stage_result: StageResult,
        assets: list[dict] | None = None,
    ) -> None:
        """Create a review request file after stage completion.

        Writes a human-readable YAML-like file with:
        - Stage name and timestamp
        - Success/failure status
        - Output files and paths
        - Key metrics
        - Instructions for how to approve/reject
        """
        pending_file = self.approvals_dir / f"{stage_name}.pending"
        review_content = self._format_review_request(stage_name, stage_result, assets)

        with open(pending_file, "w", encoding="utf-8") as f:
            f.write(review_content)

        logger.info(f"[approval] Created review request: {pending_file}")

    def _format_review_request(
        self,
        stage_name: str,
        stage_result: StageResult,
        assets: list[dict] | None = None,
    ) -> str:
        """Format a human-readable review request."""
        lines = [
            "# ═══════════════════════════════════════════════════════════",
            f"# Stage Review Request: {stage_name}",
            f"# Generated: {datetime.now().isoformat()}",
            "# ═══════════════════════════════════════════════════════════",
            "",
            f"stage: {stage_name}",
            f"status: {'SUCCESS' if stage_result.success else 'FAILED'}",
            f"timestamp: {datetime.now().isoformat()}",
            "",
            "## Outputs",
        ]

        if stage_result.outputs:
            if isinstance(stage_result.outputs, dict):
                for key, path in stage_result.outputs.items():
                    lines.append(f"  {key}: {path}")
            else:
                for path in stage_result.outputs:
                    lines.append(f"  - {path}")
        else:
            lines.append("  (no outputs)")

        if stage_result.metadata:
            lines.append("")
            lines.append("## Metadata")
            for key, value in stage_result.metadata.items():
                lines.append(f"  {key}: {value}")

        if assets:
            lines.append("")
            lines.append("## Reviewable Assets")
            for asset in assets:
                lines.append(f"  - type: {asset.get('type', 'unknown')}")
                lines.append(f"    path: {asset.get('path', 'unknown')}")
                lines.append(f"    description: {asset.get('description', '')}")
                lines.append("")

        lines.append("## Instructions")
        lines.append("  To approve this stage and proceed:")
        lines.append(f"    narrascape approve -p . -s {stage_name}")
        lines.append("")
        lines.append("  To reject this stage (requires fix and retry):")
        lines.append(f"    narrascape reject -p . -s {stage_name}")
        lines.append("")
        lines.append("  To skip this stage (not recommended):")
        lines.append(f"    narrascape skip -p . -s {stage_name}")
        lines.append("")

        lines.append("## Notes")
        lines.append(f"  {stage_result.message or 'No additional notes'}")
        lines.append("")

        return "\n".join(lines)

    # ── Approve / Reject / Skip ─────────────────────────────────────

    def approve(self, stage_name: str, reviewer: str = "human", notes: str = "") -> None:
        """Mark a stage as approved."""
        self._clear_status_files(stage_name)
        approved_file = self.approvals_dir / f"{stage_name}.approved"
        with open(approved_file, "w", encoding="utf-8") as f:
            f.write(f"stage: {stage_name}\n")
            f.write("status: approved\n")
            f.write(f"reviewer: {reviewer}\n")
            f.write(f"timestamp: {datetime.now().isoformat()}\n")
            if notes:
                f.write(f"notes: {notes}\n")
        logger.info(f"[approval] Stage '{stage_name}' approved by {reviewer}")

    def reject(self, stage_name: str, reviewer: str = "human", notes: str = "") -> None:
        """Mark a stage as rejected."""
        self._clear_status_files(stage_name)
        rejected_file = self.approvals_dir / f"{stage_name}.rejected"
        with open(rejected_file, "w", encoding="utf-8") as f:
            f.write(f"stage: {stage_name}\n")
            f.write("status: rejected\n")
            f.write(f"reviewer: {reviewer}\n")
            f.write(f"timestamp: {datetime.now().isoformat()}\n")
            if notes:
                f.write(f"notes: {notes}\n")
        logger.info(f"[approval] Stage '{stage_name}' rejected by {reviewer}")

    def skip(self, stage_name: str, reviewer: str = "human", notes: str = "") -> None:
        """Mark a stage as explicitly skipped."""
        self._clear_status_files(stage_name)
        skipped_file = self.approvals_dir / f"{stage_name}.skipped"
        with open(skipped_file, "w", encoding="utf-8") as f:
            f.write(f"stage: {stage_name}\n")
            f.write("status: skipped\n")
            f.write(f"reviewer: {reviewer}\n")
            f.write(f"timestamp: {datetime.now().isoformat()}\n")
            if notes:
                f.write(f"notes: {notes}\n")
        logger.info(f"[approval] Stage '{stage_name}' skipped by {reviewer}")

    def _clear_status_files(self, stage_name: str) -> None:
        """Remove all status files for a stage."""
        for suffix in (".pending", ".approved", ".rejected", ".skipped"):
            f = self.approvals_dir / f"{stage_name}{suffix}"
            if f.exists():
                f.unlink()

    # ── Interactive prompt ─────────────────────────────────────────

    def prompt_interactive(
        self,
        stage_name: str,
        stage_result: StageResult,
        console: Any,
    ) -> str:
        """Interactive prompt for user approval.

        Returns one of: 'approved', 'rejected', 'retry', 'skipped'
        """
        from rich.panel import Panel
        from rich.table import Table

        # Display review panel
        console.print()
        console.print(
            Panel(
                f"[bold yellow]⏸️ Stage Complete: {stage_name}[/]\n"
                f"[dim]Status: {'SUCCESS' if stage_result.success else 'FAILED'}[/]\n"
                f"[dim]Message: {stage_result.message or 'N/A'}[/]",
                title="Review Required",
                border_style="yellow",
            )
        )

        # Display outputs
        if stage_result.outputs:
            table = Table(title="Generated Assets")
            table.add_column("Key", style="cyan")
            table.add_column("Path", style="green")
            for key, path in stage_result.outputs.items():
                table.add_row(key, str(path))
            console.print(table)

        if stage_result.metadata:
            table = Table(title="Metadata")
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="magenta")
            for key, value in stage_result.metadata.items():
                table.add_row(key, str(value))
            console.print(table)

        # Prompt for action
        while True:
            console.print()
            console.print("[bold]What would you like to do?[/]")
            console.print("  [1] [green]approve[/]  — Approve and proceed to next stage")
            console.print("  [2] [red]reject[/]   — Reject, stop pipeline, fix manually")
            console.print("  [3] [yellow]retry[/]   — Re-run this stage")
            console.print("  [4] [dim]skip[/]     — Skip review (not recommended)")
            console.print()

            choice = input("Choice [1/2/3/4]: ").strip().lower()

            if choice in ("1", "approve", "a", "y", "yes"):
                self.approve(stage_name)
                console.print(f"[bold green]✅ Stage '{stage_name}' approved[/]")
                return "approved"
            elif choice in ("2", "reject", "r", "n", "no"):
                self.reject(stage_name)
                console.print(f"[bold red]❌ Stage '{stage_name}' rejected[/]")
                return "rejected"
            elif choice in ("3", "retry", "t"):
                console.print(f"[bold yellow]🔄 Retrying stage '{stage_name}'[/]")
                return "retry"
            elif choice in ("4", "skip", "s"):
                self.skip(stage_name)
                console.print(f"[bold dim]⏭️ Stage '{stage_name}' skipped[/]")
                return "skipped"
            else:
                console.print("[red]Invalid choice. Please enter 1, 2, 3, or 4.[/]")

    # ── List all approvals ──────────────────────────────────────────

    def list_all(self) -> dict[str, str]:
        """Return a dict of all stage statuses."""
        statuses = {}
        for f in self.approvals_dir.iterdir():
            if f.suffix in (".pending", ".approved", ".rejected", ".skipped"):
                stage_name = f.stem
                statuses[stage_name] = f.suffix[1:]  # remove leading dot
        return statuses
