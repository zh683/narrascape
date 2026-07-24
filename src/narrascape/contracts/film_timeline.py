"""Typed model for `film_timeline.yaml` (schema_version: film_timeline.v1).

Field set traced from `stages/film_timeline.py` (`run`, `_semantic_fields`,
`_music_track`, `_subtitle_track`), verified against production artifacts.
Clip-level optional keys vary by visual source: footage clips add
`source_in`/`source_out`; the ending card omits all design/semantic fields.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from narrascape.contracts.common import ContractModel, ProjectRef


class VisualClip(ContractModel):
    id: str = ""
    segment_id: int | None = None  # None on the ending card
    source: str = ""
    asset_ref: str | None = None
    path: str | None = ""
    start: float = 0.0
    duration: float = 0.0
    role: str = ""
    transition: str = ""
    # Design passthrough (absent on the ending card).
    shot_type: str | None = None
    movement: str | None = None
    emotion: str | None = None
    intensity: Any = None  # numeric or label, producer-defined
    # Footage-only trim window.
    source_in: float | None = None
    source_out: float | None = None
    # Semantic fields from _semantic_fields (None when nothing locked).
    character_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    wardrobe: str | None = None
    lighting_scheme: str | None = None
    screen_axis: str | None = None
    storyboard_frame_ids: list[str] = Field(default_factory=list)
    character_positions: list[str] = Field(default_factory=list)
    composition: str | None = None


class NarrationClip(ContractModel):
    id: str = ""
    segment_id: int | None = None
    asset_ref: str = ""
    path: str = ""
    start: float = 0.0
    duration: float = 0.0
    text: str = ""


class MusicClip(ContractModel):
    id: str = ""
    asset_ref: str = ""
    path: str = ""
    covers: list[int] = Field(default_factory=list)
    label: str = ""


class SubtitleTrack(ContractModel):
    id: str = ""
    path: str = ""
    format: str = ""


class TimelineStrategy(ContractModel):
    visual_priority: list[str] = Field(default_factory=list)
    fallback: str = ""


class TimelineCoverage(ContractModel):
    generated_video_segments: list[int] = Field(default_factory=list)
    source_media_segments: list[int] = Field(default_factory=list)
    generated_image_segments: list[int] = Field(default_factory=list)
    missing_visual_segments: list[int] = Field(default_factory=list)


class TimelineTracks(ContractModel):
    visual: list[VisualClip] = Field(default_factory=list)
    narration: list[NarrationClip] = Field(default_factory=list)
    music: list[MusicClip] = Field(default_factory=list)
    subtitles: list[SubtitleTrack] = Field(default_factory=list)


class FilmTimeline(ContractModel):
    """Top-level film_timeline.yaml model (write-side gate + typed reads)."""

    schema_version: Literal["film_timeline.v1"]
    project: ProjectRef = Field(default_factory=ProjectRef)
    duration: float = 0.0
    strategy: TimelineStrategy = Field(default_factory=TimelineStrategy)
    coverage: TimelineCoverage
    tracks: TimelineTracks
