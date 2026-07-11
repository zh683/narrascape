from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from narrascape.artifacts import load_artifact_file
from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, Script
from narrascape.utils.safe_io import load_json_mapping


@dataclass
class StageContext:
    """Shared context passed to all stages during pipeline execution."""

    config: NarrascapeConfig
    script: Script
    cache: BuildCache
    state: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def pipeline_dir(self) -> Path:
        return self.config.pipeline_dir

    @property
    def output_dir(self) -> Path:
        return self.config.output_dir


@dataclass
class StageResult:
    """Result of a stage execution."""

    stage_name: str
    success: bool
    outputs: Sequence[str | Path] | dict[str, Any] = field(default_factory=list)
    message: str = ""
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.success


class Stage(ABC):
    """Abstract base class for a pipeline stage."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stage identifier."""
        ...

    @property
    @abstractmethod
    def depends_on(self) -> list[str]:
        """List of stage names this stage depends on."""
        ...

    @property
    def outputs(self) -> Sequence[str | Path]:
        """Expected output files for this stage."""
        return []

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        """Check if prerequisites are met. Returns (can_run, reason)."""
        return True, ""

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return load_artifact_file(path)

    def _load_json(self, path: Path) -> dict[str, Any]:
        return load_json_mapping(path)

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0] if paths else Path()

    @abstractmethod
    def run(self, context: StageContext) -> StageResult:
        """Execute the stage."""
        ...
