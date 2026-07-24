from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_data import load_timeline_dashboard
from narrascape.dashboard_i18n import zh_stage_label, zh_status
from narrascape.dashboard_pages.context import DashboardPageContext
from narrascape.dashboard_pages.shared import clip_rows, fmt_seconds, render_source_mix


def render_timeline_page(ctx: DashboardPageContext) -> None:
    st.header("影片时间线")

    project_dir = _require_project_dir(ctx)

    pipeline_dir = _pipeline_dir(ctx)
    data = load_timeline_dashboard(project_dir, pipeline_dir)

    if data["status"] == "missing_timeline":
        st.markdown(
            "<div style='color:#737373;font-size:0.9em'>尚未生成 film_timeline.yaml。</div>",
            unsafe_allow_html=True,
        )
        st.code(f"narrascape build -p {ctx.project_dir} --stage film_timeline --approve")
        st.stop()

    coverage = data.get("coverage", {})
    visual = data.get("visual", [])
    remotion = data.get("remotion", {})
    rework_loop = data.get("rework_loop", {})
    _render_timeline_stats(data, coverage, visual, remotion)

    left, right = st.columns([2, 1])
    with left:
        _render_visual_track(data, visual)
    with right:
        _render_source_panel(ctx, data, remotion, rework_loop)


def _pipeline_dir(ctx: DashboardPageContext) -> Path:
    maybe_pipeline_dir = Path(ctx.config.pipeline_dir) if ctx.config else ctx.get_pipeline_dir()
    if maybe_pipeline_dir is None:
        st.info("流水线目录不可用。")
        st.stop()
        raise RuntimeError("pipeline directory unavailable")
    return maybe_pipeline_dir


def _require_project_dir(ctx: DashboardPageContext) -> Path:
    project_dir = ctx.project_dir
    if project_dir is None:
        st.info("请从侧栏选择项目。")
        st.stop()
        raise RuntimeError("project unavailable")
    return project_dir


def _render_timeline_stats(
    data: dict[str, Any],
    coverage: dict[str, Any],
    visual: object,
    remotion: dict[str, Any],
) -> None:
    visual_count = len(visual) if isinstance(visual, list) else 0
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{visual_count}</div>
  <div class="stat-label">画面片段</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{fmt_seconds(float(data.get("duration") or 0.0))}</div>
  <div class="stat-label">总时长</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col3:
        generated_segments = coverage.get("generated_video_segments")
        generated = len(generated_segments) if isinstance(generated_segments, list) else 0
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{generated}</div>
  <div class="stat-label">生成视频</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col4:
        missing_assets = data.get("missing_assets")
        missing_preview = remotion.get("missing")
        missing = (len(missing_assets) if isinstance(missing_assets, list) else 0) + (
            len(missing_preview) if isinstance(missing_preview, list) else 0
        )
        color = "#ef4444" if missing else "#22c55e"
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num" style="color:{color}">{missing}</div>
  <div class="stat-label">缺失素材</div>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_visual_track(data: dict[str, Any], visual: object) -> None:
    st.markdown("<div class='section-label'>画面轨道</div>", unsafe_allow_html=True)
    rows = clip_rows(visual if isinstance(visual, list) else [])
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.markdown(
            "<div style='color:#404040;font-style:italic'>暂无画面轨道。</div>",
            unsafe_allow_html=True,
        )

    if data.get("missing_assets"):
        st.markdown(
            "<div class='section-label'>时间线缺失素材</div>",
            unsafe_allow_html=True,
        )
        st.dataframe(data["missing_assets"], use_container_width=True, hide_index=True)


def _render_source_panel(
    ctx: DashboardPageContext,
    data: dict[str, Any],
    remotion: dict[str, Any],
    rework_loop: dict[str, Any],
) -> None:
    st.markdown("<div class='section-label'>素材来源构成</div>", unsafe_allow_html=True)
    raw_source_counts = data.get("source_counts")
    source_counts = (
        {str(key): int(value) for key, value in raw_source_counts.items() if isinstance(value, int)}
        if isinstance(raw_source_counts, dict)
        else {}
    )
    render_source_mix(source_counts)

    st.markdown(
        "<div class='section-label' style='margin-top:2em'>Remotion</div>",
        unsafe_allow_html=True,
    )
    status = remotion.get("status", "missing")
    tag_cls = "done" if status == "ready" else "warn"
    st.markdown(
        f"<span class='tag tag-{tag_cls}'>{zh_status(status)}</span>", unsafe_allow_html=True
    )
    root = remotion.get("root")
    if root:
        st.markdown(
            f"<div class='file-row' style='margin-top:0.8em'>{root}</div>",
            unsafe_allow_html=True,
        )
    _render_remotion_commands(ctx, remotion)
    _render_rework_loop(rework_loop)


def _render_remotion_commands(ctx: DashboardPageContext, remotion: dict[str, Any]) -> None:
    commands = remotion.get("commands") if isinstance(remotion.get("commands"), dict) else {}
    if commands:
        command_labels = {
            "install": "安装",
            "studio": "工作室",
            "still_check": "静帧检查",
            "render": "渲染",
        }
        for label in ("install", "studio", "still_check", "render"):
            command = commands.get(label)
            if command:
                st.markdown(
                    f"<div style='color:#525252;font-size:0.72em;margin-top:0.8em'>{command_labels[label]}</div>",
                    unsafe_allow_html=True,
                )
                st.code(command, language="bash")
    else:
        st.code(f"narrascape build -p {ctx.project_dir} --stage remotion_preview --approve")

    if remotion.get("missing"):
        st.markdown(
            "<div class='section-label'>预览缺失素材</div>",
            unsafe_allow_html=True,
        )
        st.dataframe(remotion["missing"], use_container_width=True, hide_index=True)


def _render_rework_loop(rework_loop: dict[str, Any]) -> None:
    st.markdown(
        "<div class='section-label' style='margin-top:2em'>返工回路</div>",
        unsafe_allow_html=True,
    )
    loop_status = rework_loop.get("status", "not_started")
    loop_tag = "warn" if rework_loop.get("blocking") else "done"
    if loop_status == "not_started":
        loop_tag = "pending"
    st.markdown(
        f"<span class='tag tag-{loop_tag}'>{zh_status(loop_status)}</span>",
        unsafe_allow_html=True,
    )
    loop_rows = [
        {"指标": "QA 错误", "数量": rework_loop.get("qa_error_count", 0)},
        {"指标": "QA 警告", "数量": rework_loop.get("qa_warning_count", 0)},
        {"指标": "返工动作", "数量": rework_loop.get("action_count", 0)},
        {"指标": "已执行动作", "数量": rework_loop.get("executed_count", 0)},
        {
            "指标": "创意建议",
            "数量": rework_loop.get("creative_recommendation_count", 0),
        },
        {"指标": "视觉问题", "数量": rework_loop.get("visual_finding_count", 0)},
    ]
    st.dataframe(loop_rows, use_container_width=True, hide_index=True)
    next_stages = rework_loop.get("next_stages") or []
    if next_stages:
        st.markdown(
            "<div style='color:#525252;font-size:0.72em;margin-top:0.8em'>下一阶段</div>",
            unsafe_allow_html=True,
        )
        st.code(" -> ".join(zh_stage_label(str(item)) for item in next_stages), language="text")
