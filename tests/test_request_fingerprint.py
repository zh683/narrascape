#!/usr/bin/env python3
"""Tests for request-level content-addressed fingerprints (P1-3/P1-9).

Covers the fingerprint primitive, the video task ledger fingerprint fields,
and the four paid generation stages' skip semantics: an artifact is reused
only when the output file exists AND the stored request fingerprint matches;
any change to prompt / model / parameters / reference content regenerates;
unrelated state metadata does not.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from narrascape.config import (
    BGMMap,
    BGMZone,
    NarrascapeConfig,
    ProjectConfig,
    Script,
)
from narrascape.stages.base import StageContext
from narrascape.stages.generate_video import GenerateVideoStage
from narrascape.stages.generate_video_services import (
    VideoTaskLedger,
    video_task_prompt_hash,
)
from narrascape.utils.fingerprint import (
    hash_file_content,
    hash_reference,
    request_fingerprint,
)


def _context(config):
    return StageContext(
        config=config,
        script=Script.model_construct(segments=[]),
    )


# ── Fingerprint primitive ────────────────────────────────────────────


class TestRequestFingerprint:
    def test_deterministic_and_param_order_irrelevant(self):
        fp1 = request_fingerprint(provider="p", model="m", prompt="x", params={"a": 1, "b": 2})
        fp2 = request_fingerprint(provider="p", model="m", prompt="x", params={"b": 2, "a": 1})
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_sensitive_to_every_request_component(self):
        base = {
            "provider": "p",
            "model": "m",
            "prompt": "x",
            "negative_prompt": "n",
            "params": {"size": "1024x1024"},
            "reference_hashes": ["abc"],
        }
        fp = request_fingerprint(**base)
        for override in (
            {"provider": "p2"},
            {"model": "m2"},
            {"prompt": "x2"},
            {"negative_prompt": "n2"},
            {"params": {"size": "2048x2048"}},
            {"reference_hashes": ["abd"]},
            {"reference_hashes": ["abc", "abd"]},
        ):
            changed = {**base, **override}
            assert request_fingerprint(**changed) != fp, override

    def test_hash_file_content_tracks_bytes(self, tmp_path):
        f = tmp_path / "ref.png"
        f.write_bytes(b"content-v1")
        h1 = hash_file_content(f)
        f.write_bytes(b"content-v2")
        assert hash_file_content(f) != h1

    def test_hash_reference_local_file_is_content_addressed(self, tmp_path):
        f1 = tmp_path / "a.png"
        f2 = tmp_path / "b.png"
        f1.write_bytes(b"same-bytes")
        f2.write_bytes(b"same-bytes")
        # Same content at different paths -> same hash (content addressing).
        assert hash_reference(str(f1)) == hash_reference(str(f2)) == hash_file_content(f1)
        f1.write_bytes(b"different-bytes")
        # Same path, changed content -> different hash.
        assert hash_reference(str(f1)) != hash_reference(str(f2))

    def test_hash_reference_url_and_data_uri_hash_the_string(self):
        url_hash = hash_reference("https://example.com/ref.png")
        assert url_hash == hash_reference("https://example.com/ref.png")
        assert url_hash != hash_reference("https://example.com/other.png")
        uri = "data:image/png;base64,aGVsbG8="
        assert hash_reference(uri) == hash_reference(uri)
        assert hash_reference(uri) != hash_reference("data:image/png;base64,d29ybGQ=")


# ── Video task ledger fingerprint fields ─────────────────────────────


def _ledger_record(ledger, out_name="vid_01", prompt="p", fp=None, status=None):
    ledger.record_created(
        out_name,
        task_id="task-1",
        provider="seedance",
        prompt_hash=video_task_prompt_hash(
            provider="seedance", model="model-x", resolution="720p", prompt=prompt
        ),
        model="model-x",
        resolution="720p",
        output_path=f"assets/videos/{out_name}.mp4",
        request_fingerprint=fp,
    )
    if status:
        ledger.update_status(out_name, status, video_url="https://example.com/v.mp4")


class TestLedgerFingerprint:
    def test_record_created_persists_request_fingerprint(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp="fp-123")
        record = json.loads((tmp_path / "video_tasks.json").read_text(encoding="utf-8"))["tasks"][
            "vid_01"
        ]
        assert record["request_fingerprint"] == "fp-123"

    def test_fingerprint_matches_only_succeeded_exact_match(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp="fp-1", status="succeeded")
        assert ledger.fingerprint_matches("vid_01", "fp-1") is True
        assert ledger.fingerprint_matches("vid_01", "fp-other") is False
        assert ledger.fingerprint_matches("vid_99", "fp-1") is False

    def test_fingerprint_matches_rejects_unfinished_and_legacy(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, out_name="vid_01", fp="fp-1")  # status submitted
        _ledger_record(ledger, out_name="vid_02", fp=None, status="succeeded")  # legacy
        assert ledger.fingerprint_matches("vid_01", "fp-1") is False
        assert ledger.fingerprint_matches("vid_02", "fp-1") is False

    def test_reusable_download_requires_fingerprint_when_present(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp="fp-1", status="succeeded")
        prompt_hash = ledger.get("vid_01")["prompt_hash"]
        assert ledger.find_reusable_download("vid_01", prompt_hash, "fp-1") is not None
        assert ledger.find_reusable_download("vid_01", prompt_hash, "fp-other") is None

    def test_reusable_download_legacy_record_falls_back_to_prompt_hash(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp=None, status="succeeded")  # legacy record
        prompt_hash = ledger.get("vid_01")["prompt_hash"]
        assert ledger.find_reusable_download("vid_01", prompt_hash, "fp-new") is not None
        assert ledger.find_reusable_download("vid_01", "wrong-hash", "fp-new") is None

    def test_resumable_requires_fingerprint_when_present(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp="fp-1")  # status submitted (resumable)
        prompt_hash = ledger.get("vid_01")["prompt_hash"]
        assert ledger.find_resumable("vid_01", prompt_hash, "fp-1") is not None
        # Same prompt_hash but different full request: must NOT resume —
        # the in-flight task would yield content that no longer matches.
        assert ledger.find_resumable("vid_01", prompt_hash, "fp-other") is None

    def test_resumable_legacy_record_falls_back_to_prompt_hash(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        _ledger_record(ledger, fp=None)  # legacy in-flight record
        prompt_hash = ledger.get("vid_01")["prompt_hash"]
        assert ledger.find_resumable("vid_01", prompt_hash, "fp-new") is not None


# ── Video stage skip semantics ───────────────────────────────────────


def _video_stage(tmp_path):
    stage = GenerateVideoStage(api_key="fake", poll_interval=0)
    stage._task_ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
    return stage


def _videos_dir(tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(exist_ok=True)
    return videos_dir


def _mock_video_download(monkeypatch):
    def fake_download(url, dest, **kwargs):
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fake_download)
    monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)


def _stage_fp(stage, prompt="p", negative_prompt="", **overrides):
    kwargs = {
        "provider": "seedance",
        "model": "model-x",
        "resolution": "720p",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "first_frame": None,
        "last_frame": None,
        "reference_images": None,
    }
    kwargs.update(overrides)
    return stage._video_request_fingerprint(**kwargs)


class TestVideoFingerprintSkip:
    def test_existing_file_with_matching_fingerprint_skips_provider(self, tmp_path, monkeypatch):
        stage = _video_stage(tmp_path)
        ledger = stage._task_ledger
        videos_dir = _videos_dir(tmp_path)
        (videos_dir / "vid_01.mp4").write_bytes(b"old-video")
        _ledger_record(ledger, fp=_stage_fp(stage), status="succeeded")

        def forbidden(*args, **kwargs):
            raise AssertionError("must not contact the provider")

        monkeypatch.setattr(stage, "_create_task", forbidden)
        monkeypatch.setattr(stage, "_poll_task", forbidden)

        ok = stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir)

        assert ok is True
        assert (videos_dir / "vid_01.mp4").read_bytes() == b"old-video"

    def test_prompt_change_regenerates_despite_existing_file(self, tmp_path, monkeypatch):
        stage = _video_stage(tmp_path)
        ledger = stage._task_ledger
        videos_dir = _videos_dir(tmp_path)
        (videos_dir / "vid_01.mp4").write_bytes(b"old-video")
        _ledger_record(
            ledger,
            prompt="old prompt",
            fp=_stage_fp(stage, prompt="old prompt"),
            status="succeeded",
        )

        created = []
        monkeypatch.setattr(stage, "_create_task", lambda *a, **k: created.append(1) or "task-new")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.com/new.mp4")
        _mock_video_download(monkeypatch)

        ok = stage._generate_one("new prompt", "vid_01", "model-x", "720p", None, None, videos_dir)

        assert ok is True
        assert created == [1]
        assert (videos_dir / "vid_01.mp4").read_bytes() != b"old-video"
        record = ledger.get("vid_01")
        assert record["request_fingerprint"] == _stage_fp(stage, prompt="new prompt")

    def test_negative_prompt_change_regenerates_with_same_prompt_hash(self, tmp_path, monkeypatch):
        """prompt_hash (task-equivalence key) is unchanged here by design;
        the full request fingerprint still forces a new task."""
        stage = _video_stage(tmp_path)
        videos_dir = _videos_dir(tmp_path)
        _ledger_record(
            stage._task_ledger,
            fp=_stage_fp(stage, negative_prompt=""),
            status="succeeded",
        )
        (videos_dir / "vid_01.mp4").write_bytes(b"old-video")

        created = []
        monkeypatch.setattr(stage, "_create_task", lambda *a, **k: created.append(1) or "task-new")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.com/n.mp4")
        _mock_video_download(monkeypatch)

        ok = stage._generate_one(
            "p",
            "vid_01",
            "model-x",
            "720p",
            None,
            None,
            videos_dir,
            negative_prompt="no text overlay",
        )

        assert ok is True
        assert created == [1]

    def test_succeeded_record_redownloads_for_free_when_file_missing(self, tmp_path, monkeypatch):
        stage = _video_stage(tmp_path)
        videos_dir = _videos_dir(tmp_path)
        _ledger_record(stage._task_ledger, fp=_stage_fp(stage), status="succeeded")

        def forbidden_create(*args, **kwargs):
            raise AssertionError("must not create a new paid task")

        monkeypatch.setattr(stage, "_create_task", forbidden_create)
        monkeypatch.setattr(stage, "_poll_task", forbidden_create)
        _mock_video_download(monkeypatch)

        ok = stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir)

        assert ok is True
        assert (videos_dir / "vid_01.mp4").exists()


# ── TTS stage skip semantics ─────────────────────────────────────────


def _tts_config(tmp_path, text="Hello world."):
    config = NarrascapeConfig(
        project=ProjectConfig(name="fp-tts", title="FP TTS", script_file="scripts/script.yaml"),
        project_dir=tmp_path,
    )
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "script.yaml").write_text(
        f"segments:\n- id: 1\n  text: {text}\n", encoding="utf-8"
    )
    return config


def _tts_selection():
    return SimpleNamespace(
        tool=SimpleNamespace(
            name="minimax_tts",
            provider="minimax",
            requires=["MINIMAX_API_KEY"],
            capability=SimpleNamespace(value="tts"),
        ),
        alternatives=[],
        score=1.0,
        reason="test",
    )


def _mock_tts_api(monkeypatch):
    calls = []
    body = json.dumps(
        {
            "base_resp": {"status_code": 0, "status_msg": "ok"},
            "data": {"audio": b"fake-mp3-bytes".hex()},
        }
    ).encode()

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return SimpleNamespace(read=lambda: body)

    monkeypatch.setattr(
        "narrascape.stages.generate_tts.select_provider", lambda *a, **k: _tts_selection()
    )
    monkeypatch.setattr("narrascape.stages.generate_tts.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return calls


class TestTtsFingerprintSkip:
    def _run(self, config):
        from narrascape.stages.generate_tts import GenerateTTSStage

        return GenerateTTSStage(api_key="fake").run(_context(config))

    def test_second_run_skips_paid_call_and_state_records_fingerprint(self, tmp_path, monkeypatch):
        config = _tts_config(tmp_path)
        calls = _mock_tts_api(monkeypatch)

        assert self._run(config).success is True
        assert len(calls) == 1
        state = json.loads((config.pipeline_dir / "tts_state.json").read_text(encoding="utf-8"))
        assert state["fingerprints"]["1"]

        assert self._run(config).success is True
        assert len(calls) == 1  # fingerprint match: no new paid request

    def test_script_text_change_regenerates(self, tmp_path, monkeypatch):
        config = _tts_config(tmp_path)
        calls = _mock_tts_api(monkeypatch)
        self._run(config)
        assert len(calls) == 1

        (tmp_path / "scripts" / "script.yaml").write_text(
            "segments:\n- id: 1\n  text: A completely different line.\n", encoding="utf-8"
        )
        self._run(config)
        assert len(calls) == 2

    def test_unrelated_state_metadata_does_not_regenerate(self, tmp_path, monkeypatch):
        config = _tts_config(tmp_path)
        calls = _mock_tts_api(monkeypatch)
        self._run(config)
        assert len(calls) == 1

        state_path = config.pipeline_dir / "tts_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["operator_note"] = "reviewed by QA at some point"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        self._run(config)
        assert len(calls) == 1

    def test_legacy_state_without_fingerprints_regenerates_once(self, tmp_path, monkeypatch):
        config = _tts_config(tmp_path)
        calls = _mock_tts_api(monkeypatch)
        config.pipeline_dir.mkdir(parents=True, exist_ok=True)
        config.tts_dir.mkdir(parents=True, exist_ok=True)
        (config.tts_dir / "seg_01.mp3").write_bytes(b"legacy-mp3")
        (config.pipeline_dir / "tts_state.json").write_text(
            json.dumps({"done": [1], "errors": []}), encoding="utf-8"
        )

        self._run(config)
        assert len(calls) == 1  # legacy state: fingerprint missing -> regenerate once

        self._run(config)
        assert len(calls) == 1  # fingerprint now recorded -> skip


# ── Music stage skip semantics ───────────────────────────────────────


def _music_config(tmp_path, prompt="quiet pulse"):
    config = NarrascapeConfig(
        project=ProjectConfig(name="fp-music", title="FP Music", script_file="scripts/script.yaml"),
        bgm_map=BGMMap(
            zones=[
                BGMZone(id="zone_a", covers=[1, 1], label="Zone A", prompt=prompt, min_duration=10)
            ]
        ),
        project_dir=tmp_path,
    )
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "script.yaml").write_text(
        "segments:\n- id: 1\n  text: Hello world.\n", encoding="utf-8"
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 4.0}), encoding="utf-8")
    return config


def _mock_music_api(monkeypatch):
    calls = []
    body = json.dumps(
        {
            "base_resp": {"status_code": 0, "status_msg": "ok"},
            "data": {"audio": b"fake-music-bytes".hex()},
        }
    ).encode()

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return SimpleNamespace(read=lambda: body)

    selection = SimpleNamespace(
        tool=SimpleNamespace(
            name="minimax_music",
            provider="minimax",
            requires=["MINIMAX_API_KEY"],
            capability=SimpleNamespace(value="music"),
        ),
        alternatives=[],
        score=1.0,
        reason="test",
    )
    monkeypatch.setattr(
        "narrascape.stages.generate_music.select_provider", lambda *a, **k: selection
    )
    monkeypatch.setattr("narrascape.stages.generate_music.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return calls


class TestMusicFingerprintSkip:
    def _run(self, config):
        from narrascape.stages.generate_music import GenerateMusicStage

        return GenerateMusicStage(api_key="fake").run(_context(config))

    def test_second_run_skips_paid_call(self, tmp_path, monkeypatch):
        config = _music_config(tmp_path)
        calls = _mock_music_api(monkeypatch)

        assert self._run(config).success is True
        assert len(calls) == 1
        state = json.loads((config.pipeline_dir / "bgm_state.json").read_text(encoding="utf-8"))
        assert state["fingerprints"]["zone_a"]

        assert self._run(config).success is True
        assert len(calls) == 1

    def test_prompt_change_regenerates(self, tmp_path, monkeypatch):
        config = _music_config(tmp_path)
        calls = _mock_music_api(monkeypatch)
        self._run(config)
        assert len(calls) == 1

        config.bgm_map.zones[0].prompt = "dramatic strings"
        self._run(config)
        assert len(calls) == 2

    def test_duration_change_regenerates(self, tmp_path, monkeypatch):
        config = _music_config(tmp_path)
        calls = _mock_music_api(monkeypatch)
        self._run(config)
        assert len(calls) == 1

        (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 40.0}), encoding="utf-8")
        self._run(config)
        assert len(calls) == 2


# ── Images stage skip semantics ──────────────────────────────────────


def _images_config(tmp_path, description="A documentary image."):
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="fp-images", title="FP Images", script_file="scripts/script.yaml"
        ),
        project_dir=tmp_path,
    )
    (tmp_path / "image_prompts.yaml").write_text(
        "prompts:\n" "- id: img_01\n" "  shot_type: medium\n" f"  description: {description}\n",
        encoding="utf-8",
    )
    return config


def _mock_images_api(monkeypatch):
    calls = []

    def fake_post(req, *, provider):
        calls.append(req)
        return {"data": [{"url": "https://example.com/img.jpg"}]}

    selection = SimpleNamespace(
        tool=SimpleNamespace(
            name="seedream_image",
            provider="volcengine",
            requires=["VOLCENGINE_API_KEY"],
            capability=SimpleNamespace(value="image_generation"),
        ),
        alternatives=[],
        score=1.0,
        reason="test",
    )
    monkeypatch.setattr(
        "narrascape.stages.generate_images.select_provider", lambda *a, **k: selection
    )
    monkeypatch.setattr(
        "narrascape.stages.generate_images.GenerateImagesStage._post_image_request",
        lambda self, req, *, provider: fake_post(req, provider=provider),
    )

    def fake_download(url, dest, **kwargs):
        dest.write_bytes(b"\xff\xd8" + b"0" * 200)

    def fake_ffmpeg(args, timeout=60):
        from pathlib import Path

        Path(args[-1]).write_bytes(b"\x89PNG" + b"0" * 2048)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("narrascape.stages.generate_images.download_to_path", fake_download)
    monkeypatch.setattr("narrascape.stages.generate_images.run_ffmpeg_raw", fake_ffmpeg)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return calls


class TestImagesFingerprintSkip:
    def _run(self, config, **stage_kwargs):
        from narrascape.stages.generate_images import GenerateImagesStage

        stage_kwargs.setdefault("api_key", "fake")
        stage_kwargs.setdefault("sleep_between", 0)
        return GenerateImagesStage(**stage_kwargs).run(_context(config))

    def test_second_run_skips_paid_call(self, tmp_path, monkeypatch):
        config = _images_config(tmp_path)
        calls = _mock_images_api(monkeypatch)

        assert self._run(config).success is True
        assert len(calls) == 1
        state = json.loads(
            (config.pipeline_dir / "image_gen_state.json").read_text(encoding="utf-8")
        )
        assert state["fingerprints"]["img_01"]

        assert self._run(config).success is True
        assert len(calls) == 1

    def test_prompt_change_regenerates(self, tmp_path, monkeypatch):
        config = _images_config(tmp_path)
        calls = _mock_images_api(monkeypatch)
        self._run(config)
        assert len(calls) == 1

        (tmp_path / "image_prompts.yaml").write_text(
            "prompts:\n"
            "- id: img_01\n"
            "  shot_type: medium\n"
            "  description: A completely different subject.\n",
            encoding="utf-8",
        )
        self._run(config)
        assert len(calls) == 2

    def test_reference_content_change_same_path_regenerates(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"reference-v1")
        config = _images_config(tmp_path)
        calls = _mock_images_api(monkeypatch)

        self._run(config, ref_image=str(ref))
        assert len(calls) == 1

        self._run(config, ref_image=str(ref))
        assert len(calls) == 1  # same reference content -> skip

        ref.write_bytes(b"reference-v2-changed-content")
        self._run(config, ref_image=str(ref))
        assert len(calls) == 2  # same path, new content -> regenerate

    def test_legacy_state_without_fingerprints_regenerates_once(self, tmp_path, monkeypatch):
        config = _images_config(tmp_path)
        calls = _mock_images_api(monkeypatch)
        config.pipeline_dir.mkdir(parents=True, exist_ok=True)
        config.images_dir.mkdir(parents=True, exist_ok=True)
        (config.images_dir / "img_01.png").write_bytes(b"legacy-png")
        (config.pipeline_dir / "image_gen_state.json").write_text(
            json.dumps({"done": ["img_01"], "errors": []}), encoding="utf-8"
        )

        self._run(config)
        assert len(calls) == 1

        self._run(config)
        assert len(calls) == 1


# ── Image uploader content-addressed cache ───────────────────────────


class TestUploaderContentCache:
    def test_same_path_changed_content_reuploads(self, tmp_path):
        from narrascape.uploader.image_uploader import ImageUploader

        uploader = ImageUploader(backend="base64")
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"content-v1")
        url1 = uploader.upload(ref)

        ref.write_bytes(b"content-v2-changed")
        url2 = uploader.upload(ref)

        assert url1 != url2  # no stale URL reuse for changed content
        assert len(uploader.get_cache()) == 2

    def test_same_content_hits_cache(self, tmp_path):
        from narrascape.uploader.image_uploader import ImageUploader

        uploader = ImageUploader(backend="base64")
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"stable-content")
        assert uploader.upload(ref) == uploader.upload(ref)
        assert len(uploader.get_cache()) == 1
