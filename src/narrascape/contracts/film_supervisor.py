"""Typed model for `film_supervisor.yaml` (schema_version: film_supervisor.v1).

Field set traced from `stages/film_supervisor.py` (`run`), consumed by
`pipeline.Pipeline._supervisor_next_stages` and `stages/assistant_handoff.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from narrascape.contracts.common import ContractModel, ProjectRef


class SupervisorDecision(ContractModel):
    rework_action_count: int = 0
    creative_recommendation_count: int = 0
    visual_finding_count: int = 0
    blocking_error_count: int = 0


class SupervisorSources(ContractModel):
    rework_plan: str = ""
    creative_review: str = ""
    visual_semantic_report: str = ""
    render_report: str = ""


class FilmSupervisorReport(ContractModel):
    """Top-level film_supervisor.yaml model (write-side gate + typed reads)."""

    schema_version: Literal["film_supervisor.v1"]
    project: ProjectRef = Field(default_factory=ProjectRef)
    status: str
    decision: SupervisorDecision
    next_stages: list[str] = Field(default_factory=list)
    sources: SupervisorSources = Field(default_factory=SupervisorSources)
