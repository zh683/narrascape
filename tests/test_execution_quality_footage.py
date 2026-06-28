from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import (
    AudioConfig,
    BGMMap,
    BGMZone,
    ImageConfig,
    ImageProvider,
    MusicAudioConfig,
    MusicProvider,
    NarrascapeConfig,
    ProjectConfig,
    TTSConfig,
    TTSProvider,
    VideoConfig,
    VideoProvider,
)
from narrascape.stages.base import StageContext


def _write_minimal_project(project_dir: Path) -> None:
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "A field recording begins."}]}),
        encoding="utf-8",
    )
    (project_dir / "image_prompts.yaml").write_text(
        yaml.safe_dump(
            {
                "prompts": [
                    {
                        "id": "img_01",
                        "shot_type": "medium",
                        "description": "A documentary image of the subject.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Provider Test",
                "segments": [
                    {
                        "segment_id": 1,
                        "shot_type": "medium",
                        "image_prompt": "A documentary image of the subject.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _config(tmp_path: Path, *, bgm: bool = False) -> NarrascapeConfig:
    project_dir = tmp_path / "project"
    _write_minimal_project(project_dir)
    bgm_map = (
        BGMMap(
            zones=[
                BGMZone(
                    id="zone_a",
                    covers=[1, 1],
                    label="Zone A",
                    prompt="quiet pulse",
                    min_duration=10,
                )
            ]
        )
        if bgm
        else BGMMap()
    )
    return NarrascapeConfig(
        project=ProjectConfig(
            name="project",
            title="Provider Test",
            script_file="scripts/script.yaml",
        ),
        images=ImageConfig(provider=ImageProvider.LOCAL, width=640, height=480),
        tts=TTSConfig(provider=TTSProvider.LOCAL),
        audio=AudioConfig(music=MusicAudioConfig(provider=MusicProvider.LOCAL)),
        bgm_map=bgm_map,
        project_dir=project_dir,
    )


def _context(config: NarrascapeConfig) -> StageContext:
    from narrascape.config import load_script

    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_generate_images_executes_provider_selected_by_selector(tmp_path):
    from narrascape.stages.generate_images import GenerateImagesStage

    config = _config(tmp_path)
    result = GenerateImagesStage(api_key=None).run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_image"
    state = json.loads((config.pipeline_dir / "image_gen_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_image"


def test_agnes_image_payload_uses_official_extra_body_format(tmp_path):
    from narrascape.stages.generate_images import GenerateImagesStage

    stage = GenerateImagesStage(api_key="fake")

    payload, url = stage._build_image_payload(
        provider="agnes",
        prompt="cinematic frame",
        size="1024x768",
        ref_image=["https://example.com/ref.png"],
        negative_prompt="watermark",
        model="doubao-seedream-5-0-260128",
        sample_strength=0.7,
        seed=42,
    )

    assert url == "https://apihub.agnes-ai.com/v1/images/generations"
    assert payload["model"] == "agnes-image-2.1-flash"
    assert payload["extra_body"]["response_format"] == "url"
    assert payload["extra_body"]["image"] == ["https://example.com/ref.png"]
    assert "response_format" not in payload


def test_agnes_image_payload_sanitizes_literary_risk_terms():
    from narrascape.stages.generate_images import GenerateImagesStage

    stage = GenerateImagesStage(api_key="fake")

    payload, _ = stage._build_image_payload(
        provider="agnes",
        prompt="A murderer hides an axe after a crime, blood on the floor.",
        size="1024x768",
        ref_image=None,
        negative_prompt="blood splatter, gore",
        model="agnes-image-2.1-flash",
        sample_strength=None,
        seed=None,
    )

    prompt = payload["prompt"].lower()
    negative = payload["negative_prompt"].lower()
    assert "murderer" not in prompt
    assert "axe" not in prompt
    assert "blood" not in prompt
    assert "gore" not in negative
    assert "period literary drama" in prompt


def test_agnes_image_provider_uses_rate_limit_sleep():
    from narrascape.stages.generate_images import GenerateImagesStage

    stage = GenerateImagesStage(api_key="fake", sleep_between=1.5)

    assert stage._sleep_between_for_provider("agnes") == 65.0
    assert stage._sleep_between_for_provider("seedream") == 1.5


def test_provider_selector_selects_agnes_image_when_configured(tmp_path):
    from narrascape.providers import select_provider

    config = _config(tmp_path)
    config.images.provider = ImageProvider.AGNES

    selection = select_provider(config, "image_generation", intent="creative")

    assert selection.tool.name == "agnes_image"
    assert selection.tool.requires == ["AGNES_API_KEY"]


def test_pre_production_uses_agnes_key_when_agnes_image_is_configured(tmp_path, monkeypatch):
    from narrascape.stages.pre_production import PreProductionStage

    config = _config(tmp_path)
    config.images.provider = ImageProvider.AGNES
    config.llm.mode = "none"
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_API_KEY", "agnes-key")

    can_run, reason = PreProductionStage(llm_client=None).can_run(_context(config))

    assert can_run, reason


def test_pre_production_extracts_director_notes_without_llm(tmp_path):
    from narrascape.stages.pre_production import PreProductionStage

    config = _config(tmp_path)
    (config.project_dir / "director_notes.md").write_text(
        """# Director Notes

## Character Bible

### raskolnikov

- Role: former student
- Age: early 20s
- Face and body: gaunt face, hollow eyes
- Wardrobe lock: worn dark student coat, old cap
- Behavior: avoids direct eye contact
- Negative anchors: not modern

## Scene Bible

### rented_room

- Core look: attic room, yellow wallpaper, narrow bed
- Lighting: sickly window light
- Continuity: never spacious
""",
        encoding="utf-8",
    )

    script = yaml.safe_load((config.script_path).read_text(encoding="utf-8"))
    from narrascape.config import Script

    parsed = Script(**script)
    characters, scenes = PreProductionStage(llm_client=None)._extract_characters_and_scenes(
        parsed, config
    )

    assert characters[0]["char_id"] == "raskolnikov"
    assert "worn dark student coat" in characters[0]["identity_block"]
    assert scenes[0]["scene_id"] == "rented_room"
    assert "yellow wallpaper" in scenes[0]["description"]


def test_pre_production_local_provider_still_extracts_director_notes(tmp_path):
    from narrascape.stages.pre_production import PreProductionStage

    config = _config(tmp_path)
    (config.project_dir / "director_notes.md").write_text(
        """# Director Notes

## Character Bible

### raskolnikov

- Role: former student
- Age: early 20s
- Face and body: gaunt face, hollow eyes
- Wardrobe lock: worn dark student coat, old cap
- Behavior: avoids direct eye contact

## Scene Bible

### rented_room

- Core look: attic room, yellow wallpaper, narrow bed
- Lighting: sickly window light
- Continuity: never spacious
""",
        encoding="utf-8",
    )

    result = PreProductionStage(llm_client=None).run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "pre_production.yaml").read_text(encoding="utf-8")
    )
    assert report["characters"][0]["char_id"] == "raskolnikov"
    assert "worn dark student coat" in report["characters"][0]["identity_block"]
    assert report["environments"][0]["scene_id"] == "rented_room"
    first_frame = report["storyboard"]["frames"][0]
    assert first_frame["character_refs"] == ["raskolnikov"]
    assert first_frame["scene_ref"] == "rented_room"


def test_pre_production_local_storyboard_uses_storyboard_intent_scene_refs(tmp_path):
    from narrascape.stages.pre_production import PreProductionStage

    config = _config(tmp_path)
    (config.project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Porfiry smiles while the student feels trapped."},
                    {"id": 2, "text": "Sonya listens beside the candle."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.project_dir / "director_notes.md").write_text(
        """# Director Notes

## Character Bible

### raskolnikov

- Role: former student
- Wardrobe lock: worn dark student coat

### porfiry

- Role: investigating magistrate
- Wardrobe lock: dark civil-service coat

### sonya

- Role: moral witness
- Wardrobe lock: plain faded brown dress, small cross

## Scene Bible

### police_office

- Core look: papers, ink, dark wood, frosted windows.
- Lighting: gray daylight and small lamp pools.

### sonya_room

- Core look: poor room, icon corner, candle.
- Lighting: warm candle against cold window.

## Storyboard Intent

- `sb_01_01`: Porfiry leaning back in the office, polite smile, Raskolnikov trapped by empty space.
- `sb_02_01`: Sonya listening in her room, candle between her and Raskolnikov.
""",
        encoding="utf-8",
    )

    result = PreProductionStage(llm_client=None).run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "pre_production.yaml").read_text(encoding="utf-8")
    )
    frames = report["storyboard"]["frames"]
    assert frames[0]["scene_ref"] == "police_office"
    assert set(frames[0]["character_refs"]) == {"porfiry", "raskolnikov"}
    assert frames[1]["scene_ref"] == "sonya_room"
    assert set(frames[1]["character_refs"]) == {"sonya", "raskolnikov"}


def test_pre_production_reference_prompt_sanitizes_for_agnes(tmp_path, monkeypatch):
    from narrascape.stages.pre_production import PreProductionStage

    config = _config(tmp_path)
    config.images.provider = ImageProvider.AGNES
    refs_dir = config.project_dir / "assets" / "references"
    refs_dir.mkdir(parents=True)
    calls: list[str] = []

    def fake_generate_one(self, prompt, out_name, size, ref_image, images_dir, **kwargs):
        calls.append(prompt)
        (images_dir / f"{out_name}.png").write_bytes(b"png")
        return True

    monkeypatch.setattr(
        "narrascape.stages.generate_images.GenerateImagesStage._generate_one",
        fake_generate_one,
    )
    monkeypatch.setattr("narrascape.stages.pre_production.time.sleep", lambda seconds: None)

    stage = PreProductionStage(
        llm_client=None,
        generate_turns=False,
        generate_expressions=False,
    )
    sheet = stage._generate_character_reference(
        {
            "char_id": "raskolnikov",
            "name": "Raskolnikov",
            "identity_block": "former student, murderer, hiding an axe, worn dark student coat",
        },
        refs_dir,
        config,
        style_anchor_path=None,
        unified_style="19th-century literary drama",
        image_provider="agnes",
    )

    assert sheet.primary_reference_path
    prompt = calls[0].lower()
    assert "murderer" not in prompt
    assert "axe" not in prompt
    assert "worn dark student coat" in prompt


def test_generate_images_reports_empty_prompt_file_as_stage_failure(tmp_path):
    from narrascape.stages.generate_images import GenerateImagesStage

    config = _config(tmp_path)
    (config.project_dir / "image_prompts.yaml").write_text("", encoding="utf-8")

    result = GenerateImagesStage(api_key=None).run(_context(config))

    assert not result.success
    assert "No prompts" in result.message


def test_provider_selector_uses_health_circuit_breaker(tmp_path):
    from narrascape.providers import record_provider_failure, select_provider

    config = _config(tmp_path)
    config.images.provider = ImageProvider.SEEDREAM
    for _ in range(3):
        record_provider_failure(config, "seedream_image", "temporary outage")

    selection = select_provider(config, "image_generation", intent="creative")

    assert selection.tool.name == "local_image"


def test_provider_health_store_merges_failure_updates_under_lock(tmp_path):
    from narrascape.providers.health import ProviderHealthStore

    path = tmp_path / "provider_health.json"
    first = ProviderHealthStore(path)
    second = ProviderHealthStore(path)

    first.record_failure("seedream_image", "first")
    state = second.record_failure("seedream_image", "second")

    assert state.failure_count == 2
    snapshot = first.snapshot()
    assert snapshot["seedream_image"].failure_count == 2
    assert snapshot["seedream_image"].last_error == "second"


def test_generate_video_failure_records_provider_health(tmp_path, monkeypatch):
    from narrascape.providers.health import health_store_for_project
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.pipeline_dir.mkdir(parents=True)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")
    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    monkeypatch.setattr(stage, "_resolve_first_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(stage, "_generate_one", lambda *args, **kwargs: False)

    result = stage.run(_context(config))

    assert not result.success
    health = health_store_for_project(config.project_dir).snapshot()
    assert health["seedance_video"].failure_count == 1


def test_ffmpeg_media_args_resolve_dash_prefixed_paths(tmp_path):
    from narrascape.utils.ffmpeg import _normalize_ffmpeg_args, safe_media_arg

    media = tmp_path / "-clip.mp4"
    media.write_bytes(b"video")
    out = tmp_path / "-out.mp4"

    assert safe_media_arg(media) == str(media.resolve())
    args = _normalize_ffmpeg_args(["-i", str(media), "-c", "copy", str(out)])
    assert args[1] == str(media.resolve())
    assert args[-1] == str(out.resolve())

    relative_args = _normalize_ffmpeg_args(["-i", "-clip.mp4", "-c", "copy", "-out.mp4"])
    assert Path(relative_args[1]).is_absolute()
    assert Path(relative_args[-1]).is_absolute()


def test_get_duration_rejects_non_numeric_ffprobe_duration(tmp_path, monkeypatch):
    import subprocess

    import pytest

    from narrascape.utils.ffmpeg import get_duration

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    monkeypatch.setattr("narrascape.utils.ffmpeg.find_ffprobe", lambda: tmp_path / "ffprobe")
    monkeypatch.setattr(
        "narrascape.utils.ffmpeg.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="N/A\n", stderr=""),
    )

    with pytest.raises(RuntimeError, match="invalid ffprobe duration"):
        get_duration(media)


def test_generate_tts_executes_provider_selected_by_selector(tmp_path, monkeypatch):
    from narrascape.stages.generate_tts import GenerateTTSStage

    config = _config(tmp_path)
    stage = GenerateTTSStage(api_key=None)
    monkeypatch.setattr(
        stage, "_generate_local_tone", lambda out, duration, seg_id: out.write_bytes(b"tone")
    )

    result = stage.run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_tts"
    state = json.loads((config.pipeline_dir / "tts_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_tts"


def test_generate_music_executes_provider_selected_by_selector(tmp_path, monkeypatch):
    from narrascape.stages.generate_music import GenerateMusicStage

    config = _config(tmp_path, bgm=True)
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 4.0}), encoding="utf-8")
    stage = GenerateMusicStage(api_key=None)
    monkeypatch.setattr(
        stage, "_generate_local_music", lambda out, duration, index: out.write_bytes(b"music")
    )

    result = stage.run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_music"
    state = json.loads((config.pipeline_dir / "bgm_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_music"


def test_generate_video_checks_selected_provider_requirements(tmp_path):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")

    can_run, reason = GenerateVideoStage(api_key=None).can_run(_context(config))

    assert not can_run
    assert "seedance_video" in reason
    assert "ARK_API_KEY" in reason


def test_generate_video_checks_agnes_provider_requirements(tmp_path):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.video = VideoConfig(provider=VideoProvider.AGNES, model="agnes-video-v2.0")
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")

    can_run, reason = GenerateVideoStage(api_key=None).can_run(_context(config))

    assert not can_run
    assert "agnes_video" in reason
    assert "AGNES_API_KEY" in reason


def test_generate_video_passes_selected_agnes_provider_to_execution(tmp_path, monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.video = VideoConfig(provider=VideoProvider.AGNES, model="agnes-video-v2.0")
    config.pipeline_dir.mkdir(parents=True)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")
    monkeypatch.setenv("AGNES_API_KEY", "agnes-key")
    calls: list[dict[str, object]] = []

    stage = GenerateVideoStage(api_key=None, sleep_between=0)
    monkeypatch.setattr(stage, "_resolve_first_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(stage, "_reference_inputs_for_segment", lambda *args, **kwargs: {
        "uploaded_reference_images": [],
        "state": {},
    })

    def fake_generate_one(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        out_name = args[1]
        (config.project_dir / "assets" / "videos" / f"{out_name}.mp4").write_bytes(b"video")
        return True

    monkeypatch.setattr(stage, "_generate_one", fake_generate_one)

    result = stage.run(_context(config))

    assert result.success
    assert calls
    assert calls[0]["kwargs"]["provider"] == "agnes"


def test_generate_video_passes_compiled_agnes_negative_prompt_to_execution(
    tmp_path, monkeypatch
):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.video = VideoConfig(provider=VideoProvider.AGNES, model="agnes-video-v2.0")
    config.pipeline_dir.mkdir(parents=True)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")
    (config.pipeline_dir / "director_contract.yaml").write_text(
        yaml.safe_dump(
            {
                "shots": [
                    {
                        "segment_id": 1,
                        "continuity_constraints": {
                            "characters": ["mira"],
                            "location": "green-lit research lab",
                            "wardrobe": "field coat with brass name pin",
                        },
                        "storyboard_binding": {
                            "storyboard_frame_ids": ["sb_01_01"],
                            "reference_image_ids": ["char_mira", "scene_lab"],
                            "composition_requirements": [
                                "Mira framed in a restrained medium shot at the lab bench"
                            ],
                        },
                        "generation": {
                            "video_prompt": (
                                "Mira stands in a green-lit research lab, wearing a field "
                                "coat with a brass name pin, restrained medium shot with "
                                "slow camera drift across the lab bench. Cinematic "
                                "photorealistic motion with coherent physical detail."
                            ),
                            "compiled_prompts": {
                                "agnes": {
                                    "prompt": (
                                        "Mira stands in a green-lit research lab, wearing a "
                                        "field coat with a brass name pin, restrained medium "
                                        "shot with slow camera drift across the lab bench. "
                                        "Cinematic photorealistic motion with coherent "
                                        "physical detail."
                                    ),
                                    "negative_prompt": "watermark, extra limbs",
                                }
                            },
                        },
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGNES_API_KEY", "agnes-key")
    calls: list[dict[str, object]] = []

    stage = GenerateVideoStage(api_key=None, sleep_between=0)
    monkeypatch.setattr(stage, "_resolve_first_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        stage,
        "_reference_inputs_for_segment",
        lambda *args, **kwargs: {
            "uploaded_reference_images": [],
            "state": {},
        },
    )

    def fake_generate_one(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        out_name = args[1]
        (config.project_dir / "assets" / "videos" / f"{out_name}.mp4").write_bytes(b"video")
        return True

    monkeypatch.setattr(stage, "_generate_one", fake_generate_one)

    result = stage.run(_context(config))

    assert result.success
    assert calls
    assert calls[0]["args"][0].startswith("Mira stands in a green-lit research lab")
    assert calls[0]["kwargs"]["negative_prompt"] == "watermark, extra limbs"


def test_generate_video_accepts_pipeline_design_report(tmp_path):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    root_report = config.project_dir / "design_report.yaml"
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "design_report.yaml").write_text(
        root_report.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    root_report.unlink()
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")

    can_run, reason = GenerateVideoStage(api_key=None).can_run(_context(config))

    assert not can_run
    assert "ARK_API_KEY" in reason
    assert "design_report.yaml not found" not in reason


def test_generate_video_download_failure_does_not_leave_final_file(tmp_path, monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task")
    monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.invalid/out.mp4")

    def fail_download(*args, **kwargs):
        raise OSError("download failed")

    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fail_download)

    ok = stage._generate_one("prompt", "vid_01", "model", "720p", None, None, videos_dir)

    assert ok is False
    assert not (videos_dir / "vid_01.mp4").exists()


def test_agnes_video_payload_uses_video_id_workflow():
    from narrascape.stages.generate_video import GenerateVideoStage

    stage = GenerateVideoStage(api_key="fake", duration=5)

    payload = stage._build_agnes_payload(
        prompt="A cinematic shot",
        model="agnes-video-v2.0",
        resolution="720p",
        first_frame="https://example.com/start.png",
        last_frame=None,
        reference_images=[],
    )

    assert payload["model"] == "agnes-video-v2.0"
    assert payload["image"] == "https://example.com/start.png"
    assert payload["num_frames"] == 121
    assert payload["frame_rate"] == 24


def test_agnes_video_payload_strips_data_uri_prefix():
    from narrascape.stages.generate_video import GenerateVideoStage

    stage = GenerateVideoStage(api_key="fake", duration=5)

    payload = stage._build_agnes_payload(
        prompt="A cinematic shot",
        model="agnes-video-v2.0",
        resolution="720p",
        first_frame="data:image/png;base64,QUJDRA==",
        last_frame=None,
        reference_images=["https://example.com/ref.png"],
    )

    assert payload["extra_body"]["image"] == ["QUJDRA==", "https://example.com/ref.png"]


def test_agnes_video_payload_compacts_base64_reference_images(tmp_path):
    from PIL import Image

    from narrascape.stages.generate_video import GenerateVideoStage

    image_path = tmp_path / "large_ref.png"
    Image.new("RGB", (1920, 1080), color=(90, 80, 70)).save(image_path)

    stage = GenerateVideoStage(api_key="fake", duration=5)
    data_uri = stage.uploader.upload(image_path)
    original_b64 = data_uri.split(",", 1)[1]

    payload = stage._build_agnes_payload(
        prompt="A cinematic shot",
        model="agnes-video-v2.0",
        resolution="720p",
        first_frame=data_uri,
        last_frame=None,
        reference_images=[],
    )

    compact_b64 = payload["image"]
    assert compact_b64 != original_b64
    assert len(compact_b64) < len(original_b64)


def test_agnes_video_reference_strategy_prioritizes_first_frame_and_character():
    from narrascape.stages.generate_video import GenerateVideoStage

    stage = GenerateVideoStage(api_key="fake", duration=5)

    refs = stage._ordered_reference_images(
        "first-frame",
        None,
        [
            {"url": "style-anchor", "role": "style"},
            {"url": "character-anchor", "role": "character"},
            {"url": "scene-mood", "role": "scene"},
            {"url": "extra-scene", "role": "scene"},
        ],
        provider="agnes",
    )

    assert refs == ["first-frame", "character-anchor", "scene-mood"]


def test_agnes_video_payload_sanitizes_literary_risk_terms():
    from narrascape.stages.generate_video import GenerateVideoStage

    stage = GenerateVideoStage(api_key="fake", duration=5)

    payload = stage._build_agnes_payload(
        prompt="A cinematic murder confession after violent crime, blood on the floor.",
        model="agnes-video-v2.0",
        resolution="720p",
        first_frame=None,
        last_frame=None,
        reference_images=[],
    )

    prompt = payload["prompt"].lower()
    assert "murder" not in prompt
    assert "violent" not in prompt
    assert "blood" not in prompt
    assert "period literary drama" in prompt


def test_agnes_video_provider_uses_rate_limit_sleep():
    from narrascape.stages.generate_video import GenerateVideoStage

    stage = GenerateVideoStage(api_key="fake", sleep_between=3.0)

    assert stage._sleep_between_for_provider("agnes") == 65.0
    assert stage._sleep_between_for_provider("seedance") == 3.0


def test_agnes_video_generation_downloads_completed_result(tmp_path, monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    calls = []

    monkeypatch.setattr(
        stage,
        "_create_agnes_task",
        lambda *args, **kwargs: ("task_1", "video_1"),
    )
    monkeypatch.setattr(
        stage,
        "_poll_agnes_task",
        lambda task_id=None, video_id=None: "https://example.com/out.mp4",
    )

    def fake_download(url, path, **kwargs):
        calls.append((url, path))
        path.write_bytes(b"video")

    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fake_download)
    monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)

    ok = stage._generate_one(
        "prompt",
        "vid_01",
        "agnes-video-v2.0",
        "720p",
        None,
        None,
        videos_dir,
        provider="agnes",
    )

    assert ok is True
    assert calls[0][0] == "https://example.com/out.mp4"
    assert (videos_dir / "vid_01.mp4").exists()


def test_agnes_video_task_creation_retries_read_timeout(monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    attempts = []
    sleeps = []

    class Response:
        def read(self):
            return json.dumps({"task_id": "task_1", "video_id": "video_1"}).encode()

    def fake_urlopen(req, timeout=60):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise TimeoutError("The read operation timed out")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    stage = GenerateVideoStage(api_key="fake")

    task_id, video_id = stage._create_agnes_task(
        "A cinematic shot",
        "agnes-video-v2.0",
        "720p",
        None,
        None,
        reference_images=[],
    )

    assert (task_id, video_id) == ("task_1", "video_1")
    assert attempts == [stage.AGNES_CREATE_TIMEOUT, stage.AGNES_CREATE_TIMEOUT]
    assert sleeps == [65.0]


def test_agnes_video_poll_uses_recommended_video_id_endpoint(monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    urls = []

    class Response:
        def read(self):
            return json.dumps(
                {
                    "status": "completed",
                    "remixed_from_video_id": "https://example.com/video.mp4",
                }
            ).encode()

    def fake_urlopen(req, timeout=30):
        urls.append(req.full_url)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    stage = GenerateVideoStage(api_key="fake", poll_interval=0, max_poll_time=10)

    result = stage._poll_agnes_task(video_id="video_123")

    assert result == "https://example.com/video.mp4"
    assert urls
    assert "agnesapi?video_id=video_123" in urls[0]


def test_generate_video_poll_exits_after_repeated_transport_errors(monkeypatch):
    import urllib.error

    from narrascape.stages.generate_video import GenerateVideoStage

    sleeps = []
    attempts = []

    def fail_urlopen(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.URLError("server unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    stage = GenerateVideoStage(
        api_key="fake",
        poll_interval=10,
        max_poll_time=300,
        max_poll_errors=2,
    )

    assert stage._poll_task("task") is None
    assert len(attempts) == 2
    assert sleeps == [10]


def test_qa_reports_deep_quality_checks(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    config = _config(tmp_path)
    config.output_dir.mkdir(parents=True)
    config.pipeline_dir.mkdir(parents=True)
    final = config.output_dir / "project-sub.mp4"
    final.write_bytes(b"video")
    (config.pipeline_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nhello\n", encoding="utf-8"
    )
    (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 10.0}), encoding="utf-8")
    (config.pipeline_dir / "image_gen_state.json").write_text(
        json.dumps({"provider_selection": {"name": "local_image"}}),
        encoding="utf-8",
    )
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"same")
    (config.images_dir / "img_02.png").write_bytes(b"same")

    monkeypatch.setattr("narrascape.stages.qa.validate_video", lambda path: True)
    monkeypatch.setattr(
        "narrascape.stages.qa.get_media_info",
        lambda path: {
            "format": {"duration": "4.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        },
    )
    stage = QAStage()
    monkeypatch.setattr(
        stage, "_detect_silence", lambda path: {"ok": False, "mean_volume_db": -90.0}
    )
    monkeypatch.setattr(
        stage, "_detect_black_frames", lambda path, duration: {"risk": True, "black_seconds": 4.0}
    )

    result = stage.run(_context(config))

    assert not result.success
    checks = result.metadata["report"]["checks"]
    assert checks["subtitle_output_present"] is True
    assert checks["duration_within_tolerance"] is False
    assert checks["audio_not_silent"] is False
    assert checks["black_frame_risk"] is True
    assert checks["repeated_shot_risk"] is True
    assert checks["placeholder_residue"] is True


def test_source_media_writes_real_footage_edit_timeline(tmp_path):
    from narrascape.stages.source_media import SourceMediaStage

    config = _config(tmp_path)
    media_dir = config.project_dir / "source_media"
    media_dir.mkdir()
    (media_dir / "archive_clip.mp4").write_bytes(b"video bytes")

    result = SourceMediaStage().run(_context(config))

    assert result.success
    timeline_path = config.project_dir / "footage_timeline.yaml"
    assert timeline_path.exists()
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    assert timeline["strategy"] == "source_media_first"
    assert timeline["edits"][0]["asset_id"] == "asset_001"
    assert timeline["edits"][0]["source_path"].endswith("archive_clip.mp4")
    assert timeline["edits"][0]["role"] == "documentary_footage"


def test_footage_edit_stage_renders_source_media_roughcut(tmp_path, monkeypatch):
    from narrascape.stages.footage_edit import FootageEditStage
    from narrascape.stages.source_media import SourceMediaStage

    config = _config(tmp_path)
    media_dir = config.project_dir / "source_media"
    media_dir.mkdir()
    (media_dir / "archive_clip.mp4").write_bytes(b"video bytes")
    SourceMediaStage().run(_context(config))

    def fake_run_ffmpeg(args, **kwargs):
        Path(args[-1]).write_bytes(b"rendered")
        return True

    monkeypatch.setattr("narrascape.stages.footage_edit.run_ffmpeg", fake_run_ffmpeg)

    result = FootageEditStage().run(_context(config))

    assert result.success
    assert result.outputs[0] == config.pipeline_dir / "footage_roughcut.mp4"
    assert (config.pipeline_dir / "source_media_segments" / "edit_001.mp4").exists()
    assert (config.pipeline_dir / "footage_roughcut.mp4").exists()
