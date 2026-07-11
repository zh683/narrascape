from __future__ import annotations

import queue
import sys
import time
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_i18n import zh_stage_label, zh_status
from narrascape.dashboard_jobs import build_stage_command, clean_stage_command
from narrascape.dashboard_pages.context import DashboardPageContext
from narrascape.dashboard_pages.shared import path_exists
from narrascape.dashboard_stage_view import (
    group_output_files,
    stage_label,
    stage_title,
    status_tag,
)


def render_pipeline_page(ctx: DashboardPageContext) -> None:
    st.header("流水线")

    _require_project_dir(ctx)

    stage_dashboard = ctx.get_stage_dashboard()
    stages = list(stage_dashboard.get("stages") or [])
    stage_names = [str(stage["name"]) for stage in stages]
    stage_labels = [
        f"{zh_stage_label(name, stage_label(name, ctx.stage_meta.get(name, {})))} - {zh_status(stages[index].get('status', 'pending'))}"
        for index, name in enumerate(stage_names)
    ]
    selected = st.selectbox(
        "阶段", range(len(stage_labels)), format_func=lambda i: f"{i + 1}. {stage_labels[i]}"
    )
    selected_stage = stage_names[selected]

    st.markdown("<div style='height:0.5em'></div>", unsafe_allow_html=True)
    render_stage_page(ctx, selected_stage)


def render_stage_page(ctx: DashboardPageContext, stage_name: str) -> None:
    meta = ctx.stage_meta.get(stage_name, {})
    title = zh_stage_label(stage_name, stage_title(stage_name, meta))
    description = meta.get("description", "")

    st.header(title)
    if description:
        st.markdown(
            "<div style='color:#737373;font-size:0.9em;line-height:1.6;margin-bottom:1.5em'>"
            f"{escape(str(description))}</div>",
            unsafe_allow_html=True,
        )

    project_dir = _require_project_dir(ctx)

    status = _get_stage_status(ctx, stage_name)
    stage_info = status.get("stage") or {}

    status_text = str(status.get("status") or "pending")
    approval_text = str(status.get("approval") or "unknown")
    tag = status_tag(status_text)
    st.markdown(
        f"""
<div style='display:flex;align-items:center;gap:16px;margin-bottom:1.5em'>
  <span class="tag tag-{tag}">{escape(zh_status(status_text))}</span>
  <span class="tag tag-pending">审批：{escape(zh_status(approval_text))}</span>
  <span style='color:#525252;font-size:0.8em'>{len(status['files'])} 个文件 &middot; {ctx.fmt_bytes(status['size'])}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-label'>输入与依赖</div>", unsafe_allow_html=True)
    inputs = meta.get("inputs", [])
    depends_on = stage_info.get("depends_on") or []
    if not inputs and not depends_on:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>没有上游依赖。</div>",
            unsafe_allow_html=True,
        )
    else:
        for dep in depends_on:
            dep_status = _get_stage_status(ctx, str(dep))
            dep_color = "#22c55e" if dep_status.get("done") else "#64748b"
            st.markdown(
                f"<div style='color:{dep_color};font-family:monospace;font-size:0.8em;padding:2px 0'>"
                f"依赖：{escape(zh_stage_label(str(dep)))} "
                f"<span style='color:#404040'>{escape(zh_status(dep_status.get('status', 'pending')))}</span></div>",
                unsafe_allow_html=True,
            )
        for item in inputs:
            found, info = path_exists(project_dir, str(item), ctx.fmt_size)
            color = "#22c55e" if found else "#ef4444"
            icon = "&#10003;" if found else "&#10007;"
            st.markdown(
                f"<div style='color:{color};font-family:monospace;font-size:0.8em;padding:2px 0'>"
                f"{icon} {escape(str(item))} <span style='color:#404040'>{escape(info)}</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:1em'></div>", unsafe_allow_html=True)

    st.markdown("<div class='section-label'>输出产物</div>", unsafe_allow_html=True)
    expected_outputs = [str(item) for item in stage_info.get("outputs", []) or []]
    if not status["done"]:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>尚未完成。可在下方运行或刷新该阶段。</div>",
            unsafe_allow_html=True,
        )
        _render_expected_outputs(expected_outputs)
    elif not status["files"]:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>阶段已完成，但登记的输出文件不存在。</div>",
            unsafe_allow_html=True,
        )
        _render_expected_outputs(expected_outputs)
    else:
        _render_output_files(ctx, status["files"])

    st.markdown("<div style='height:1.5em'></div>", unsafe_allow_html=True)
    _render_controls(ctx, stage_name)
    _render_stage_log(stage_name)


def _get_stage_status(ctx: DashboardPageContext, stage_name: str) -> dict[str, Any]:
    dashboard = ctx.get_stage_dashboard()
    stage = dashboard.get("stage_by_name", {}).get(stage_name)
    if not isinstance(stage, dict):
        return {"done": False, "files": [], "size": 0, "stage": None}
    files = [Path(str(row["path"])) for row in stage.get("output_files", []) if row.get("exists")]
    return {
        "done": stage.get("status") == "completed",
        "status": stage.get("status", "pending"),
        "approval": stage.get("approval", "unknown"),
        "files": files,
        "size": int(stage.get("output_size") or 0),
        "stage": stage,
    }


def _require_project_dir(ctx: DashboardPageContext) -> Path:
    project_dir = ctx.project_dir
    if project_dir is None:
        st.info("请从侧栏选择项目。")
        st.stop()
        raise RuntimeError("project unavailable")
    return project_dir


def _render_expected_outputs(paths: list[str]) -> None:
    if not paths:
        return
    with st.expander("预期输出"):
        for item in paths:
            st.markdown(f"<div class='file-row'>{escape(item)}</div>", unsafe_allow_html=True)


def _render_output_files(ctx: DashboardPageContext, files: list[Path]) -> None:
    grouped = group_output_files(files)

    if grouped.images:
        cols = st.columns(min(4, len(grouped.images[:8])))
        for index, path in enumerate(grouped.images[:8]):
            with cols[index % len(cols)]:
                st.image(str(path), use_container_width=True)
                st.caption(path.name)
    for path in grouped.video[:3]:
        st.video(str(path))
        st.caption(f"{path.name} - {ctx.fmt_size(path)}")
    for path in grouped.audio[:4]:
        st.audio(str(path), format=f"audio/{path.suffix.lstrip('.')}")
        st.caption(f"{path.name} - {ctx.fmt_size(path)}")
    for path in grouped.text[:6]:
        with st.expander(path.name):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                language = (
                    path.suffix.lstrip(".") if path.suffix in (".yaml", ".yml", ".json") else None
                )
                st.code(content[:1500], language=language)
            except Exception as exc:
                st.error(f"读取失败：{exc}")
    for path in grouped.other[:10]:
        st.markdown(
            f"<div class='file-row'>{escape(path.name)} &middot; {ctx.fmt_size(path)}</div>",
            unsafe_allow_html=True,
        )


def _render_controls(ctx: DashboardPageContext, stage_name: str) -> None:
    st.markdown("<div class='section-label'>阶段控制</div>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        dry = st.checkbox("试运行", key=f"dry_{stage_name}")
    with col2:
        force = st.checkbox("强制", key=f"force_{stage_name}")
    with col3:
        if st.button(
            "运行",
            use_container_width=True,
            key=f"run_{stage_name}",
            disabled=st.session_state.running_stage is not None,
        ):
            project_dir = _require_project_dir(ctx)
            ctx.start_command(
                stage_name,
                build_stage_command(
                    sys.executable,
                    project_dir,
                    stage_name,
                    force=force,
                    dry_run=dry,
                ),
            )
    with col4:
        if st.button("清理", use_container_width=True, key=f"clean_{stage_name}"):
            project_dir = _require_project_dir(ctx)
            ctx.start_command(
                f"clean_{stage_name}",
                clean_stage_command(sys.executable, project_dir, stage_name),
            )


def _render_stage_log(stage_name: str) -> None:
    if st.session_state.running_stage not in {stage_name, f"clean_{stage_name}"}:
        return
    st.markdown("<div class='section-label'>作业日志</div>", unsafe_allow_html=True)
    stage_log_queue: queue.Queue[str] | None = st.session_state.log_queue
    if stage_log_queue is not None:
        new_lines: list[str] = []
        while not stage_log_queue.empty():
            try:
                new_lines.append(stage_log_queue.get_nowait())
            except queue.Empty:
                break
        if new_lines:
            st.session_state.logs.extend(new_lines)
    if st.session_state.logs:
        log_text = "\n".join(st.session_state.logs[-200:])
        st.code(log_text, language=None)
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
