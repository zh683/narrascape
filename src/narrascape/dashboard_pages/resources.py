from __future__ import annotations

from pathlib import Path

import streamlit as st

from narrascape.dashboard_pages.context import DashboardPageContext


def render_resources_page(ctx: DashboardPageContext) -> None:
    st.header("资源")

    project_dir = _require_project_dir(ctx)
    assets = project_dir / "assets"
    tabs = st.tabs(["图像", "配音", "音乐", "视频", "成片输出"])

    with tabs[0]:
        _render_image_assets(ctx, assets / "images")
    with tabs[1]:
        _render_audio_assets(ctx, assets / "tts", empty_message="暂无配音音频。")
    with tabs[2]:
        _render_audio_assets(ctx, assets / "music", empty_message="暂无背景音乐。")
    with tabs[3]:
        _render_video_assets(ctx, assets / "videos")
    with tabs[4]:
        _render_output_assets(project_dir / "output")


def _require_project_dir(ctx: DashboardPageContext) -> Path:
    project_dir = ctx.project_dir
    if project_dir is None:
        st.info("请从侧栏选择项目。")
        st.stop()
        raise RuntimeError("project unavailable")
    return project_dir


def _render_image_assets(ctx: DashboardPageContext, image_dir: Path) -> None:
    if not image_dir.exists():
        _empty("图像目录不存在。")
        return
    files = sorted(image_dir.rglob("*"))
    image_files = [f for f in files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    _count(f"{len(image_files)} 张图像")
    if not image_files:
        _empty("暂无图像。")
        return
    cols = st.columns(4)
    for index, path in enumerate(image_files[:16]):
        with cols[index % 4]:
            st.image(str(path), use_container_width=True)
            st.caption(path.name, unsafe_allow_html=False)


def _render_audio_assets(ctx: DashboardPageContext, audio_dir: Path, *, empty_message: str) -> None:
    if not audio_dir.exists():
        _empty(empty_message)
        return
    files = sorted(path for path in audio_dir.rglob("*") if path.suffix.lower() in (".mp3", ".wav"))
    _count(f"{len(files)} 个文件")
    if not files:
        _empty(empty_message)
        return
    for path in files:
        st.audio(str(path))
        st.caption(f"{path.name} &middot; {ctx.fmt_size(path)}")


def _render_video_assets(ctx: DashboardPageContext, video_dir: Path) -> None:
    if not video_dir.exists():
        _empty("暂无视频。")
        return
    files = sorted(path for path in video_dir.rglob("*") if path.suffix.lower() in (".mp4", ".mov"))
    _count(f"{len(files)} 个文件")
    if not files:
        _empty("暂无视频。")
        return
    for path in files[:6]:
        st.video(str(path))
        st.caption(f"{path.name} &middot; {ctx.fmt_size(path)}")


def _render_output_assets(output_dir: Path) -> None:
    if not output_dir.exists():
        _empty("暂无成片输出。")
        return
    files = sorted(output_dir.rglob("*"))
    _count(f"{len(files)} 个文件")
    if not files:
        _empty("暂无成片输出。")
        return
    for path in files:
        if path.suffix.lower() in (".mp4", ".mov"):
            st.video(str(path))
        elif path.suffix.lower() in (".png", ".jpg"):
            st.image(str(path))
        st.caption(path.name)


def _count(text: str) -> None:
    st.markdown(
        f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{text}</div>",
        unsafe_allow_html=True,
    )


def _empty(text: str) -> None:
    st.markdown(
        f"<div style='color:#404040;font-style:italic'>{text}</div>",
        unsafe_allow_html=True,
    )
