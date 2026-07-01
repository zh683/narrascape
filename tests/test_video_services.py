from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class _Uploader:
    def upload(self, value: str | Path) -> str:
        return f"uploaded://{Path(value).stem}"


def test_video_generation_planner_applies_provider_specific_config() -> None:
    from narrascape.stages.generate_video_services import VideoGenerationPlanner

    planner = VideoGenerationPlanner(
        model="jimeng-video-seedance-2.0",
        agnes_model="agnes-video-v2.0",
        resolution="720p",
        ratio="16:9",
        duration=5,
        frame_rate=24,
        takes=1,
        sleep_between=3.0,
    )
    config = SimpleNamespace(
        video=SimpleNamespace(
            ratio="9:16",
            duration=7,
            frame_rate=30,
            takes=3,
            resolution="1080p",
            model="agnes-video-v2.0",
        )
    )

    planner.apply_config(config, "agnes")

    assert planner.active_model("agnes") == "agnes-video-v2.0"
    assert planner.active_model("seedance") == "jimeng-video-seedance-2.0"
    assert planner.takes_per_shot() == 3
    assert planner.output_names_for_segment("vid_01", 3) == [
        "vid_01_take_01",
        "vid_01_take_02",
        "vid_01_take_03",
    ]
    assert planner.sleep_between_for_provider("agnes") == 65.0
    assert planner.segment_model({"agnes_model": "not-agnes"}, "agnes") == "agnes-video-v2.0"
    assert planner.segment_resolution({"agnes_resolution": "540p"}, "agnes") == "540p"


def test_video_prompt_builder_prefers_provider_contract_prompt() -> None:
    from narrascape.stages.generate_video_services import VideoPromptBuilder

    builder = VideoPromptBuilder()
    segment = {
        "segment_id": 4,
        "cinematic_format": "Fallback cinematic language.",
        "image_prompt": "Fallback image prompt.",
    }
    contract = {
        "generation": {
            "video_prompt": "Legacy execution prompt.",
            "negative_prompt": "legacy negative",
            "compiled_prompts": {
                "agnes": {
                    "prompt": "Agnes compiled execution prompt.",
                    "negative_prompt": "agnes negative",
                },
                "seedance": {
                    "prompt": "Seedance compiled execution prompt.",
                    "negative_prompt": "seedance negative",
                },
            },
        }
    }

    assert (
        builder.build_prompt(segment, contract_by_segment={4: contract}, provider="agnes")
        == "Agnes compiled execution prompt."
    )
    assert (
        builder.build_prompt(segment, contract_by_segment={4: contract}, provider="seedance")
        == "Seedance compiled execution prompt."
    )
    assert (
        builder.build_prompt(segment, contract_by_segment={4: contract}, provider=None)
        == "Legacy execution prompt."
    )
    assert builder.build_negative_prompt(contract, "agnes") == "agnes negative"


def test_video_reference_resolver_resolves_first_and_last_frames(tmp_path: Path) -> None:
    from narrascape.stages.generate_video_services import VideoReferenceResolver

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "img_02.png").write_bytes(b"png")
    resolver = VideoReferenceResolver(_Uploader())

    first_frame = resolver.resolve_first_frame(
        {"segment_id": 1, "reference_image_url": "https://example.test/ref.png"},
        images_dir,
        "img_01",
    )
    last_frame = resolver.resolve_last_frame(
        {"segment_id": 1, "reference_chain_ids": ["ending_02"]},
        images_dir,
        {
            "reference_image_chains": [
                {
                    "chain_id": "ending_02",
                    "usage_mode": "last_frame",
                    "generated_images": ["img_02.png"],
                }
            ]
        },
    )

    assert first_frame == "https://example.test/ref.png"
    assert last_frame == "uploaded://img_02"
