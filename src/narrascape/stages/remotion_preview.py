from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import load_yaml_mapping


class RemotionPreviewStage(Stage):
    """Generate a Remotion handoff project from film_timeline.yaml."""

    name = "remotion_preview"
    depends_on = ["film_timeline"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline_path = context.config.project_dir / "film_timeline.yaml"
        if not timeline_path.exists():
            return False, f"film_timeline.yaml not found: {timeline_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        timeline_path = config.project_dir / "film_timeline.yaml"
        timeline = load_yaml_mapping(timeline_path)
        visual_clips = timeline.get("tracks", {}).get("visual", [])
        if not isinstance(visual_clips, list) or not visual_clips:
            return StageResult(self.name, False, message="No visual clips in film_timeline.yaml")

        preview_dir = config.pipeline_dir / "remotion_preview"
        src_dir = preview_dir / "src"
        public_dir = preview_dir / "public"
        src_dir.mkdir(parents=True, exist_ok=True)
        public_dir.mkdir(parents=True, exist_ok=True)

        prepared_clips, asset_report = self._prepare_clips(visual_clips, context, public_dir)
        composition = {
            "id": "NarrascapeTimeline",
            "fps": int(config.encode.fps),
            "width": int(config.encode.width),
            "height": int(config.encode.height),
            "durationInFrames": self._duration_in_frames(
                timeline, prepared_clips, config.encode.fps
            ),
        }
        timeline_json = {
            "schemaVersion": "narrascape.remotion_timeline.v1",
            "sourceTimeline": timeline_path.relative_to(config.project_dir).as_posix(),
            "project": timeline.get("project", {}),
            "composition": composition,
            "clips": prepared_clips,
            "narration": timeline.get("tracks", {}).get("narration", []),
            "music": timeline.get("tracks", {}).get("music", []),
            "subtitles": timeline.get("tracks", {}).get("subtitles", []),
        }

        (public_dir / "timeline.json").write_text(
            json.dumps(timeline_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (src_dir / "timeline-data.json").write_text(
            json.dumps(timeline_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_remotion_files(preview_dir, src_dir, composition)

        missing_assets = [
            item["timeline_path"] for item in asset_report if item.get("status") == "missing"
        ]
        report = {
            "schema_version": "remotion_preview.v1",
            "status": "ready" if not missing_assets else "missing_assets",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
                "root": preview_dir.as_posix(),
            },
            "composition": composition,
            "assets": {
                "copied": [
                    item for item in asset_report if item.get("status") in {"copied", "reused"}
                ],
                "missing": [item for item in asset_report if item.get("status") == "missing"],
            },
            "commands": {
                "install": "npm install",
                "studio": "npx remotion studio",
                "render": (
                    "npx remotion render "
                    "src/index.ts NarrascapeTimeline out/narrascape-preview.mp4"
                ),
                "still_check": (
                    "npx remotion still src/index.ts NarrascapeTimeline "
                    "out/still.png --frame=30 --scale=0.25"
                ),
            },
        }
        validate_artifact("remotion_preview", report)
        report_path = config.pipeline_dir / "remotion_preview.yaml"
        report_path.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")

        success = not missing_assets
        return StageResult(
            self.name,
            success,
            outputs=[report_path, preview_dir],
            message=(
                "Remotion preview project generated"
                if success
                else f"Remotion preview has missing assets: {missing_assets}"
            ),
            metadata={
                "preview_dir": preview_dir.as_posix(),
                "missing_assets": missing_assets,
                "composition": composition,
            },
        )

    def _prepare_clips(
        self,
        clips: list[dict[str, Any]],
        context: StageContext,
        public_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prepared: list[dict[str, Any]] = []
        asset_report: list[dict[str, Any]] = []
        for clip in sorted(clips, key=lambda item: float(item.get("start") or 0.0)):
            clip_id = str(clip.get("id") or f"clip_{len(prepared) + 1:03d}")
            source = str(clip.get("source") or "")
            prepared_clip = dict(clip)
            prepared_clip["id"] = clip_id
            prepared_clip["start"] = float(clip.get("start") or 0.0)
            prepared_clip["duration"] = float(clip.get("duration") or 1.0)
            prepared_clip["source"] = source

            if source == "ending_card":
                prepared_clip["remotionAsset"] = None
                prepared_clip["mediaType"] = "ending"
                prepared.append(prepared_clip)
                continue

            timeline_path = str(clip.get("path") or "")
            source_path = context.config.project_dir / timeline_path
            media_type = "image" if source == "generated_image" else "video"
            asset_name = self._asset_name(clip_id, source_path, media_type)
            target = public_dir / asset_name
            if source_path.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or source_path.stat().st_size != target.stat().st_size:
                    shutil.copy2(source_path, target)
                    status = "copied"
                else:
                    status = "reused"
                prepared_clip["remotionAsset"] = asset_name
            else:
                status = "missing"
                prepared_clip["remotionAsset"] = None

            prepared_clip["mediaType"] = media_type
            prepared.append(prepared_clip)
            asset_report.append(
                {
                    "clip_id": clip_id,
                    "source": source,
                    "timeline_path": timeline_path,
                    "public_asset": asset_name,
                    "status": status,
                }
            )
        return prepared, asset_report

    def _asset_name(self, clip_id: str, source_path: Path, media_type: str) -> str:
        suffix = source_path.suffix.lower()
        if not suffix:
            suffix = ".png" if media_type == "image" else ".mp4"
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clip_id)
        return f"assets/{safe_id}{suffix}"

    def _duration_in_frames(
        self,
        timeline: dict[str, Any],
        clips: list[dict[str, Any]],
        fps: int,
    ) -> int:
        duration = float(timeline.get("duration") or 0.0)
        for clip in clips:
            duration = max(duration, float(clip["start"]) + float(clip["duration"]))
        return max(1, int(round(duration * fps)))

    def _write_remotion_files(
        self,
        preview_dir: Path,
        src_dir: Path,
        composition: dict[str, Any],
    ) -> None:
        (preview_dir / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {
                        "studio": "remotion studio",
                        "render": (
                            "remotion render src/index.ts NarrascapeTimeline "
                            "out/narrascape-preview.mp4"
                        ),
                        "still": (
                            "remotion still src/index.ts NarrascapeTimeline "
                            "out/still.png --frame=30 --scale=0.25"
                        ),
                    },
                    "dependencies": {
                        "@remotion/media": "latest",
                        "remotion": "latest",
                        "react": "latest",
                        "react-dom": "latest",
                        "zod": "latest",
                    },
                    "devDependencies": {
                        "@types/react": "latest",
                        "typescript": "latest",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (preview_dir / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "jsx": "react-jsx",
                        "strict": True,
                        "noEmit": True,
                        "target": "ES2020",
                        "module": "ESNext",
                        "moduleResolution": "Bundler",
                        "resolveJsonModule": True,
                        "allowSyntheticDefaultImports": True,
                    },
                    "include": ["src"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (src_dir / "index.ts").write_text(
            "import {registerRoot} from 'remotion';\n"
            "import {RemotionRoot} from './Root';\n\n"
            "registerRoot(RemotionRoot);\n",
            encoding="utf-8",
        )
        (src_dir / "Root.tsx").write_text(self._root_template(composition), encoding="utf-8")
        (src_dir / "TimelineComposition.tsx").write_text(
            self._composition_template(), encoding="utf-8"
        )

    def _root_template(self, composition: dict[str, Any]) -> str:
        return f"""import {{Composition}} from 'remotion';
import timeline from './timeline-data.json';
import {{TimelineComposition, TimelineSchema}} from './TimelineComposition';

export const RemotionRoot = () => {{
  return (
    <Composition
      id="NarrascapeTimeline"
      component={{TimelineComposition}}
      durationInFrames={int(composition["durationInFrames"])}
      fps={int(composition["fps"])}
      width={int(composition["width"])}
      height={int(composition["height"])}
      defaultProps={{{{timeline}}}}
      schema={{TimelineSchema}}
    />
  );
}};
"""

    def _composition_template(self) -> str:
        return """import {Video} from '@remotion/media';
import type {CSSProperties, FC} from 'react';
import {AbsoluteFill, Img, Sequence, staticFile, useVideoConfig} from 'remotion';
import {z} from 'zod';

const ClipSchema = z.object({
  id: z.string(),
  source: z.string(),
  mediaType: z.string(),
  remotionAsset: z.string().nullable(),
  start: z.number(),
  duration: z.number(),
  source_in: z.number().optional(),
  shot_type: z.string().nullable().optional(),
  movement: z.string().nullable().optional(),
  emotion: z.string().nullable().optional(),
  character_ids: z.array(z.string()).optional(),
  storyboard_frame_ids: z.array(z.string()).optional(),
  composition: z.string().nullable().optional(),
});

const TimelineDataSchema = z.object({
  schemaVersion: z.string(),
  sourceTimeline: z.string(),
  project: z.object({}).passthrough(),
  composition: z.object({
    id: z.string(),
    fps: z.number(),
    width: z.number(),
    height: z.number(),
    durationInFrames: z.number(),
  }),
  clips: z.array(ClipSchema),
  narration: z.array(z.any()).optional(),
  music: z.array(z.any()).optional(),
  subtitles: z.array(z.any()).optional(),
});

export const TimelineSchema = z.object({timeline: TimelineDataSchema});

type TimelineProps = z.infer<typeof TimelineDataSchema>;
type Clip = z.infer<typeof ClipSchema>;

const frameOf = (seconds: number, fps: number) => Math.max(0, Math.round(seconds * fps));

const ClipLayer: FC<{clip: Clip}> = ({clip}) => {
  const {fps} = useVideoConfig();
  if (clip.source === 'ending_card') {
    return <AbsoluteFill style={{backgroundColor: '#060606'}} />;
  }
  if (!clip.remotionAsset) {
    return <AbsoluteFill style={{backgroundColor: '#180808'}} />;
  }
  const commonStyle: CSSProperties = {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
  };
  if (clip.mediaType === 'image') {
    return <Img src={staticFile(clip.remotionAsset)} style={commonStyle} />;
  }
  return (
    <Video
      src={staticFile(clip.remotionAsset)}
      trimBefore={frameOf(Math.max(0, clip.source_in ?? 0), fps)}
      muted
      style={commonStyle}
    />
  );
};

const DirectorOverlay: FC<{clip: Clip}> = ({clip}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: 32,
        bottom: 28,
        maxWidth: '64%',
        color: '#f8f4e9',
        fontFamily: 'Inter, Arial, sans-serif',
        fontSize: 18,
        lineHeight: 1.35,
        textShadow: '0 2px 16px rgba(0,0,0,0.75)',
      }}
    >
      <div style={{fontSize: 13, opacity: 0.72, marginBottom: 4}}>{clip.id}</div>
      <div>{[clip.shot_type, clip.movement, clip.emotion].filter(Boolean).join(' / ')}</div>
    </div>
  );
};

export const TimelineComposition: FC<{timeline: TimelineProps}> = ({timeline}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: '#050505'}}>
      {timeline.clips.map((clip) => (
        <Sequence
          key={clip.id}
          from={frameOf(clip.start, fps)}
          durationInFrames={Math.max(1, frameOf(clip.duration, fps))}
          premountFor={fps}
        >
          <ClipLayer clip={clip} />
          <DirectorOverlay clip={clip} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
"""
