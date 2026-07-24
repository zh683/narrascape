from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import write_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_media_info
from narrascape.utils.safe_io import atomic_write_yaml


class SourceMediaStage(Stage):
    """Discover local source media and write a canonical asset manifest."""

    name = "source_media"
    depends_on: list[str] = []
    media_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".png", ".jpg", ".jpeg"}

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        media_dir = context.config.project_dir / "source_media"
        if not media_dir.exists():
            return False, f"source_media directory not found: {media_dir}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        project_dir = context.config.project_dir
        media_dir = project_dir / "source_media"
        manifest_path = project_dir / "asset_manifest.yaml"
        timeline_path = project_dir / "footage_timeline.yaml"
        media_dir.mkdir(parents=True, exist_ok=True)

        assets: list[dict[str, Any]] = []
        for path in sorted(p for p in media_dir.rglob("*") if p.is_file()):
            if path.suffix.lower() not in self.media_extensions:
                continue
            rel = path.relative_to(project_dir).as_posix()
            media_type = self._type_for(path)
            metadata = {"bytes": path.stat().st_size}
            metadata.update(self._probe_media(path, media_type))
            assets.append(
                {
                    "id": f"asset_{len(assets) + 1:03d}",
                    "path": rel,
                    "type": media_type,
                    "provider": "local",
                    "source": "local_library",
                    "license": "user_provided",
                    "metadata": metadata,
                }
            )

        data = {"schema_version": "asset_manifest.v1", "assets": assets}
        write_artifact("asset_manifest", manifest_path, data)
        timeline = self._build_footage_timeline(assets, context)
        atomic_write_yaml(timeline_path, timeline)

        return StageResult(
            self.name,
            True,
            outputs=[manifest_path, timeline_path],
            message=f"{len(assets)} local source asset(s)",
            metadata={"asset_count": len(assets), "timeline": timeline_path.as_posix()},
        )

    def _type_for(self, path: Path) -> str:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return "image"
        return "video"

    def _probe_media(self, path: Path, media_type: str) -> dict[str, Any]:
        if media_type != "video":
            return {}
        try:
            info = get_media_info(path)
        except Exception as exc:
            return {"probe_status": "unavailable", "probe_error": str(exc)}

        metadata: dict[str, Any] = {"probe_status": "ok"}
        try:
            metadata["duration_seconds"] = float(info.get("format", {}).get("duration", 0.0))
        except (TypeError, ValueError):
            pass
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                if stream.get("width") and stream.get("height"):
                    metadata["resolution"] = [int(stream["width"]), int(stream["height"])]
                if stream.get("avg_frame_rate"):
                    metadata["avg_frame_rate"] = stream["avg_frame_rate"]
                break
        return metadata

    def _build_footage_timeline(
        self,
        assets: list[dict[str, Any]],
        context: StageContext,
    ) -> dict[str, Any]:
        edits: list[dict[str, Any]] = []
        cursor = 0.0
        script_segments = list(context.script.segments)
        default_duration = 6.0

        for index, asset in enumerate(assets):
            metadata = asset.get("metadata", {})
            raw_duration = metadata.get("duration_seconds") or default_duration
            try:
                duration = max(1.0, min(float(raw_duration), 12.0))
            except (TypeError, ValueError):
                duration = default_duration
            segment = script_segments[index % len(script_segments)] if script_segments else None
            edit = {
                "id": f"edit_{index + 1:03d}",
                "asset_id": asset["id"],
                "source_path": asset["path"],
                "source_type": asset["type"],
                "role": "documentary_footage" if asset["type"] == "video" else "documentary_still",
                "target_segment_id": segment.id if segment else None,
                "timeline_start": round(cursor, 3),
                "duration": round(duration, 3),
                "source_in": 0.0,
                "source_out": round(duration, 3),
                "transition": "cut",
                "notes": "Local source media selected before generated fallback.",
            }
            edits.append(edit)
            cursor += duration

        return {
            "strategy": "source_media_first",
            "project": context.config.project.name,
            "total_duration": round(cursor, 3),
            "edits": edits,
        }
