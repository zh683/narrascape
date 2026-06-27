from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from narrascape.config import MovementType, ShotType, SupersampleMode, VisualConfig
from narrascape.utils.ffmpeg import validate_video


@dataclass(frozen=True)
class MotionParams:
    """Parameters for a single motion segment."""
    image_path: Path
    output_path: Path
    duration: float
    fps: int
    width: int
    height: int
    movement: MovementType
    shot_type: ShotType
    fade_in: float
    fade_out: float
    zoom_start: float = 1.0
    zoom_end: float = 1.0
    supersample: SupersampleMode = SupersampleMode.AUTO


@dataclass
class MotionResult:
    """Result of a motion segment generation."""
    output_path: Path
    success: bool
    engine_used: str
    duration: float
    error: str | None = None

    def validate(self) -> bool:
        """Verify the output file is a valid video."""
        if not self.success:
            return False
        return validate_video(self.output_path)


class MotionEngine(ABC):
    """Abstract base class for Ken Burns motion rendering engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier name."""
        ...

    @abstractmethod
    def can_handle(self, params: MotionParams) -> bool:
        """Check if this engine can handle the given parameters."""
        ...

    @abstractmethod
    def generate(self, params: MotionParams) -> MotionResult:
        """Generate a single motion segment. Must be idempotent."""
        ...

    def _build_fade_vf(self, params: MotionParams) -> str:
        """Build fade-in/fade-out filter string."""
        parts = [f"fade=t=in:st=0:d={params.fade_in}"]
        if params.duration > 3.0:
            fade_out_start = params.duration - params.fade_out
            parts.append(f"fade=t=out:st={fade_out_start:.1f}:d={params.fade_out:.1f}")
        return ",".join(parts)
