from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from narrascape.config import (
    ImageProvider,
    MusicProvider,
    NarrascapeConfig,
    TTSProvider,
    VideoProvider,
)


class ProviderCapability(str, Enum):
    LLM = "llm"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    TTS = "tts"
    MUSIC = "music"
    RENDERING = "rendering"
    SOURCE_MEDIA = "source_media"


@dataclass(frozen=True)
class ProviderTool:
    name: str
    capability: ProviderCapability
    provider: str
    status: str = "available"
    quality: float = 0.5
    control: float = 0.5
    reliability: float = 0.7
    cost_efficiency: float = 0.7
    latency: float = 0.7
    continuity: float = 0.5
    task_fit: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability.value,
            "provider": self.provider,
            "status": self.status,
            "quality": self.quality,
            "control": self.control,
            "reliability": self.reliability,
            "cost_efficiency": self.cost_efficiency,
            "latency": self.latency,
            "continuity": self.continuity,
            "task_fit": dict(self.task_fit),
            "notes": self.notes,
            "requires": list(self.requires),
        }


class ProviderRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ProviderTool] = {}

    def register(self, tool: ProviderTool) -> None:
        if not tool.name:
            raise ValueError("provider tool name is required")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ProviderTool | None:
        return self._tools.get(name)

    def all(self) -> list[ProviderTool]:
        return list(self._tools.values())

    def by_capability(self, capability: str | ProviderCapability) -> list[ProviderTool]:
        cap = ProviderCapability(capability)
        return [tool for tool in self._tools.values() if tool.capability == cap]

    def available(self, capability: str | ProviderCapability | None = None) -> list[ProviderTool]:
        tools = self.all() if capability is None else self.by_capability(capability)
        return [tool for tool in tools if tool.status == "available"]

    def support_envelope(self) -> dict[str, dict[str, Any]]:
        return {name: tool.to_dict() for name, tool in sorted(self._tools.items())}

    def capability_summary(self) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        for tool in self._tools.values():
            bucket = summary.setdefault(tool.capability.value, {"total": 0, "available": 0})
            bucket["total"] += 1
            if tool.status == "available":
                bucket["available"] += 1
        return dict(sorted(summary.items()))


def _status(condition: bool) -> str:
    return "available" if condition else "unavailable"


def build_default_registry(config: NarrascapeConfig) -> ProviderRegistry:
    registry = ProviderRegistry()

    llm_available = config.llm.mode in {"auto", "ai_assistant", "bridge", "api"}
    registry.register(
        ProviderTool(
            name=f"{config.llm.mode}_llm",
            capability=ProviderCapability.LLM,
            provider=config.llm.mode,
            status=_status(llm_available),
            quality=0.8 if llm_available else 0.1,
            task_fit={"creative": 0.9, "offline": 0.1},
            notes="Configured project LLM mode",
        )
    )
    registry.register(
        ProviderTool(
            name="none_llm",
            capability=ProviderCapability.LLM,
            provider="none",
            status=_status(config.llm.mode == "none"),
            quality=0.1,
            cost_efficiency=1.0,
            task_fit={"offline": 1.0},
            notes="Deterministic local fallback, not creative LLM",
        )
    )

    registry.register(
        ProviderTool(
            name="local_image",
            capability=ProviderCapability.IMAGE_GENERATION,
            provider="local",
            status="available",
            quality=0.15,
            cost_efficiency=1.0,
            task_fit={"offline": 1.0},
            notes="Deterministic placeholder images",
        )
    )
    registry.register(
        ProviderTool(
            name="seedream_image",
            capability=ProviderCapability.IMAGE_GENERATION,
            provider="seedream",
            status=_status(config.images.provider == ImageProvider.SEEDREAM),
            quality=0.85,
            control=0.75,
            continuity=0.8,
            cost_efficiency=0.5,
            task_fit={"creative": 0.9, "reference": 0.9},
            requires=["ARK_API_KEY"],
        )
    )
    registry.register(
        ProviderTool(
            name="agnes_image",
            capability=ProviderCapability.IMAGE_GENERATION,
            provider="agnes",
            status=_status(config.images.provider == ImageProvider.AGNES),
            quality=0.82,
            control=0.75,
            reliability=0.75,
            cost_efficiency=0.65,
            latency=0.65,
            continuity=0.7,
            task_fit={"creative": 0.88, "reference": 0.8},
            notes="Agnes Image 2.1 Flash text-to-image and image-to-image",
            requires=["AGNES_API_KEY"],
        )
    )

    registry.register(
        ProviderTool(
            name="local_tts",
            capability=ProviderCapability.TTS,
            provider="local",
            status="available",
            quality=0.1,
            cost_efficiency=1.0,
            task_fit={"offline": 1.0},
        )
    )
    registry.register(
        ProviderTool(
            name="minimax_tts",
            capability=ProviderCapability.TTS,
            provider="minimax",
            status=_status(config.tts.provider == TTSProvider.MINIMAX),
            quality=0.8,
            requires=["MINIMAX_API_KEY"],
        )
    )

    registry.register(
        ProviderTool(
            name="local_music",
            capability=ProviderCapability.MUSIC,
            provider="local",
            status="available",
            quality=0.1,
            cost_efficiency=1.0,
            task_fit={"offline": 1.0},
        )
    )
    registry.register(
        ProviderTool(
            name="minimax_music",
            capability=ProviderCapability.MUSIC,
            provider="minimax",
            status=_status(config.audio.music.provider == MusicProvider.MINIMAX),
            quality=0.65,
            requires=["MINIMAX_API_KEY"],
        )
    )

    registry.register(
        ProviderTool(
            name="seedance_video",
            capability=ProviderCapability.VIDEO_GENERATION,
            provider="seedance",
            status=_status(config.video.provider == VideoProvider.SEEDANCE),
            quality=0.8,
            control=0.7,
            continuity=0.85,
            cost_efficiency=0.4,
            requires=["ARK_API_KEY"],
        )
    )
    registry.register(
        ProviderTool(
            name="agnes_video",
            capability=ProviderCapability.VIDEO_GENERATION,
            provider="agnes",
            status=_status(config.video.provider == VideoProvider.AGNES),
            quality=0.82,
            control=0.75,
            reliability=0.75,
            continuity=0.78,
            cost_efficiency=0.65,
            latency=0.55,
            task_fit={"creative": 0.9, "reference": 0.82},
            notes="Agnes Video V2.0 async text/image/multi-image generation",
            requires=["AGNES_API_KEY"],
        )
    )
    registry.register(
        ProviderTool(
            name="ffmpeg_render",
            capability=ProviderCapability.RENDERING,
            provider="ffmpeg",
            status="available",
            quality=0.75,
            reliability=0.9,
            cost_efficiency=1.0,
        )
    )
    registry.register(
        ProviderTool(
            name="local_source_media",
            capability=ProviderCapability.SOURCE_MEDIA,
            provider="local",
            status="available",
            reliability=0.9,
            cost_efficiency=1.0,
        )
    )

    return registry
