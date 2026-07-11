from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.catalog import (
    core_artifact_templates,
    repo_relative_doc_label,
    stage_doc_path,
    stage_doc_paths,
    stage_intent,
)
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import (
    atomic_write_text,
    atomic_write_yaml,
    load_json_mapping,
)


class AssistantHandoffStage(Stage):
    """Write a takeover packet for Codex-style AI assistants."""

    name = "assistant_handoff"
    depends_on = ["film_supervisor"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        path = context.config.pipeline_dir / "film_supervisor.yaml"
        if not path.exists():
            return False, f"film_supervisor.yaml not found: {path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output_yaml = config.pipeline_dir / "assistant_handoff.yaml"
        output_md = config.pipeline_dir / "assistant_handoff.md"
        output_yaml.parent.mkdir(parents=True, exist_ok=True)

        supervisor = self._load_yaml(config.pipeline_dir / "film_supervisor.yaml")
        render_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")
        production_readiness = self._load_yaml(config.pipeline_dir / "production_readiness.yaml")
        state = load_json_mapping(config.pipeline_dir / "state.json", default={})

        next_stages = [str(item) for item in supervisor.get("next_stages", []) or []]
        handoff = {
            "schema_version": "assistant_handoff.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
                "project_dir": config.project_dir.as_posix(),
                "pipeline_dir": config.pipeline_dir.as_posix(),
            },
            "status": self._handoff_status(supervisor, render_report, production_readiness),
            "director_decision": {
                "supervisor_status": str(supervisor.get("status", "missing")),
                "next_stages": next_stages,
                "decision": supervisor.get("decision", {}) or {},
            },
            "assistant_contract": self._assistant_contract(config),
            "required_reading": self._required_reading(next_stages),
            "artifacts": self._artifact_summary(config),
            "quality_gates": self._quality_gates(config, render_report, production_readiness),
            "next_actions": self._next_actions(config, next_stages),
            "blocking_items": self._blocking_items(render_report, production_readiness),
            "state_summary": self._state_summary(state),
            "commands": self._commands(config, next_stages),
        }
        validate_artifact("assistant_handoff", handoff)
        atomic_write_yaml(output_yaml, handoff)
        atomic_write_text(output_md, self._render_markdown(handoff))

        return StageResult(
            self.name,
            True,
            outputs=[output_yaml, output_md],
            message=f"assistant handoff: {handoff['status']}",
            metadata={"status": handoff["status"], "next_stages": next_stages},
        )

    def _handoff_status(
        self,
        supervisor: dict[str, Any],
        render_report: dict[str, Any],
        production_readiness: dict[str, Any],
    ) -> str:
        if production_readiness.get("status") == "blocked":
            return "blocked_before_generation"
        if render_report.get("errors"):
            return "blocked_by_qa"
        if supervisor.get("status") == "needs_rework":
            return "needs_rework"
        if supervisor.get("status") == "approved":
            return "approved"
        return "needs_attention"

    def _assistant_contract(self, config: Any) -> list[dict[str, str]]:
        rules = [
            (
                "read_before_acting",
                "Read this handoff, docs/ai-director.md, and the stage docs for every next stage before changing outputs.",
            ),
            (
                "director_contract_is_source_of_truth",
                "Treat director_contract.yaml and reference_plates.yaml as the executable visual contract.",
            ),
            (
                "do_not_bypass_pipeline",
                "Use narrascape stages and queues instead of manually editing final renders or generated media.",
            ),
            (
                "protect_provider_calls",
                "Announce and verify any stage that may call paid media providers before running it.",
            ),
            (
                "verify_after_changes",
                "Run the most relevant tests or QA stages and update the handoff after material changes.",
            ),
        ]
        if config.pipeline.strict_director:
            rules.append(
                (
                    "strict_director_boundary",
                    "Do not accept not_configured or fallback_after_error director artifacts in production.",
                )
            )
        return [{"id": rule_id, "rule": rule} for rule_id, rule in rules]

    def _required_reading(self, next_stages: list[str]) -> list[dict[str, str]]:
        docs: list[str] = ["README.md", "docs/ai-director.md", "docs/assistant-handoff.md"]
        docs.extend(stage_doc_paths(next_stages))
        result = []
        seen = set()
        for doc in docs:
            if doc in seen:
                continue
            seen.add(doc)
            result.append({"path": doc, "reason": self._reading_reason(doc)})
        return result

    def _reading_reason(self, path: str) -> str:
        if path == "README.md":
            return "project positioning, current capabilities, and production profile"
        if path == "docs/ai-director.md":
            return "AI Director boundaries and LLM/fallback rules"
        if path == "docs/assistant-handoff.md":
            return "Codex takeover protocol"
        return f"stage-specific contract for {repo_relative_doc_label(path)}"

    def _artifact_summary(self, config: Any) -> list[dict[str, Any]]:
        result = []
        for artifact, template in core_artifact_templates().items():
            rel = template.format(name=config.project.name)
            path = config.project_dir / rel
            if not path.exists() and rel.startswith("pipeline/"):
                path = config.pipeline_dir / Path(rel).name
            result.append(
                {
                    "id": artifact,
                    "path": path.as_posix(),
                    "exists": path.exists(),
                    "status": self._artifact_status(path),
                }
            )
        return result

    def _artifact_status(self, path: Path) -> str:
        if not path.exists():
            return "missing"
        data = self._load_yaml(path)
        status = data.get("status")
        if status:
            return str(status)
        if data.get("errors"):
            return "has_errors"
        return "present"

    def _quality_gates(
        self,
        config: Any,
        render_report: dict[str, Any],
        production_readiness: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks = render_report.get("checks", {}) if isinstance(render_report, dict) else {}
        return [
            {
                "id": "llm_mode",
                "status": config.llm.mode,
                "required": "ai_assistant, bridge, api, or auto for production video",
            },
            {
                "id": "video_generation",
                "status": config.pipeline.video_generation,
                "required": "required for production generated-video films",
            },
            {
                "id": "strict_director",
                "status": bool(config.pipeline.strict_director),
                "required": True,
            },
            {
                "id": "production_readiness",
                "status": str(production_readiness.get("status", "missing")),
                "required": "ready before generated-video production",
            },
            {
                "id": "qa_errors",
                "status": len(render_report.get("errors", []) or []),
                "required": 0,
            },
            {
                "id": "missing_generated_video_segments",
                "status": checks.get("missing_generated_video_segments", []),
                "required": [],
            },
        ]

    def _next_actions(self, config: Any, next_stages: list[str]) -> list[dict[str, Any]]:
        if not next_stages:
            return [
                {
                    "stage": "status",
                    "intent": "No supervisor rerun requested. Inspect outputs or start a new creative iteration.",
                    "command": f"narrascape status -p {config.project_dir.as_posix()}",
                    "read_before": ["docs/ai-director.md"],
                }
            ]
        return [
            {
                "stage": stage,
                "intent": stage_intent(stage),
                "command": (
                    f"narrascape build -p {config.project_dir.as_posix()} "
                    f"--stage {stage} --approve"
                ),
                "read_before": [stage_doc_path(stage)] if stage_doc_path(stage) else [],
            }
            for stage in next_stages
        ]

    def _blocking_items(
        self,
        render_report: dict[str, Any],
        production_readiness: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result = []
        for error in render_report.get("errors", []) or []:
            result.append({"source": "render_report", "severity": "error", "message": str(error)})
        for finding in production_readiness.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            result.append(
                {
                    "source": "production_readiness",
                    "severity": str(finding.get("severity", "medium")),
                    "message": str(finding.get("message") or finding.get("risk_type") or finding),
                }
            )
        return result

    def _state_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        stages = state.get("stages", {}) if isinstance(state.get("stages"), dict) else {}
        counts = {"completed": 0, "pending": 0, "failed": 0, "skipped": 0, "other": 0}
        for status in stages.values():
            key = str(status)
            counts[key if key in counts else "other"] += 1
        return {"stage_counts": counts, "known_stage_count": len(stages)}

    def _commands(self, config: Any, next_stages: list[str]) -> dict[str, str]:
        project = config.project_dir.as_posix()
        commands = {
            "status": f"narrascape status -p {project}",
            "full_build": f"narrascape build -p {project} --approve",
            "production_build": f"narrascape build -p {project} --production --approve",
            "refresh_handoff": f"narrascape build -p {project} --stage assistant_handoff --approve",
        }
        if next_stages:
            commands["next_stage"] = (
                f"narrascape build -p {project} --stage {next_stages[0]} --approve"
            )
        return commands

    def _render_markdown(self, handoff: dict[str, Any]) -> str:
        lines = [
            "# Assistant Handoff",
            "",
            f"Project: {handoff['project']['title']} (`{handoff['project']['name']}`)",
            f"Status: `{handoff['status']}`",
            f"Supervisor: `{handoff['director_decision']['supervisor_status']}`",
            "",
            "## Required Reading",
        ]
        for item in handoff["required_reading"]:
            lines.append(f"- `{item['path']}` - {item['reason']}")
        lines.extend(["", "## Next Actions"])
        for item in handoff["next_actions"]:
            lines.append(f"- `{item['stage']}`: {item['intent']}")
            lines.append(f"  Command: `{item['command']}`")
        lines.extend(["", "## Blocking Items"])
        if handoff["blocking_items"]:
            for item in handoff["blocking_items"]:
                lines.append(f"- `{item['source']}` {item['severity']}: {item['message']}")
        else:
            lines.append("- none")
        lines.extend(["", "## Assistant Contract"])
        for item in handoff["assistant_contract"]:
            lines.append(f"- `{item['id']}`: {item['rule']}")
        lines.extend(["", "## Commands"])
        for key, value in handoff["commands"].items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
        return "\n".join(lines)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)
