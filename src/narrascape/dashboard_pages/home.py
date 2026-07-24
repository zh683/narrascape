from __future__ import annotations

import queue
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_i18n import zh_stage_label
from narrascape.dashboard_jobs import build_full_pipeline_command
from narrascape.dashboard_pages.context import DashboardPageContext
from narrascape.dashboard_stage_view import stage_label


def render_home_page(ctx: DashboardPageContext) -> None:
    config = ctx.config
    project_path = _require_project_dir(ctx)

    title = config.project.title if config else project_path.name
    st.markdown(
        f"<div style='font-size:1.6em;font-weight:600;color:#fafafa'>{escape(str(title))}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='color:#525252;font-size:0.85em;margin-bottom:1.5em'>{escape(project_path.name)}</div>",
        unsafe_allow_html=True,
    )

    stage_dashboard = ctx.get_stage_dashboard()
    stages_done = int(stage_dashboard.get("completed") or 0)
    total_stages = int(stage_dashboard.get("total") or 0)
    pct = int(stage_dashboard.get("progress") or 0)
    pipeline_dir = ctx.get_pipeline_dir() or (project_path / "pipeline" / project_path.name)
    image_count = _image_count(project_path)

    _render_stats(stages_done, total_stages, pct, image_count)
    _render_stage_timeline(ctx, stage_dashboard, pct)
    _render_recent_files(ctx, pipeline_dir)
    _render_quick_actions(ctx)


def _image_count(project_dir: Path) -> int:
    assets = project_dir / "assets"
    return (
        sum(1 for item in (assets / "images").rglob("*") if item.is_file())
        if (assets / "images").exists()
        else 0
    )


def _require_project_dir(ctx: DashboardPageContext) -> Path:
    project_dir = ctx.project_dir
    if project_dir is None:
        st.info("未找到项目。请先运行：narrascape init my-video")
        st.stop()
        raise RuntimeError("project unavailable")
    return project_dir


def _render_stats(stages_done: int, total_stages: int, pct: int, image_count: int) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{stages_done}/{total_stages}</div>
  <div class="stat-label">制作阶段</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{pct}%</div>
  <div class="stat-label">总进度</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{image_count}</div>
  <div class="stat-label">图像</div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
<div style="margin:1.5em 0">
  <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_stage_timeline(
    ctx: DashboardPageContext,
    stage_dashboard: dict[str, Any],
    _pct: int,
) -> None:
    st.markdown("<div class='section-label'>流水线</div>", unsafe_allow_html=True)
    timeline_html = '<div class="stage-timeline">'
    current_stage = stage_dashboard.get("current_stage") or {}
    current_name = current_stage.get("name") if isinstance(current_stage, dict) else None
    raw_stages = stage_dashboard.get("stages")
    stages = raw_stages if isinstance(raw_stages, list) else []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        name = str(stage["name"])
        label = zh_stage_label(name, stage_label(name, ctx.stage_meta.get(name, {})))
        status = str(stage.get("status") or "pending")
        done = status == "completed"
        is_current = name == current_name
        dot_cls = "done" if done else "current" if is_current else "pending"
        node_cls = "done" if done else "current" if is_current else ""
        timeline_html += (
            f'<div class="stage-node {node_cls}"><div class="stage-dot {dot_cls}"></div>'
            f"{escape(label)}</div>"
        )
        if index < len(stages) - 1:
            timeline_html += '<span style="color:#262626">&rsaquo;</span>'
    timeline_html += "</div>"
    st.markdown(timeline_html, unsafe_allow_html=True)


def _render_recent_files(ctx: DashboardPageContext, pipeline_dir: Path) -> None:
    st.markdown(
        "<div class='section-label' style='margin-top:2em'>最近产物</div>",
        unsafe_allow_html=True,
    )
    if pipeline_dir.exists():
        all_files = sorted(
            [
                (file_path, file_path.stat().st_mtime)
                for directory in pipeline_dir.rglob("*")
                if directory.is_dir()
                for file_path in directory.rglob("*")
                if file_path.is_file()
            ],
            key=lambda item: item[1],
            reverse=True,
        )[:10]
        for file_path, mtime in all_files:
            rel = file_path.relative_to(pipeline_dir)
            ts = datetime.fromtimestamp(mtime).strftime("%H:%M")
            st.markdown(
                f"<div class='file-row'>{escape(str(rel))} &middot; {ctx.fmt_size(file_path)} &middot; {ts}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>尚无输出。</div>",
            unsafe_allow_html=True,
        )


def _render_quick_actions(ctx: DashboardPageContext) -> None:
    st.markdown(
        "<div class='section-label' style='margin-top:2em'>快速操作</div>",
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        dry = st.checkbox("试运行", key="dry_full_home")
    with col2:
        force = st.checkbox("强制重建", key="force_full_home")
    if st.button(
        "运行完整流水线",
        use_container_width=True,
        disabled=st.session_state.running_stage is not None,
    ):
        project_dir = _require_project_dir(ctx)
        ctx.start_command(
            "full_pipeline",
            build_full_pipeline_command(
                sys.executable,
                project_dir,
                force=force,
                dry_run=dry,
            ),
        )

    _render_full_pipeline_log()


def _render_full_pipeline_log() -> None:
    if st.session_state.running_stage != "full_pipeline":
        return
    st.markdown("<div class='section-label'>构建日志</div>", unsafe_allow_html=True)
    full_log_queue: queue.Queue[str] | None = st.session_state.log_queue
    if full_log_queue is not None:
        new_lines: list[str] = []
        while not full_log_queue.empty():
            try:
                new_lines.append(full_log_queue.get_nowait())
            except queue.Empty:
                break
        if new_lines:
            st.session_state.logs.extend(new_lines)
    if st.session_state.logs:
        st.code("\n".join(st.session_state.logs[-300:]), language=None)
    else:
        st.markdown(
            "<div style='color:#333;font-style:italic'>暂无输出…</div>",
            unsafe_allow_html=True,
        )
    if st.session_state.build_process is None:
        st.session_state.running_stage = None
        st.session_state.log_queue = None
        st.rerun()
    else:
        time.sleep(0.5)
        st.rerun()
