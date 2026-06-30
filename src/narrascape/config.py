#!/usr/bin/env python3
"""
Pydantic configuration models for narrascape.
Replaces raw YAML dicts with validated, typed, auto-completed configs.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_VISUAL_STYLE = (
    "Oil painting style, painterly cinematic frames, visible brush texture, "
    "layered pigments, canvas grain, rich chiaroscuro lighting, cohesive color palette, "
    "period-drama mood; not photorealistic photography, not anime, not cartoon, "
    "no readable text, no watermark."
)

# ───────────────────────────────────────────
# Enums
# ───────────────────────────────────────────


class SupersampleMode(str, Enum):
    """Ken Burns zoom rendering quality mode."""

    NORMAL = "normal"  # 2x pre-scale + zoompan (fast, painterly images)
    EXTREME = "extreme"  # PIL float-pixel affine (slow, 100% smooth)
    AUTO = "auto"  # Auto-detect hard edges, switch per image


class ShotType(str, Enum):
    """Cinematic shot type — drives image size and default motion."""

    WIDE_ENV = "wide_env"
    WIDE_ANGLE = "wide_angle"
    AERIAL = "aerial"
    ESTABLISHING = "establishing"
    MEDIUM = "medium"
    TWO_SHOT = "two_shot"
    OVER_SHOULDER = "over_shoulder"
    CLOSE_UP = "close_up"
    EXTREME_CLOSE_UP = "extreme_close_up"
    DETAIL = "detail"
    INSERT = "insert"
    SILHOUETTE = "silhouette"
    GROUP_SHOT = "group_shot"
    BLACK = "black"


class MovementType(str, Enum):
    """Ken Burns motion types."""

    STILL = "still"
    ZOOM_IN = "zoom_in"
    ZOOM_SLOW = "zoom_slow"
    ZOOM_IN_SLOW = "zoom_in_slow"
    ZOOM_OUT = "zoom_out"
    ZOOM_OUT_SLOW = "zoom_out_slow"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    DRIFT = "drift"


class TTSProvider(str, Enum):
    """Supported TTS providers."""

    MINIMAX = "minimax"
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    PIPER = "piper"
    LOCAL = "local"


class ImageProvider(str, Enum):
    """Supported image generation providers."""

    SEEDREAM = "seedream"
    AGNES = "agnes"
    FLUX = "flux"
    OPENAI = "openai"
    LOCAL = "local"


class VideoProvider(str, Enum):
    """Supported video generation providers."""

    SEEDANCE = "seedance"
    AGNES = "agnes"


class MusicProvider(str, Enum):
    """Supported music generation providers."""

    MINIMAX = "minimax"
    SUNO = "suno"
    ELEVENLABS = "elevenlabs"
    LOCAL = "local"


class SubtitleEngine(str, Enum):
    """Subtitle rendering engine."""

    SRT = "srt"
    VTT = "vtt"


class LLMConfig(BaseModel):
    """LLM configuration for the project."""

    mode: str = Field("auto", description="LLM mode: auto, ai_assistant, api, bridge, none")
    timeout: int = Field(300, description="Bridge mode timeout in seconds")
    provider: str = Field(
        "", description="API provider: openai, anthropic, deepseek, volcengine, ai_assistant"
    )
    model: str = Field("", description="Model name for API mode")
    api_key: str = Field("", description="API key (or use env var)")
    base_url: str = Field("", description="Custom API base URL")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(2000, ge=100, le=16000)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        allowed = {"auto", "ai_assistant", "api", "bridge", "none"}
        if v.lower() not in allowed:
            raise ValueError(f"llm.mode must be one of {allowed}, got '{v}'")
        return v.lower()


# ───────────────────────────────────────────
# Project & Pipeline
# ───────────────────────────────────────────


class ProjectConfig(BaseModel):
    """Project identity and metadata."""

    name: str = Field(
        ..., description="Project slug, used for pipeline subdirs and output filenames"
    )
    title: str = Field(..., description="Human-readable video title")
    subtitle: str | None = Field(None, description="Video subtitle / tagline")
    author: str | None = Field(None, description="Content author / narrator name")
    year: int | None = Field(None, description="Production year")
    series: str | None = Field(None, description="Series name if part of a series")
    episode: int | None = Field(None, description="Episode number in series")
    script_file: str = Field(..., description="Path to script YAML file")
    segment_count: int | None = Field(
        12, description="Default number of segments for script generation"
    )
    style: str | None = Field("documentary", description="Default video style")


class PipelineConfig(BaseModel):
    """Pipeline identity and production-loop behavior."""

    name: str = Field("animated-explainer", description="Pipeline type identifier")
    category: str | None = Field(None, description="Pipeline category")
    version: str = Field("2.0", description="Pipeline version string")
    design_overwrite: bool = Field(
        True,
        description=(
            "Whether the design stage rewrites image_prompts.yaml and image_map.yaml. "
            "Set false for curated projects that should preserve authored prompt files."
        ),
    )
    video_generation: Literal["auto", "required", "off"] = Field(
        "auto",
        description=(
            "Generated-video policy: auto tries video when credentials are available, "
            "required fails instead of falling back, off omits generated-video stages."
        ),
    )
    strict_director: bool = Field(
        False,
        description=(
            "Fail key AI Director stages when their artifacts show not_configured "
            "or fallback_after_error LLM status."
        ),
    )
    production_quality_gates: bool = Field(
        False,
        description=(
            "Enable stricter pre-video readiness checks for production AI-film builds: "
            "script density, pre-production coverage, storyboard bindings, and prompt contracts."
        ),
    )
    auto_rework: bool = Field(
        True,
        description="Automatically execute film_supervisor rework decisions during default builds.",
    )
    max_rework_cycles: int = Field(
        1,
        ge=0,
        le=10,
        description="Maximum automatic rework/rerun cycles after the first supervisor pass.",
    )


# ───────────────────────────────────────────
# TTS
# ───────────────────────────────────────────


class PronunciationEntry(BaseModel):
    """A single pronunciation override."""

    original: str = Field(..., description="Original text to replace")
    replacement: str = Field(..., description="Phonetic replacement")


class TTSConfig(BaseModel):
    """Text-to-speech configuration."""

    provider: TTSProvider = Field(TTSProvider.MINIMAX, description="TTS provider")
    engine: str | None = Field(None, description="Engine override")
    model: str = Field("speech-2.8-hd", description="TTS model name")
    voice_id: str = Field("male-qn-jingying", description="Voice identifier")
    speed: float = Field(0.9, ge=0.5, le=2.0, description="Speech speed multiplier")
    pitch: int = Field(0, ge=-10, le=10, description="Pitch shift in semitones")
    vol: float = Field(1.0, ge=0.0, le=2.0, description="Volume multiplier")
    sample_rate: int = Field(32000, description="Output sample rate in Hz")
    segments: int | None = Field(None, description="Number of segments (auto-detected)")
    continuous_sound: bool = Field(True, description="Clause-level smoothing (MiniMax 2.8+)")
    text_normalization: bool = Field(True, description="Normalize numbers and punctuation")
    language_boost: str = Field("Chinese", description="Language hint for TTS engine")
    add_pauses: bool = Field(False, description="Auto-insert pause markers at sentence boundaries")
    pronunciation_dict: list[str] = Field(
        default_factory=list, description="Pronunciation overrides"
    )


# ───────────────────────────────────────────
# Images
# ───────────────────────────────────────────


class ImageConfig(BaseModel):
    """Image generation configuration."""

    provider: ImageProvider = Field(ImageProvider.SEEDREAM)
    engine: str | None = Field(None)
    model: str = Field("doubao-seedream-5-0-260128")
    style: str = Field(DEFAULT_VISUAL_STYLE, description="Global style prompt prefix")
    aspect_ratio: str = Field("16:9")
    width: int = Field(2560, ge=640, le=8192)
    height: int = Field(1440, ge=480, le=8192)
    count: int | None = Field(None, description="Number of images (auto-detected)")


class VideoConfig(BaseModel):
    """Generated-video provider configuration."""

    provider: VideoProvider = Field(VideoProvider.SEEDANCE)
    model: str = Field("jimeng-video-seedance-2.0")
    resolution: str = Field("720p")
    ratio: str = Field("16:9")
    duration: int = Field(5, ge=1, le=18)
    frame_rate: int = Field(24, ge=1, le=60)
    takes: int = Field(
        1,
        ge=1,
        le=8,
        description="Generated-video candidates per shot. Values above 1 create multi-take clips for take_select.",
    )


# ───────────────────────────────────────────
# Visual / Ken Burns
# ───────────────────────────────────────────


class VisualConfig(BaseModel):
    """Visual rendering configuration."""

    type: str = Field("ken_burns", description="Motion type identifier")
    zoom_rate: float = Field(0.001, ge=0.0, le=0.1, description="Base zoom rate per frame")
    zoom_cap: float = Field(1.20, ge=1.0, le=2.0, description="Maximum zoom factor")
    vignette: str | None = Field(None, description="Vignette strength expression")
    fade_in_duration: float = Field(
        3.0, ge=0.0, le=10.0, description="Segment fade-in duration in seconds"
    )
    supersample: SupersampleMode = Field(SupersampleMode.AUTO, description="Zoom rendering quality")
    segment_gap: float = Field(1.5, ge=0.0, le=10.0, description="Default gap between segments")
    gap_map: dict[int, float] = Field(default_factory=dict, description="Per-segment gap overrides")

    @field_validator("gap_map")
    @classmethod
    def validate_gap_durations(cls, v: dict[int, float]) -> dict[int, float]:
        for seg_id, dur in v.items():
            if dur < 0:
                raise ValueError(f"gap_map segment {seg_id}: duration must be >= 0")
            if dur > 10:
                raise ValueError(f"gap_map segment {seg_id}: duration > 10s is unusual")
        return v


# ───────────────────────────────────────────
# Subtitles
# ───────────────────────────────────────────


class SubtitleConfig(BaseModel):
    """Subtitle rendering configuration."""

    engine: SubtitleEngine = Field(SubtitleEngine.SRT)
    font: str = Field("Microsoft YaHei")
    font_size: int = Field(24, ge=8, le=96)
    max_chars_per_line: int = Field(18, ge=4, le=80)
    strip_punctuation: bool = Field(True)
    alignment: int = Field(
        2, ge=1, le=9, description="ASS alignment: 1=bottom-left, 2=bottom-center, 3=bottom-right"
    )
    primary_color: str = Field("&H00FFFFFF")
    outline_color: str = Field("&H00000000")
    outline: int = Field(2, ge=0, le=8)
    shadow: int = Field(1, ge=0, le=8)
    margin_v: int = Field(60, ge=0, le=500)


# ───────────────────────────────────────────
# Audio
# ───────────────────────────────────────────


class NarrationAudioConfig(BaseModel):
    """Narration track audio settings."""

    provider: str | None = Field(None)
    format: str = Field("mp3")
    sample_rate: int = Field(32000)


class MusicAudioConfig(BaseModel):
    """Background music audio settings."""

    provider: MusicProvider = Field(MusicProvider.MINIMAX)
    model: str = Field("music-2.6-free")
    sample_rate: int = Field(44100)
    bitrate: int = Field(256000)
    volume: float = Field(0.25, ge=0.0, le=1.0)
    music_boost_db: float = Field(2.0)
    sidechain_threshold: float = Field(0.05, ge=0.0, le=1.0)
    sidechain_ratio: int = Field(3, ge=1, le=20)
    sidechain_attack: int = Field(20, ge=1, le=1000)
    sidechain_release: int = Field(600, ge=1, le=5000)
    narration_lufs: int = Field(-16, ge=-70, le=0)
    target_lufs: int = Field(-14, ge=-70, le=0)
    fade_out_seconds: int = Field(5, ge=0, le=30)


class AudioConfig(BaseModel):
    """Combined audio configuration."""

    narration: NarrationAudioConfig = Field(default_factory=NarrationAudioConfig)
    music: MusicAudioConfig = Field(default_factory=MusicAudioConfig)


# ───────────────────────────────────────────
# BGM Zones
# ───────────────────────────────────────────


class BGMZone(BaseModel):
    """A single background music zone."""

    id: str = Field(..., description="Zone identifier, used for filename")
    covers: list[int] = Field(..., description="Segment IDs this zone covers [start, end]")
    label: str = Field(..., description="Human-readable zone label")
    prompt: str = Field(
        ..., description="Music generation prompt (English, with instruments/BPM/key)"
    )
    min_duration: int = Field(120, ge=10, description="Minimum generated duration in seconds")


class BGMMap(BaseModel):
    """Background music zone mapping."""

    zone_crossfade: float = Field(
        1.5, ge=0.0, le=10.0, description="Crossfade duration between zones"
    )
    zones: list[BGMZone] = Field(default_factory=list)


# ───────────────────────────────────────────
# Encoding
# ───────────────────────────────────────────


class EncodeConfig(BaseModel):
    """Video encoding parameters."""

    width: int = Field(1920, ge=360, le=7680)
    height: int = Field(1080, ge=240, le=4320)
    fps: int = Field(25, ge=1, le=120)
    crf: int = Field(18, ge=0, le=51)
    preset: str = Field("medium")
    codec: str = Field("libx264")
    audio_codec: str = Field("aac")
    audio_bitrate: str = Field("192k")


# ───────────────────────────────────────────
# Ending Card
# ───────────────────────────────────────────


class EndingLine(BaseModel):
    """A single line of text on the ending card."""

    text: str
    size: int = Field(36, ge=8, le=120)


class EndingConfig(BaseModel):
    """Ending card configuration."""

    enabled: bool = Field(True)
    duration: float = Field(15.0, ge=1.0, le=60.0)
    tone: str = Field("hopeful", description="Narrative tone for generated closing narration")
    template: str | None = Field(None)
    lines: list[EndingLine] = Field(default_factory=list)
    quote: str | None = Field(None)
    quote_size: int = Field(28, ge=8, le=120)


# ───────────────────────────────────────────
# Budget
# ───────────────────────────────────────────


class BudgetConfig(BaseModel):
    """Cost estimation and budget controls."""

    total_usd: float = Field(10.0, ge=0.0)
    tts_estimated: float | None = Field(None)
    images_estimated: float | None = Field(None)
    music_estimated: float | None = Field(None)
    video_estimated: float | None = Field(None)
    total_estimated: float | None = Field(None)
    mode: Literal["observe", "warn", "cap"] = Field("warn")
    per_action_threshold: float = Field(0.5, ge=0.0)


# ───────────────────────────────────────────
# Root Config
# ───────────────────────────────────────────


class NarrascapeConfig(BaseModel):
    """Root configuration model — validates entire config.yaml."""

    project: ProjectConfig
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    images: ImageConfig = Field(default_factory=ImageConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    bgm_map: BGMMap = Field(default_factory=BGMMap)
    encode: EncodeConfig = Field(default_factory=EncodeConfig)
    ending: EndingConfig = Field(default_factory=EndingConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    # Runtime-derived paths (not in YAML)
    project_dir: Path = Field(default=Path("."), exclude=True)

    @model_validator(mode="after")
    def validate_production_policies(self) -> NarrascapeConfig:
        if self.pipeline.video_generation == "required" and self.llm.mode == "none":
            raise ValueError(
                "pipeline.video_generation=required requires llm.mode to be "
                "auto, ai_assistant, bridge, or api. llm.mode=none is only for "
                "offline/local verification."
            )
        return self

    @model_validator(mode="after")
    def derive_project_dir(self) -> NarrascapeConfig:
        if self.project_dir == Path("."):
            self.project_dir = Path.cwd()
        return self

    @property
    def assets_dir(self) -> Path:
        return self.project_dir / "assets"

    @property
    def images_dir(self) -> Path:
        return self.assets_dir / "images"

    @property
    def tts_dir(self) -> Path:
        return self.assets_dir / "tts"

    @property
    def music_dir(self) -> Path:
        return self.assets_dir / "music"

    @property
    def pipeline_dir(self) -> Path:
        return self.project_dir / "pipeline" / self.project.name

    @property
    def output_dir(self) -> Path:
        return self.project_dir / "output"

    @property
    def script_path(self) -> Path:
        return self.project_dir / self.project.script_file

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.encode.width, self.encode.height)

    @property
    def aspect_ratio(self) -> float:
        return self.encode.width / self.encode.height

    model_config = ConfigDict(extra="forbid")


# ───────────────────────────────────────────
# Script Models (script.yaml)
# ───────────────────────────────────────────


class PauseMarker(BaseModel):
    """Explicit pause marker for a segment."""

    after: str = Field(..., description="Text after which to insert pause")
    seconds: float = Field(..., ge=0.01, le=99.99, description="Pause duration in seconds")


class ScriptSegment(BaseModel):
    """A single segment in the script."""

    id: int = Field(..., ge=1, description="Segment sequence number")
    text: str = Field(..., description="Narration text for this segment")
    shot_type: ShotType | None = Field(None, description="Override shot type for this segment")
    pause_markers: list[PauseMarker] = Field(default_factory=list)
    pronunciation: list[str] = Field(default_factory=list)


class Script(BaseModel):
    """Complete script model."""

    segments: list[ScriptSegment] = Field(..., min_length=1)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def segment_ids(self) -> list[int]:
        return [s.id for s in self.segments]

    def get_segment(self, seg_id: int) -> ScriptSegment | None:
        for seg in self.segments:
            if seg.id == seg_id:
                return seg
        return None

    def get_text(self, seg_id: int) -> str:
        seg = self.get_segment(seg_id)
        return seg.text if seg else ""


# ───────────────────────────────────────────
# Image Prompt Models (image_prompts.yaml)
# ───────────────────────────────────────────


class ImagePrompt(BaseModel):
    """A single image generation prompt."""

    id: str = Field(..., description="Image identifier (e.g., img_01)")
    shot_type: ShotType = Field(ShotType.MEDIUM, description="Cinematic shot type")
    movement: MovementType | None = Field(None, description="Override Ken Burns movement")
    size: str | None = Field(None, description="Override image dimensions (e.g., 4704x2016)")
    description: str = Field(..., description="Full image generation prompt")
    strategy: str | None = Field(None, description="Generation strategy hint")
    reference_image_url: str | None = Field(
        None,
        description="URL or path to a single reference image for Seedream (legacy, use reference_images for multi)",
    )
    reference_images: list[str] = Field(
        default_factory=list,
        description="Multiple reference image URLs/paths for Seedream multi-reference (max 14)",
    )
    seedream_model: str | None = Field(None, description="Override Seedream model for this prompt")
    seedream_sample_strength: float | None = Field(
        None, ge=0.0, le=1.0, description="Reference influence strength"
    )
    negative_prompt: str | None = Field(
        None, description="Negative prompt to prevent unwanted elements"
    )

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.split("x")
        if len(parts) != 2:
            raise ValueError(f"size must be WxH, got: {v}")
        try:
            w, h = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"size dimensions must be integers, got: {v}")
        if w < 100 or h < 100:
            raise ValueError(f"size too small: {v}")
        return v

    @field_validator("reference_images")
    @classmethod
    def validate_reference_images(cls, v: list[str]) -> list[str]:
        if len(v) > 14:
            raise ValueError(f"Seedream supports max 14 reference images, got {len(v)}")
        return v


class ImagePrompts(BaseModel):
    """Complete image prompts collection."""

    prompts: list[ImagePrompt] = Field(..., min_length=1)

    def get_prompt(self, prompt_id: str) -> ImagePrompt | None:
        for p in self.prompts:
            if p.id == prompt_id:
                return p
        return None

    @property
    def prompt_ids(self) -> list[str]:
        return [p.id for p in self.prompts]


# ───────────────────────────────────────────
# Image Map Models (image_map.yaml)
# ───────────────────────────────────────────


class ImageMapEntry(BaseModel):
    """Maps a segment to its image(s) and timing."""

    id: int = Field(..., ge=1, description="Segment ID")
    images: list[str] = Field(
        default_factory=list, description="List of image IDs for this segment"
    )
    timing: list[float] | None = Field(
        None, description="Time allocation ratios for multi-image segments"
    )

    @field_validator("timing")
    @classmethod
    def validate_timing(cls, v: list[float] | None, info: Any) -> list[float] | None:
        if v is None:
            return v
        images = info.data.get("images", [])
        if len(v) != len(images):
            raise ValueError(f"timing length ({len(v)}) must match images length ({len(images)})")
        total = sum(v)
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"timing ratios must sum to 1.0, got {total}")
        return v


class ImageMap(BaseModel):
    """Complete segment-to-image mapping."""

    segments: list[ImageMapEntry] = Field(...)

    def get_entry(self, seg_id: int) -> ImageMapEntry | None:
        for entry in self.segments:
            if entry.id == seg_id:
                return entry
        return None

    def get_images(self, seg_id: int) -> list[str]:
        entry = self.get_entry(seg_id)
        return entry.images if entry else []

    def get_timing(self, seg_id: int) -> list[float] | None:
        entry = self.get_entry(seg_id)
        return entry.timing if entry else None


# ───────────────────────────────────────────
# Loader helpers
# ───────────────────────────────────────────


def load_config(path: Path) -> NarrascapeConfig:
    """Load and validate config.yaml from a project directory or file path."""
    from narrascape.utils.safe_io import load_yaml_mapping

    # If path is a directory, look for config.yaml inside it
    if path.is_dir():
        path = path / "config.yaml"
    data = load_yaml_mapping(path)
    cfg = NarrascapeConfig(**data)
    cfg.project_dir = path.parent
    return cfg


def load_script(path: Path) -> Script:
    """Load and validate script.yaml."""
    from narrascape.utils.safe_io import load_yaml_mapping

    data = load_yaml_mapping(path)
    return Script(**data)


def load_image_prompts(path: Path) -> ImagePrompts:
    """Load and validate image_prompts.yaml."""
    from narrascape.utils.safe_io import load_yaml_mapping

    data = load_yaml_mapping(path)
    return ImagePrompts(**data)


def load_image_map(path: Path) -> ImageMap:
    """Load and validate image_map.yaml."""
    from narrascape.utils.safe_io import load_yaml_mapping

    data = load_yaml_mapping(path)
    return ImageMap(**data)
