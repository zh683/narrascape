"""Generate music stage — integrate MiniMax music generation API.

Reads bgm_map from config.yaml, calculates zone durations from timing.json,
generates background music segments to assets/music/.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from narrascape.api_keys import APIKeys
from narrascape.config import (
    BGMZone,
    MusicAudioConfig,
    NarrascapeConfig,
    ScriptSegment,
    load_script,
)
from narrascape.providers import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_duration
from narrascape.utils.retry import retry_with_backoff
from narrascape.utils.safe_io import atomic_write_bytes, atomic_write_json, load_json_mapping

logger = logging.getLogger("narrascape.stages.generate_music")


class GenerateMusicStage(Stage):
    """Generate background music zones using MiniMax music API.

    Inputs:  config.yaml (bgm_map), timing.json
    Outputs: assets/music/{zone_id}.mp3
    State:   pipeline/{name}/bgm_state.json
    """

    name = "generate_music"
    depends_on = ["generate_tts"]
    outputs = []

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimaxi.com",
    ):
        self.api_key = api_key or APIKeys.minimax()
        self.base_url = base_url

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        if not config.bgm_map or not config.bgm_map.zones:
            return True, ""
        selection = select_provider(config, "music", intent=self._intent_for_config(config))
        if selection.tool.name == "local_music":
            return True, ""
        if not self.api_key:
            return False, (
                f"{selection.tool.name} selected but MINIMAX_API_KEY not found. "
                "Set env var or .env file."
            )
        timing_path = config.pipeline_dir / "timing.json"
        if not timing_path.exists():
            return False, "timing.json not found. Run generate_tts first."
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = load_script(config.script_path)
        music_dir = config.music_dir
        music_dir.mkdir(parents=True, exist_ok=True)
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)
        selection = select_provider(config, "music", intent=self._intent_for_config(config))
        provider_meta = selection_metadata(selection)

        music_cfg = config.audio.music
        zones = config.bgm_map.zones
        zone_xfade = config.bgm_map.zone_crossfade
        segments = script.segments
        gap_default = config.visual.segment_gap
        gap_map = config.visual.gap_map
        model = music_cfg.model

        if not zones:
            state_path = pipe_dir / "bgm_state.json"
            atomic_write_json(
                state_path,
                {"done": [], "skipped": "no bgm zones", "provider_selection": provider_meta},
            )
            return StageResult(
                self.name,
                True,
                outputs=[],
                message="no BGM zones configured",
                metadata={"mode": "skipped", "provider_selection": provider_meta},
            )

        if selection.tool.name == "local_music":
            generated = []
            timing_path = pipe_dir / "timing.json"
            durations = (
                json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else {}
            )
            for i, zone in enumerate(zones):
                is_last = i == len(zones) - 1
                duration = self._calc_zone_duration(
                    zone, durations, segments, gap_map, gap_default, config, music_cfg, is_last
                )
                out = music_dir / f"{zone.id}.mp3"
                if not out.exists():
                    self._generate_local_music(out, min(duration, 8.0), i)
                generated.append(out)
            state_path = pipe_dir / "bgm_state.json"
            state = self._load_state(state_path)
            state["provider_selection"] = provider_meta
            state["done"] = [zone.id for zone in zones]
            atomic_write_json(state_path, state)
            record_provider_success(config, selection.tool.name)
            return StageResult(
                self.name,
                True,
                outputs=generated,
                message=f"{len(generated)}/{len(zones)} local BGM",
                metadata={
                    "mode": "local",
                    "count": len(generated),
                    "provider_selection": provider_meta,
                },
            )

        # Budget check
        from narrascape.utils.budget import BudgetTracker

        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        est_cost = budget_tracker.get_cost_estimate("music", len(zones))
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)

        # Asset isolation warning
        old = [f for f in music_dir.glob("*.mp3") if f.stat().st_size > 0]
        if old:
            logger.warning(f"music/ has {len(old)} old files. Archive before re-generating.")

        # Load timing
        timing_path = pipe_dir / "timing.json"
        durations = (
            json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else {}
        )

        # Load state
        bgm_state_path = pipe_dir / "bgm_state.json"
        bgm_state = self._load_state(bgm_state_path)
        bgm_state["provider_selection"] = provider_meta
        atomic_write_json(bgm_state_path, bgm_state)

        logger.info(f"BGM: {len(zones)} zones, model={model}")
        logger.info(f"     sample_rate={music_cfg.sample_rate}Hz, bitrate={music_cfg.bitrate}bps")

        total_narration = sum(float(v) for v in durations.values())
        total_gap = sum(gap_map.get(seg.id, gap_default) for seg in segments[:-1])
        logger.info(f"  Narration: {total_narration:.0f}s")
        logger.info(f"  Gaps:      {total_gap:.0f}s")

        generated = []
        for i, zone in enumerate(zones):
            is_last = i == len(zones) - 1
            dur = self._calc_zone_duration(
                zone, durations, segments, gap_map, gap_default, config, music_cfg, is_last
            )
            start_id = zone.covers[0] if zone.covers else 0
            end_id = zone.covers[-1] if zone.covers else 0
            label = zone.label or zone.id
            logger.info(
                f"[{i + 1}/{len(zones)}] {zone.id} ({label}) · seg {start_id}-{end_id} · target {dur:.0f}s"
            )
            result = self._generate_one(zone, dur, music_cfg, bgm_state, music_dir)
            if result:
                generated.append(result)
                if zone.id not in bgm_state.get("done", []):
                    bgm_state.setdefault("done", []).append(zone.id)
                    atomic_write_json(bgm_state_path, bgm_state)
                # Record actual cost per successful zone generation
                per_zone = budget_tracker.get_cost_estimate("music", 1)
                spend_ok, spend_msg = budget_tracker.try_spend(per_zone)
                if not spend_ok:
                    return StageResult(self.name, False, message=spend_msg)
            else:
                logger.error("FAILED - stopping")
                record_provider_failure(
                    config,
                    selection.tool.name,
                    f"music zone {zone.id} generation failed",
                )
                return StageResult(self.name, False, message=f"Zone {zone.id} generation failed")
            if i < len(zones) - 1:
                time.sleep(2)

        total_dur = 0.0
        for f in generated:
            try:
                total_dur += get_duration(f)
            except RuntimeError:
                logger.warning(f"Could not parse music duration for {f}")

        logger.info(
            f"Done: {len(generated)}/{len(zones)} OK, {total_dur:.0f}s ({total_dur / 60:.1f}min)"
        )
        record_provider_success(config, selection.tool.name)
        return StageResult(
            self.name,
            True,
            message=f"{len(generated)}/{len(zones)} OK, {total_dur:.0f}s",
            metadata={"provider_selection": provider_meta, "total_seconds": total_dur},
        )

    # ── Helpers ───────────────────────────

    def _load_state(self, path: Path) -> dict[str, Any]:
        return load_json_mapping(path, default={"done": []})

    def _intent_for_config(self, config: NarrascapeConfig) -> str:
        if config.audio.music.provider.value == "local":
            return "offline"
        return "creative"

    def _generate_local_music(self, out: Path, duration: float, index: int) -> None:
        from narrascape.utils.ffmpeg import run_ffmpeg

        frequency = 110 + (index % 4) * 35
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration={duration}:sample_rate=44100",
                "-af",
                "volume=0.035",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(out),
            ],
            desc=f"local music {out.stem}",
            validate_output=False,
        )

    def _calc_zone_duration(
        self,
        zone: BGMZone,
        durations: dict[str, Any],
        segments: list[ScriptSegment],
        gap_map: dict[int, float],
        gap_default: float,
        config: NarrascapeConfig,
        music_cfg: MusicAudioConfig,
        is_last: bool,
    ) -> float:
        start_id, end_id = zone.covers
        total = 0.0
        for seg in segments:
            sid = seg.id
            if sid < start_id or sid > end_id:
                continue
            total += _to_float(durations.get(str(sid)), default=0.0)
            if sid < end_id:
                total += gap_map.get(sid, gap_default)
        total *= 1.2
        if is_last:
            total += config.ending.duration + music_cfg.fade_out_seconds + 5
        return float(max(zone.min_duration, total))

    def _generate_one(
        self,
        zone: Any,
        duration_seconds: float,
        music_cfg: Any,
        state: dict[str, Any],
        music_dir: Path,
    ) -> Path | None:
        zid = zone.id
        out = music_dir / f"{zid}.mp3"
        if zid in state.get("done", []) and out.exists():
            logger.info("    skip (cached in state)")
            return out

        prompt = zone.prompt
        logger.info(
            f"    model={music_cfg.model}, {len(prompt)} chars (target ~{duration_seconds:.0f}s)"
        )

        payload = {
            "model": music_cfg.model,
            "prompt": prompt,
            "is_instrumental": True,
            "output_format": "hex",
            "audio_setting": {
                "sample_rate": music_cfg.sample_rate,
                "bitrate": music_cfg.bitrate,
                "format": "mp3",
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/music_generation", data=data, method="POST"
        )
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            r = retry_with_backoff(
                lambda: json.loads(urllib.request.urlopen(req, timeout=360).read().decode()),
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
            )
        except Exception as e:
            logger.error(f"    HTTP/API error: {e}")
            return None

        if r["base_resp"]["status_code"] != 0:
            logger.error(f"    Error: {r['base_resp']}")
            return None

        raw = bytes.fromhex(r["data"]["audio"])
        atomic_write_bytes(out, raw)

        # Check actual duration
        try:
            actual = get_duration(out)
        except RuntimeError:
            logger.warning(f"    WARN could not parse duration for {out}")
            actual = duration_seconds
        need = duration_seconds / 1.2
        ratio = actual / max(need, 1)
        if ratio > 3.0:
            logger.warning(
                f"    WARN {out.stat().st_size / 1024:.0f}KB, {actual:.0f}s (need ~{need:.0f}s) — {ratio:.1f}x, LIKELY LOOPED"
            )
        elif ratio > 2.0:
            logger.warning(
                f"    WARN {out.stat().st_size / 1024:.0f}KB, {actual:.0f}s (need ~{need:.0f}s) — {ratio:.1f}x"
            )
        else:
            logger.info(
                f"    OK {out.stat().st_size / 1024:.0f}KB, {actual:.0f}s (need ~{need:.0f}s)"
            )
        return out


def _to_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
