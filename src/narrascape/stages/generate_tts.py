"""Generate TTS stage — integrate MiniMax T2A v2 API.

Reads script.yaml, calls MiniMax speech API, outputs to assets/tts/seg_*.mp3.
Generates timing.json for downstream stages.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

import yaml

from narrascape.api_keys import APIKeys
from narrascape.config import NarrascapeConfig, load_script
from narrascape.providers import select_provider, selection_metadata
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import find_ffprobe
from narrascape.utils.retry import retry_with_backoff

logger = logging.getLogger("narrascape.stages.generate_tts")


class GenerateTTSStage(Stage):
    """Generate narration audio from script using MiniMax T2A v2.

    Inputs:  script.yaml, config.yaml (tts section)
    Outputs: assets/tts/seg_*.mp3, pipeline/{name}/timing.json
    State:   pipeline/{name}/tts_state.json
    """

    name = "generate_tts"
    depends_on = []
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
        if not config.script_path.exists():
            return False, f"Script not found: {config.script_path}"
        selection = select_provider(config, "tts", intent=self._intent_for_config(config))
        if selection.tool.name == "local_tts":
            return True, ""
        if not self.api_key:
            return False, (
                f"{selection.tool.name} selected but MINIMAX_API_KEY not found. "
                "Set env var or .env file."
            )
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = load_script(config.script_path)
        tts_dir = config.tts_dir
        tts_dir.mkdir(parents=True, exist_ok=True)
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)
        selection = select_provider(config, "tts", intent=self._intent_for_config(config))
        provider_meta = selection_metadata(selection)

        tts_cfg = config.tts
        segments = script.segments
        ns = len(segments)

        if selection.tool.name == "local_tts":
            durations = {}
            for seg in segments:
                sid = seg.id
                out = tts_dir / f"seg_{sid:02d}.mp3"
                duration = max(1.0, min(6.0, len(seg.text) / 18.0))
                if not out.exists():
                    self._generate_local_tone(out, duration, sid)
                durations[str(sid)] = duration
            (pipe_dir / "timing.json").write_text(json.dumps(durations, indent=2), encoding="utf-8")
            state_path = pipe_dir / "tts_state.json"
            state = self._load_state(state_path)
            state["provider_selection"] = provider_meta
            state["done"] = [seg.id for seg in segments]
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            return StageResult(
                self.name,
                True,
                outputs=[tts_dir / f"seg_{seg.id:02d}.mp3" for seg in segments],
                message=f"{ns}/{ns} local TTS, total {sum(durations.values()):.0f}s",
                metadata={
                    "mode": "local",
                    "total_seconds": sum(durations.values()),
                    "provider_selection": provider_meta,
                },
            )

        # Budget check
        from narrascape.utils.budget import BudgetTracker
        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        est_cost = budget_tracker.get_cost_estimate("tts", ns)
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)

        # Asset isolation warning
        old = [f for f in tts_dir.glob("*.mp3") if f.stat().st_size > 0]
        if old:
            logger.warning(f"tts/ has {len(old)} old files. Archive before re-generating.")

        # Load state
        state_path = pipe_dir / "tts_state.json"
        state = self._load_state(state_path)
        state["provider_selection"] = provider_meta
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        done = set(state.get("done", []))

        logger.info(f"TTS: {ns} segments, model={tts_cfg.model}, voice={tts_cfg.voice_id}")
        logger.info(f"     speed={tts_cfg.speed}, pitch={tts_cfg.pitch}, rate={tts_cfg.sample_rate}Hz")

        global_dict = list(tts_cfg.pronunciation_dict) if tts_cfg.pronunciation_dict else []

        for seg in segments:
            sid = seg.id
            out = tts_dir / f"seg_{sid:02d}.mp3"

            if sid in done and out.exists():
                logger.info(f"  [{sid:02d}/{ns}] skip (cached)")
                continue

            text = seg.text.replace("\n", " ").strip()
            text = self._apply_pauses(text, seg, tts_cfg)
            merged_tone = self._merge_pronunciations(global_dict, seg.pronunciation)

            logger.info(f"  [{sid:02d}/{ns}] {len(text)} chars ...")

            payload = {
                "model": tts_cfg.model,
                "text": text,
                "stream": False,
                "output_format": "hex",
                "voice_setting": {
                    "voice_id": tts_cfg.voice_id,
                    "speed": tts_cfg.speed,
                    "vol": tts_cfg.vol,
                    "pitch": tts_cfg.pitch,
                    "text_normalization": tts_cfg.text_normalization,
                },
                "audio_setting": {
                    "sample_rate": tts_cfg.sample_rate,
                    "format": "mp3",
                    "bitrate": 128000,
                    "channel": 1,
                },
                "language_boost": tts_cfg.language_boost,
            }

            # speech-2.8 continuous_sound
            if "2.8" in tts_cfg.model:
                payload["continuous_sound"] = tts_cfg.continuous_sound

            if merged_tone:
                payload["pronunciation_dict"] = {"tone": merged_tone}

            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.base_url}/v1/t2a_v2", data=data, method="POST"
                )
                req.add_header("Authorization", f"Bearer {self.api_key}")
                req.add_header("Content-Type", "application/json")

                r = retry_with_backoff(
                    lambda: json.loads(urllib.request.urlopen(req, timeout=120).read().decode()),
                    max_retries=3,
                    base_delay=2.0,
                    retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
                )

                if r["base_resp"]["status_code"] != 0:
                    logger.error(f"FAIL: {r['base_resp']}")
                    state["errors"].append(f"seg_{sid}: {r['base_resp']}")
                else:
                    raw_hex = r["data"]["audio"].replace(" ", "").replace("\n", "").replace("\r", "").strip()
                    raw = bytes.fromhex(raw_hex)
                    out.write_bytes(raw)
                    done.add(sid)
                    state["done"] = list(done)
                    logger.info(f"OK {out.stat().st_size / 1024:.0f}KB")
                    # Record actual cost per successful TTS generation
                    per_tts = budget_tracker.get_cost_estimate("tts", 1)
                    budget_tracker.record(per_tts)
            except Exception as e:
                logger.error(f"FAIL: {e}")
                state["errors"].append(f"seg_{sid}: {e}")

            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.3)

        # Generate timing.json
        logger.info("  Measuring durations...")
        dur = {}
        ffprobe = find_ffprobe()
        for seg in segments:
            sid = seg.id
            mp3 = tts_dir / f"seg_{sid:02d}.mp3"
            if mp3.exists():
                r = subprocess.run(
                    [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(mp3)],
                    capture_output=True, text=True
                )
                try:
                    dur[str(sid)] = float(r.stdout.strip())
                    logger.info(f"  seg_{sid:02d}: {dur[str(sid)]:.1f}s")
                except ValueError:
                    dur[str(sid)] = max(8, len(seg.text) / 7.2)
            else:
                dur[str(sid)] = max(8, len(seg.text) / 7.2)

        (pipe_dir / "timing.json").write_text(json.dumps(dur, indent=2), encoding="utf-8")

        total = sum(dur.values())
        errors = state.get("errors", [])
        logger.info(f"Done: {len(done)}/{ns} OK, {len(errors)} errors, total {total:.0f}s ({total / 60:.1f}min)")

        return StageResult(
            self.name,
            len(errors) == 0,
            message=f"{len(done)}/{ns} OK, {len(errors)} errors, total {total:.0f}s",
            metadata={"provider_selection": provider_meta, "total_seconds": total, "errors": errors},
        )

    # ── Helpers ───────────────────────────

    def _load_state(self, path: Path) -> dict:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"done": [], "errors": []}

    def _intent_for_config(self, config: NarrascapeConfig) -> str:
        if config.tts.provider.value in ("piper", "local"):
            return "offline"
        return "creative"

    def _generate_local_tone(self, out: Path, duration: float, seg_id: int) -> None:
        from narrascape.utils.ffmpeg import run_ffmpeg

        frequency = 330 + (seg_id % 5) * 55
        run_ffmpeg(
            [
                "-f", "lavfi",
                "-i", f"sine=frequency={frequency}:duration={duration}:sample_rate=44100",
                "-af", "volume=0.08",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                str(out),
            ],
            desc=f"local tts seg {seg_id}",
            validate_output=False,
        )

    def _apply_pauses(self, text: str, seg: Any, tts_cfg: Any) -> str:
        if seg.pause_markers:
            for pm in seg.pause_markers:
                text = text.replace(pm.after, f"{pm.after}<#{pm.seconds}#>", 1)
            return text
        if tts_cfg.add_pauses:
            text = re.sub(r'([。！？])\s*', r'\1<#1.0#>', text)
            text = re.sub(r'(──|——)\s*', r'\1<#0.8#>', text)
            text = re.sub(r'([；;])\s*', r'\1<#0.6#>', text)
            text = re.sub(r'<#[\d.]+#>\s*$', '', text)
        return text

    def _merge_pronunciations(self, global_dict: list[str], segment_dict: list[str]) -> list[str]:
        merged = list(global_dict)
        if segment_dict:
            merged.extend(segment_dict)
        seen = {}
        for entry in merged:
            word = entry.split("/")[0] if "/" in entry else entry
            seen[word] = entry
        return list(seen.values())
