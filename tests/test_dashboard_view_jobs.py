from __future__ import annotations

from pathlib import Path

from narrascape.dashboard_jobs import (
    approve_stage_command,
    build_full_pipeline_command,
    build_stage_command,
    clean_stage_command,
)
from narrascape.dashboard_stage_view import group_output_files, stage_label, status_tag


def test_dashboard_job_commands_use_cli_entrypoint(tmp_path: Path):
    build = build_stage_command(
        "python",
        tmp_path,
        "generate_video",
        force=True,
        dry_run=True,
        approve=True,
    )
    clean = clean_stage_command("python", tmp_path, "generate_video")
    approve = approve_stage_command("python", tmp_path, "generate_video")
    full = build_full_pipeline_command("python", tmp_path, force=True)

    assert build == [
        "python",
        "-m",
        "narrascape.cli",
        "build",
        "-p",
        str(tmp_path),
        "--stage",
        "generate_video",
        "--force",
        "--dry-run",
        "--approve",
    ]
    assert clean == [
        "python",
        "-m",
        "narrascape.cli",
        "clean",
        "-p",
        str(tmp_path),
        "--stage",
        "generate_video",
    ]
    assert approve == [
        "python",
        "-m",
        "narrascape.cli",
        "approve",
        "-p",
        str(tmp_path),
        "--stage",
        "generate_video",
    ]
    assert full == [
        "python",
        "-m",
        "narrascape.cli",
        "build",
        "-p",
        str(tmp_path),
        "--force",
    ]


def test_dashboard_stage_view_helpers_group_outputs():
    files = [
        Path("frame.png"),
        Path("clip.mp4"),
        Path("voice.wav"),
        Path("report.yaml"),
        Path("notes.bin"),
    ]

    grouped = group_output_files(files)

    assert [item.name for item in grouped.images] == ["frame.png"]
    assert [item.name for item in grouped.video] == ["clip.mp4"]
    assert [item.name for item in grouped.audio] == ["voice.wav"]
    assert [item.name for item in grouped.text] == ["report.yaml"]
    assert [item.name for item in grouped.other] == ["notes.bin"]
    assert stage_label("director_contract", {}) == "Director Contract"
    assert status_tag("completed") == "done"
    assert status_tag("failed") == "warn"
    assert status_tag("pending") == "pending"
