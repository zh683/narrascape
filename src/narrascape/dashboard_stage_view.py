from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OutputFileGroups:
    images: list[Path]
    video: list[Path]
    audio: list[Path]
    text: list[Path]
    other: list[Path]


def stage_title(stage_name: str, meta: dict[str, Any]) -> str:
    return str(meta.get("title") or stage_name.replace("_", " ").title())


def stage_label(stage_name: str, meta: dict[str, Any]) -> str:
    return str(meta.get("label") or stage_name.replace("_", " ").title())


def status_tag(status: str) -> str:
    if status == "completed":
        return "done"
    if status in {"failed", "running", "skipped"}:
        return "warn"
    return "pending"


def group_output_files(files: list[Path]) -> OutputFileGroups:
    images = [f for f in files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    video = [f for f in files if f.suffix.lower() in (".mp4", ".mov")]
    audio = [f for f in files if f.suffix.lower() in (".mp3", ".wav", ".aac")]
    text = [
        f for f in files if f.suffix.lower() in (".md", ".yaml", ".yml", ".json", ".txt", ".srt")
    ]
    other = [f for f in files if f not in images + video + audio + text]
    return OutputFileGroups(images=images, video=video, audio=audio, text=text, other=other)
