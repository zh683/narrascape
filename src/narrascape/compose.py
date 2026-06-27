from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CompositionPlan:
    project: str
    runtime: str
    inputs: list[Path]
    output: Path


class CompositionRuntime(Protocol):
    name: str
    available: bool

    def render(self, plan: CompositionPlan) -> bool:
        ...


@dataclass(frozen=True)
class RuntimeInfo:
    name: str
    available: bool
    reason: str = ""


class FFmpegCompositionRuntime:
    name = "ffmpeg"
    available = True

    def render(self, plan: CompositionPlan) -> bool:
        # Existing stages still perform rendering; this runtime is the selection
        # surface future compose stages can call into.
        return True


class UnavailableCompositionRuntime:
    def __init__(self, name: str, reason: str):
        self.name = name
        self.available = False
        self.reason = reason

    def render(self, plan: CompositionPlan) -> bool:
        raise RuntimeError(f"Composition runtime unavailable: {self.name}: {self.reason}")


class CompositionRuntimeRegistry:
    def __init__(self, runtimes: list[CompositionRuntime]):
        self._runtimes = {runtime.name: runtime for runtime in runtimes}

    @classmethod
    def default(cls) -> "CompositionRuntimeRegistry":
        return cls(
            [
                FFmpegCompositionRuntime(),
                UnavailableCompositionRuntime("remotion", "Remotion integration is not wired into Narrascape yet"),
            ]
        )

    def select(self, plan: CompositionPlan) -> CompositionRuntime:
        if plan.runtime and plan.runtime != "auto":
            runtime = self._runtimes.get(plan.runtime)
            if runtime is None:
                raise ValueError(f"Unknown composition runtime: {plan.runtime}")
            if not runtime.available:
                raise RuntimeError(f"Composition runtime unavailable: {runtime.name}")
            return runtime

        for runtime in self._runtimes.values():
            if runtime.available:
                return runtime
        raise RuntimeError("No available composition runtime")

    def support_envelope(self) -> dict[str, dict[str, object]]:
        envelope: dict[str, dict[str, object]] = {}
        for name, runtime in self._runtimes.items():
            envelope[name] = {
                "name": runtime.name,
                "available": runtime.available,
                "reason": getattr(runtime, "reason", ""),
            }
        return envelope
