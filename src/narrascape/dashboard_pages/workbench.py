from __future__ import annotations

import queue
import sys
import time
from collections.abc import Iterable
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_i18n import (
    zh_artifact_label,
    zh_edge_label,
    zh_handle_label,
    zh_kind,
    zh_lane_label,
    zh_lifecycle_description,
    zh_lifecycle_label,
    zh_protocol_label,
    zh_quality_gate_label,
    zh_reason,
    zh_required_reason,
    zh_source,
    zh_stage_label,
    zh_status,
)
from narrascape.dashboard_jobs import approve_stage_command, build_stage_command
from narrascape.dashboard_pages.context import DashboardPageContext
from narrascape.dashboard_stage_view import stage_label
from narrascape.dashboard_workbench import load_workbench_dashboard


def render_workbench_page(ctx: DashboardPageContext) -> None:
    project_dir = _require_project_dir(ctx)
    pipeline_dir = _pipeline_dir(ctx)
    data = load_workbench_dashboard(project_dir, pipeline_dir)
    stage_summary = data.get("stage_summary", {})
    rework_loop = data.get("rework_loop", {})
    canvas = data.get("canvas", {}) if isinstance(data.get("canvas"), dict) else {}
    current_stage = stage_summary.get("current_stage") or {}
    current_label = _current_stage_label(ctx, current_stage)
    loop_status = str(rework_loop.get("status") or "not_started")
    progress = int(stage_summary.get("progress") or 0)

    _render_workbench_css()
    _render_title_bar(data, current_label, loop_status, progress)
    mode = _render_mode_switch()
    _render_operating_strip(data, current_label, loop_status, mode)

    canvas_col, agent_col = st.columns([3.4, 1.2], gap="large")
    with canvas_col:
        _render_session_lifecycle(data)
        _render_canvas(canvas)
        _render_node_inspector(ctx, data, project_dir)
    with agent_col:
        _render_session_handles(data)
        _render_agent_queue(ctx, data, project_dir)

    inspector_col, review_col = st.columns([2.1, 1], gap="large")
    with inspector_col:
        _render_artifact_drawer(data)
    with review_col:
        _render_rework_console(rework_loop)
        _render_rework_queues(data)
        _render_artifact_events(data)

    _render_command_log()


def _pipeline_dir(ctx: DashboardPageContext) -> Path:
    maybe_pipeline_dir = Path(ctx.config.pipeline_dir) if ctx.config else ctx.get_pipeline_dir()
    if maybe_pipeline_dir is None:
        st.info("当前项目没有可用的 pipeline 目录。")
        st.stop()
        raise RuntimeError("pipeline directory unavailable")
    return maybe_pipeline_dir


def _require_project_dir(ctx: DashboardPageContext) -> Path:
    project_dir = ctx.project_dir
    if project_dir is None:
        st.info("请先在侧边栏选择项目。")
        st.stop()
        raise RuntimeError("project unavailable")
    return project_dir


def _current_stage_label(ctx: DashboardPageContext, current_stage: Any) -> str:
    if isinstance(current_stage, dict) and current_stage:
        current_name = str(current_stage.get("name") or "")
        return zh_stage_label(
            current_name, stage_label(current_name, ctx.stage_meta.get(current_name, {}))
        )
    return "空闲"


def _render_workbench_css() -> None:
    st.markdown(
        """
<style>
  .stApp,
  .stApp * {
    font-family: Inter, "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
      "Noto Sans CJK SC", Arial, sans-serif;
    letter-spacing: 0;
  }
  .block-container {
    padding-top: 1.1rem;
    max-width: 100%;
  }
  .workbench-shell {
    margin: -0.15rem 0 0.85rem;
    padding: 0.42rem 0 0.25rem;
  }
  .workbench-title-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1.2rem;
    border-bottom: 1px solid #242823;
    padding-bottom: 0.85rem;
  }
  .workbench-title {
    color: #f7f5ed;
    font-size: 1.28rem;
    font-weight: 720;
    letter-spacing: 0;
    line-height: 1.2;
  }
  .workbench-subtitle {
    margin-top: 0.34rem;
    color: #8a9388;
    font-size: 0.75rem;
    line-height: 1.45;
    max-width: 52rem;
  }
  .workbench-meta {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 0.45rem;
    flex-wrap: wrap;
  }
  .wb-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.36rem;
    height: 1.7rem;
    padding: 0 0.58rem;
    border: 1px solid #2b312a;
    border-radius: 6px;
    background: #101410;
    color: #8d968b;
    font-size: 0.68rem;
    white-space: nowrap;
  }
  .wb-chip strong {
    color: #f2efe4;
    font-size: 0.72rem;
    font-weight: 680;
  }
  div[data-testid="stRadio"] {
    margin-bottom: 0.72rem;
  }
  div[data-testid="stRadio"] label {
    color: #b9c0b3 !important;
    font-size: 0.72rem !important;
  }
  div[role="radiogroup"] {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
  }
  div[role="radiogroup"] label {
    min-height: 2rem;
    padding: 0.2rem 0.72rem;
    border: 1px solid #2b312a;
    border-radius: 6px;
    background: #0f120f;
  }
  div[role="radiogroup"] label:has(input:checked) {
    border-color: rgba(40, 215, 197, 0.55);
    background: rgba(25, 76, 72, 0.45);
    color: #ecfffb !important;
  }
  .operation-strip {
    display: grid;
    grid-template-columns: 1.12fr repeat(4, minmax(0, 1fr));
    gap: 0.55rem;
    margin: 0.65rem 0 0.85rem;
  }
  .mode-live,
  .op-card {
    min-height: 4.75rem;
    border: 1px solid #272d26;
    border-radius: 8px;
    background: #101410;
    padding: 0.72rem 0.78rem;
    box-sizing: border-box;
  }
  .mode-live {
    border-color: rgba(40, 215, 197, 0.45);
    background:
      linear-gradient(90deg, rgba(40, 215, 197, 0.16), rgba(16, 20, 16, 0.95) 48%),
      #101410;
  }
  .op-card.is-warn {
    border-color: rgba(216, 169, 40, 0.42);
    background: rgba(44, 34, 13, 0.55);
  }
  .op-label {
    color: #8b9588;
    font-size: 0.6rem;
    font-weight: 720;
  }
  .op-value {
    margin-top: 0.28rem;
    color: #f5f2e8;
    font-size: 0.82rem;
    font-weight: 720;
    line-height: 1.18;
  }
  .op-note {
    margin-top: 0.35rem;
    color: #7b8578;
    font-size: 0.62rem;
    line-height: 1.28;
  }
  .canvas-frame {
    position: relative;
    height: 610px;
    overflow: auto;
    border: 1px solid #282e27;
    border-radius: 8px;
    background:
      linear-gradient(rgba(61, 70, 58, 0.16) 1px, transparent 1px),
      linear-gradient(90deg, rgba(61, 70, 58, 0.16) 1px, transparent 1px),
      linear-gradient(135deg, rgba(40, 215, 197, 0.06), transparent 22%),
      linear-gradient(315deg, rgba(216, 169, 40, 0.05), transparent 24%),
      #080a09;
    background-size: 30px 30px, 30px 30px, auto, auto, auto;
    box-shadow: inset 0 0 70px rgba(0, 0, 0, 0.48);
  }
  .canvas-surface {
    position: relative;
    min-width: 1484px;
    min-height: 540px;
  }
  .canvas-lane {
    position: absolute;
    top: 14px;
    color: #5f6a5d;
    font-size: 0.62rem;
    font-weight: 700;
  }
  .canvas-node {
    position: absolute;
    width: 164px;
    height: 92px;
    box-sizing: border-box;
    padding: 0.68rem 0.72rem 0.64rem;
    border: 1px solid #2b312a;
    border-radius: 8px;
    background: rgba(16, 20, 16, 0.94);
    box-shadow: 0 14px 26px rgba(0, 0, 0, 0.3);
    border-left-width: 3px;
  }
  .canvas-node.done {
    border-color: rgba(99, 212, 113, 0.44);
    background: rgba(12, 30, 22, 0.92);
  }
  .canvas-node.active {
    border-color: rgba(40, 215, 197, 0.72);
    background: rgba(8, 40, 39, 0.96);
    box-shadow: 0 0 0 1px rgba(40, 215, 197, 0.16), 0 16px 34px rgba(0, 0, 0, 0.36);
  }
  .canvas-node.attention {
    border-color: rgba(216, 169, 40, 0.72);
    background: rgba(40, 31, 13, 0.96);
  }
  .canvas-node.missing {
    border-color: rgba(96, 107, 92, 0.46);
    background: rgba(13, 16, 13, 0.88);
    opacity: 0.82;
  }
  .node-topline {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.45rem;
  }
  .node-kind {
    color: #7f897b;
    font-size: 0.57rem;
    font-weight: 700;
  }
  .node-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #5f6a5d;
    box-shadow: 0 0 0 3px rgba(95, 106, 93, 0.14);
    flex: 0 0 auto;
  }
  .done .node-status-dot { background: #63d471; box-shadow: 0 0 0 3px rgba(99, 212, 113, 0.12); }
  .active .node-status-dot { background: #28d7c5; box-shadow: 0 0 0 3px rgba(40, 215, 197, 0.16); }
  .attention .node-status-dot { background: #d8a928; box-shadow: 0 0 0 3px rgba(216, 169, 40, 0.16); }
  .node-title {
    margin-top: 0.48rem;
    color: #f7f5ed;
    font-size: 0.86rem;
    font-weight: 720;
    line-height: 1.08;
  }
  .node-meta {
    margin-top: 0.35rem;
    color: #899386;
    font-size: 0.64rem;
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .node-footer {
    position: absolute;
    left: 0.75rem;
    right: 0.75rem;
    bottom: 0.52rem;
    display: flex;
    justify-content: space-between;
    color: #7d8779;
    font-size: 0.6rem;
  }
  .canvas-edge {
    position: absolute;
    overflow: visible;
    pointer-events: none;
  }
  .canvas-edge path {
    fill: none;
    stroke: #30372f;
    stroke-width: 1.3;
  }
  .canvas-edge.done path { stroke: rgba(99, 212, 113, 0.36); }
  .canvas-edge.active path { stroke: rgba(40, 215, 197, 0.58); stroke-width: 1.7; }
  .canvas-edge.attention path { stroke: rgba(216, 169, 40, 0.56); stroke-width: 1.7; }
  .edge-label {
    position: absolute;
    color: #747e70;
    background: #080a09;
    border: 1px solid rgba(43, 49, 42, 0.9);
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 0.55rem;
    pointer-events: none;
  }
  .canvas-mini-toolbar {
    position: sticky;
    left: 0;
    top: 0;
    z-index: 4;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    min-width: 100%;
    padding: 0.62rem 0.72rem;
    background: linear-gradient(180deg, rgba(8,10,9,0.97), rgba(8,10,9,0.82));
    border-bottom: 1px solid rgba(40, 46, 39, 0.82);
  }
  .canvas-mini-title {
    color: #f2efe4;
    font-size: 0.72rem;
    font-weight: 700;
  }
  .canvas-mini-stats {
    display: flex;
    gap: 0.38rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .session-rail {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.48rem;
    margin-bottom: 0.68rem;
  }
  .session-step {
    min-height: 3.15rem;
    border: 1px solid #272d26;
    border-radius: 7px;
    background: #101410;
    padding: 0.58rem 0.62rem;
  }
  .session-step.done {
    border-color: rgba(99, 212, 113, 0.34);
    background: rgba(13, 30, 21, 0.72);
  }
  .session-step.active {
    border-color: rgba(40, 215, 197, 0.5);
    background: rgba(10, 39, 38, 0.84);
  }
  .session-step-label {
    color: #f3f0e6;
    font-size: 0.66rem;
    font-weight: 700;
  }
  .session-step-state {
    margin-top: 0.32rem;
    color: #7f897b;
    font-size: 0.59rem;
    line-height: 1.25;
  }
  .panel-title {
    color: #f1eee2;
    font-size: 0.72rem;
    font-weight: 700;
    margin-bottom: 0.75rem;
  }
  .panel-title::before {
    content: "";
    display: inline-block;
    width: 0.45rem;
    height: 0.45rem;
    margin-right: 0.42rem;
    border-radius: 50%;
    background: #28d7c5;
    vertical-align: 0.02rem;
  }
  .queue-item {
    border: 1px solid #272d26;
    border-radius: 7px;
    padding: 0.66rem;
    background: #101410;
    margin-bottom: 0.52rem;
  }
  .queue-item.primary {
    border-color: rgba(40, 215, 197, 0.5);
    background: rgba(10, 39, 38, 0.82);
  }
  .queue-label {
    color: #f7f5ed;
    font-weight: 650;
    font-size: 0.76rem;
    line-height: 1.2;
  }
  .queue-reason {
    margin-top: 0.3rem;
    color: #879184;
    font-size: 0.63rem;
    line-height: 1.35;
  }
  .queue-meta {
    margin-top: 0.48rem;
    display: flex;
    justify-content: space-between;
    color: #768173;
    font-size: 0.61rem;
  }
  .artifact-strip {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.48rem;
    margin-bottom: 0.8rem;
  }
  .artifact-tile {
    min-height: 4.85rem;
    border: 1px solid #272d26;
    border-radius: 7px;
    background: #101410;
    padding: 0.62rem;
  }
  .artifact-tile.attention { border-color: rgba(216, 169, 40, 0.46); background: rgba(40, 31, 13, 0.76); }
  .artifact-tile.done { border-color: rgba(99, 212, 113, 0.34); }
  .artifact-name {
    color: #f1eee2;
    font-size: 0.72rem;
    font-weight: 650;
    line-height: 1.2;
  }
  .artifact-path {
    margin-top: 0.35rem;
    color: #778173;
    font-size: 0.6rem;
    line-height: 1.22;
    word-break: break-all;
  }
  .artifact-status {
    margin-top: 0.42rem;
    color: #9aa391;
    font-size: 0.58rem;
  }
  .review-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.52rem;
  }
  div[data-testid="stVerticalBlock"] > div:has(> div .queue-item) .stCodeBlock pre {
    max-height: 4.9rem;
    overflow: auto;
  }
  .review-metric {
    border: 1px solid #272d26;
    border-radius: 7px;
    background: #101410;
    padding: 0.65rem;
  }
  .review-value {
    color: #f7f5ed;
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1;
  }
  .review-label {
    margin-top: 0.32rem;
    color: #7d8779;
    font-size: 0.58rem;
  }
  .handle-row,
  .event-row,
  .dependency-row {
    border-bottom: 1px solid #242823;
    padding: 0.42rem 0;
  }
  .handle-row:last-child,
  .event-row:last-child,
  .dependency-row:last-child { border-bottom: none; }
  .handle-title,
  .event-title,
  .dependency-title {
    color: #efece0;
    font-size: 0.68rem;
    font-weight: 650;
    line-height: 1.25;
  }
  .handle-path,
  .event-meta,
  .dependency-meta {
    color: #7e887a;
    font-size: 0.59rem;
    line-height: 1.28;
    margin-top: 0.18rem;
    word-break: break-all;
  }
  .inspector-grid {
    display: grid;
    grid-template-columns: 1.2fr 1fr 1fr;
    gap: 0.6rem;
    margin: 0.62rem 0 0.78rem;
  }
  .inspector-panel {
    min-height: 5.2rem;
    border: 1px solid #272d26;
    border-radius: 7px;
    background: #101410;
    padding: 0.66rem;
  }
  .inspector-label {
    color: #7e887a;
    font-size: 0.58rem;
    font-weight: 700;
    margin-bottom: 0.38rem;
  }
  .inspector-value {
    color: #f1eee2;
    font-size: 0.72rem;
    line-height: 1.35;
  }
  .stButton>button {
    border-radius: 7px !important;
    border-color: #2d342c !important;
    background: #111611 !important;
    color: #e8e5d9 !important;
    font-size: 0.74rem !important;
    font-weight: 650 !important;
  }
  .stButton>button:hover {
    border-color: rgba(40, 215, 197, 0.55) !important;
    color: #f7fffd !important;
    background: #122421 !important;
  }
  .stButton>button:disabled {
    color: #596154 !important;
    background: #0b0d0b !important;
    border-color: #20241f !important;
  }
  .stSelectbox label {
    color: #aab3a5 !important;
    font-size: 0.72rem !important;
  }
  pre {
    border-color: #272d26 !important;
    background: #0c0f0c !important;
  }
  @media (max-width: 900px) {
    .workbench-title-row { align-items: flex-start; flex-direction: column; }
    .operation-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .mode-live { grid-column: 1 / -1; min-height: 3.85rem; }
    .op-card { min-height: 3.8rem; padding: 0.6rem; }
    .op-note { font-size: 0.58rem; }
    .op-value { font-size: 0.76rem; }
    .session-rail {
      grid-template-columns: repeat(5, minmax(92px, 1fr));
      overflow-x: auto;
      padding-bottom: 0.2rem;
    }
    .session-step { min-height: 2.8rem; }
    .inspector-grid { grid-template-columns: 1fr; }
    .artifact-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .canvas-frame { height: 500px; }
  }
</style>
""",
        unsafe_allow_html=True,
    )


def _render_title_bar(
    data: dict[str, Any],
    current_label: str,
    loop_status: str,
    progress: int,
) -> None:
    stage_summary = data.get("stage_summary", {})
    artifact_counts = data.get("artifact_counts", {})
    canvas = data.get("canvas", {}) if isinstance(data.get("canvas"), dict) else {}
    canvas_summary = canvas.get("summary", {}) if isinstance(canvas.get("summary"), dict) else {}
    st.markdown(
        f"""
<div class="workbench-shell">
  <div class="workbench-title-row">
    <div>
      <div class="workbench-title">Narrascape 制作工作台</div>
      <div class="workbench-subtitle">
        以流水线阶段、导演契约、产物状态、Agent 交接与返工队列为中心的原生操作界面。
      </div>
    </div>
    <div class="workbench-meta">
      <span class="wb-chip">当前 <strong>{escape(current_label)}</strong></span>
      <span class="wb-chip">进度 <strong>{progress}%</strong></span>
      <span class="wb-chip">阶段 <strong>{int(stage_summary.get("completed") or 0)}/{int(stage_summary.get("total") or 0)}</strong></span>
      <span class="wb-chip">产物 <strong>{int(artifact_counts.get("present") or 0)}/{int(artifact_counts.get("total") or 0)}</strong></span>
      <span class="wb-chip">需关注 <strong>{int(canvas_summary.get("attention") or 0)}</strong></span>
      <span class="wb-chip">循环 <strong>{escape(zh_status(loop_status))}</strong></span>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_mode_switch() -> str:
    mode = st.radio(
        "工作模式",
        ["创作视图", "Agent 接管", "返工循环"],
        horizontal=True,
        label_visibility="collapsed",
        key="workbench_mode",
    )
    return str(mode)


def _render_operating_strip(
    data: dict[str, Any],
    current_label: str,
    loop_status: str,
    mode: str,
) -> None:
    session_value = data.get("workflow_session")
    session = session_value if isinstance(session_value, dict) else {}
    polling_value = session.get("polling")
    polling = polling_value if isinstance(polling_value, dict) else {}
    primary_value = session.get("primary_action")
    primary = primary_value if isinstance(primary_value, dict) else {}
    rework_summary = session.get("rework_queue_summary")
    queues = rework_summary if isinstance(rework_summary, dict) else {}
    watch_count = (
        len(polling.get("watching") or []) if isinstance(polling.get("watching"), list) else 0
    )
    primary_stage = str(primary.get("stage") or "")
    primary_label = zh_stage_label(primary_stage, str(primary.get("label") or "等待指派"))
    queued_actions = int(queues.get("actions") or 0)
    strip_html = f"""
<div class="operation-strip">
  <div class="mode-live">
    <div class="op-label">当前模式</div>
    <div class="op-value">{escape(mode)}</div>
    <div class="op-note">会话状态：{escape(zh_status(session.get("status")))} / 交接包：{escape(zh_status(session.get("handoff_status")))}</div>
  </div>
  <div class="op-card">
    <div class="op-label">会话</div>
    <div class="op-value">{escape(str(session.get("project_handle") or "project"))}</div>
    <div class="op-note">{escape(str(session.get("id") or ""))}</div>
  </div>
  <div class="op-card">
    <div class="op-label">画布焦点</div>
    <div class="op-value">{escape(current_label)}</div>
    <div class="op-note">阶段图谱与产物契约同步</div>
  </div>
  <div class="op-card">
    <div class="op-label">下一动作</div>
    <div class="op-value">{escape(primary_label)}</div>
    <div class="op-note">{escape(zh_source(str(primary.get("source") or "suggested")))}</div>
  </div>
  <div class="op-card {'is-warn' if queued_actions else ''}">
    <div class="op-label">轮询与回流</div>
    <div class="op-value">{watch_count} 个状态源 / {queued_actions} 个动作</div>
    <div class="op-note">返工循环：{escape(zh_status(loop_status))}</div>
  </div>
</div>
"""
    st.markdown(strip_html, unsafe_allow_html=True)


def _render_canvas(canvas: dict[str, Any]) -> None:
    nodes = [item for item in _items(canvas.get("nodes")) if isinstance(item, dict)]
    edges = [item for item in _items(canvas.get("edges")) if isinstance(item, dict)]
    summary = canvas.get("summary", {}) if isinstance(canvas.get("summary"), dict) else {}
    width = int(canvas.get("width") or 1484)
    height = int(canvas.get("height") or 540)
    html = [
        '<div class="canvas-frame">',
        '<div class="canvas-mini-toolbar">',
        '<div class="canvas-mini-title">制作画布</div>',
        '<div class="canvas-mini-stats">',
        _chip("已完成", str(summary.get("done") or 0)),
        _chip("进行中", str(summary.get("active") or 0)),
        _chip("缺失", str(summary.get("missing") or 0)),
        _chip("待处理", str(summary.get("pending") or 0)),
        "</div>",
        "</div>",
        f'<div class="canvas-surface" style="width:{width}px;height:{height}px">',
    ]
    html.extend(_lane_html(canvas))
    html.extend(_edge_html(edge) for edge in edges)
    html.extend(_node_html(node) for node in nodes)
    html.extend(["</div>", "</div>"])
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_session_lifecycle(data: dict[str, Any]) -> None:
    session_value = data.get("workflow_session")
    session = session_value if isinstance(session_value, dict) else {}
    lifecycle = [item for item in _items(session.get("lifecycle")) if isinstance(item, dict)]
    if not lifecycle:
        return
    html = ['<div class="session-rail">']
    for item in lifecycle:
        state = _css_state(str(item.get("state") or "pending"))
        phase_id = str(item.get("id") or "")
        html.append(f"""
<div class="session-step {state}">
  <div class="session-step-label">{escape(zh_lifecycle_label(phase_id))}</div>
  <div class="session-step-state">{escape(zh_lifecycle_description(phase_id, str(item.get("label") or "")))}</div>
</div>
""")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _lane_html(canvas: dict[str, Any]) -> list[str]:
    lanes = [
        (str(item.get("label") or ""), int(item.get("left") or 0))
        for item in _items(canvas.get("lanes"))
        if isinstance(item, dict)
    ]
    return [
        f'<div class="canvas-lane" style="left:{left}px">{escape(_lane_display_label(label))}</div>'
        for label, left in lanes
    ]


def _lane_display_label(label: str) -> str:
    return " / ".join(zh_lane_label(part.strip()) for part in label.split("/"))


def _edge_html(edge: dict[str, Any]) -> str:
    x1 = int(edge.get("x1") or 0)
    y1 = int(edge.get("y1") or 0)
    x2 = int(edge.get("x2") or 0)
    y2 = int(edge.get("y2") or 0)
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1) or 1
    height = abs(y2 - y1) or 1
    sx = x1 - left
    sy = y1 - top
    ex = x2 - left
    ey = y2 - top
    control = max(46, abs(ex - sx) // 2)
    mid_x = left + width // 2 - 14
    mid_y = top + height // 2 - 7
    state = _css_state(str(edge.get("state") or "idle"))
    label = escape(zh_edge_label(str(edge.get("label") or "")))
    return (
        f'<svg class="canvas-edge {state}" style="left:{left}px;top:{top}px;'
        f'width:{width}px;height:{height}px" viewBox="0 0 {width} {height}">'
        f'<path d="M {sx} {sy} C {sx + control} {sy}, {ex - control} {ey}, {ex} {ey}" />'
        "</svg>"
        f'<span class="edge-label" style="left:{mid_x}px;top:{mid_y}px">{label}</span>'
    )


def _node_html(node: dict[str, Any]) -> str:
    state = _css_state(str(node.get("state") or "pending"))
    stage_name = str(node.get("stage") or "")
    node_id = str(node.get("id") or "")
    label = escape(_node_display_label(node))
    kind = escape(zh_kind(str(node.get("kind") or "stage")))
    stage = escape(stage_name)
    status = escape(zh_status(node.get("status") or "pending"))
    approval = escape(zh_status(node.get("approval") or "unknown"))
    output_count = int(node.get("output_count") or 0)
    queued = zh_status("queued") if node.get("queued") else status
    artifact_value = node.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else {}
    rel_path = str(artifact.get("relative_path") or "")
    meta = escape(rel_path or node_id or stage)
    x = int(node.get("x") or 0)
    y = int(node.get("y") or 0)
    return f"""
<div class="canvas-node {state}" style="left:{x}px;top:{y}px">
  <div class="node-topline">
    <span class="node-kind">{kind}</span>
    <span class="node-status-dot"></span>
  </div>
  <div class="node-title">{label}</div>
  <div class="node-meta">{meta}</div>
  <div class="node-footer">
    <span>{escape(queued)}</span>
    <span>{output_count} 个文件 / {approval}</span>
  </div>
</div>
"""


def _node_display_label(node: dict[str, Any]) -> str:
    node_id = str(node.get("id") or "")
    if node_id.startswith("queue:"):
        artifact_value = node.get("artifact")
        artifact = artifact_value if isinstance(artifact_value, dict) else {}
        return zh_artifact_label(str(artifact.get("id") or ""), str(node.get("label") or node_id))
    stage_name = str(node.get("stage") or "")
    return zh_stage_label(stage_name, str(node.get("label") or stage_name or "Node"))


def _render_agent_queue(
    ctx: DashboardPageContext,
    data: dict[str, Any],
    project_dir: Path,
) -> None:
    st.markdown('<div class="panel-title">Agent 队列</div>', unsafe_allow_html=True)
    queue_items = [item for item in _items(data.get("agent_queue")) if isinstance(item, dict)]
    if not queue_items:
        st.markdown(
            "<div style='color:#7e887a;font-size:0.74rem'>暂无排队动作。可刷新状态或交接包。</div>",
            unsafe_allow_html=True,
        )

    for index, item in enumerate(queue_items):
        stage = str(item.get("stage") or "")
        if not stage:
            continue
        label = zh_stage_label(
            stage, str(item.get("label") or stage_label(stage, ctx.stage_meta.get(stage, {})))
        )
        action = str(item.get("action") or "build")
        primary = str(item.get("primary") or "false") == "true"
        st.markdown(
            f"""
<div class="queue-item {'primary' if primary else ''}">
  <div class="queue-label">{index + 1}. {escape(label)}</div>
  <div class="queue-reason">{escape(zh_reason(str(item.get("reason") or "")))}</div>
  <div class="queue-meta">
    <span>{escape(zh_source(str(item.get("source") or "queue")))}</span>
    <span>{escape(zh_status(item.get("status") or "pending"))}</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        button_label = f"运行 {label}" if action != "status" else "查看状态"
        if action != "status" and st.button(
            button_label,
            key=f"workbench_queue_{action}_{stage}_{index}",
            use_container_width=True,
            disabled=st.session_state.running_stage is not None,
        ):
            _run_stage(ctx, project_dir, stage)
        if stage != "assistant_handoff":
            approve_disabled = st.session_state.running_stage is not None
            if st.button(
                f"批准 {label}",
                key=f"workbench_approve_{stage}_{index}",
                use_container_width=True,
                disabled=approve_disabled,
            ):
                _approve_stage(ctx, project_dir, stage)
        command = str(item.get("command") or "")
        if command:
            st.code(command, language="bash")

    if st.button(
        "刷新交接包",
        key="workbench_refresh_assistant_handoff",
        use_container_width=True,
        disabled=st.session_state.running_stage is not None,
    ):
        _run_stage(ctx, project_dir, "assistant_handoff")


def _render_session_handles(data: dict[str, Any]) -> None:
    session_value = data.get("workflow_session")
    session = session_value if isinstance(session_value, dict) else {}
    polling_value = session.get("polling")
    polling = polling_value if isinstance(polling_value, dict) else {}
    handles = [item for item in _items(session.get("result_handles")) if isinstance(item, dict)]
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">制片会话</div>', unsafe_allow_html=True
    )
    st.markdown(
        f"""
<div class="queue-item primary">
  <div class="queue-label">{escape(str(session.get("id") or "session"))}</div>
  <div class="queue-reason">{escape(zh_status(session.get("status") or "idle"))}</div>
  <div class="queue-meta">
    <span>{escape(str(session.get("project_handle") or ""))}</span>
    <span>{escape(zh_status(session.get("handoff_status") or "missing"))}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    status_command = str(polling.get("status_command") or "")
    if status_command:
        st.code(status_command, language="bash")
    for handle in handles:
        handle_label = zh_handle_label(str(handle.get("label") or ""))
        st.markdown(
            f"""
<div class="handle-row">
  <div class="handle-title">{escape(handle_label)}</div>
  <div class="handle-path">{escape(zh_status(handle.get("status") or ""))} / {escape(str(handle.get("path") or ""))}</div>
</div>
""",
            unsafe_allow_html=True,
        )
    _render_takeover_protocol(session)
    _render_required_reading(session)
    _render_quality_gates(data)


def _render_takeover_protocol(session: dict[str, Any]) -> None:
    protocol = [item for item in _items(session.get("takeover_protocol")) if isinstance(item, dict)]
    if not protocol:
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">接管流程</div>',
        unsafe_allow_html=True,
    )
    for item in protocol:
        command = str(item.get("command") or "")
        protocol_id = str(item.get("id") or "")
        st.markdown(
            f"""
<div class="handle-row">
  <div class="handle-title">{escape(zh_protocol_label(protocol_id, str(item.get("label") or "")))}</div>
  <div class="handle-path">{escape(zh_status(item.get("state") or ""))}</div>
</div>
""",
            unsafe_allow_html=True,
        )
        if command and len(command) < 260:
            st.code(command, language="bash" if command.startswith("narrascape") else "text")


def _render_required_reading(session: dict[str, Any]) -> None:
    rows = [item for item in _items(session.get("required_reading")) if isinstance(item, dict)]
    if not rows:
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">必读上下文</div>',
        unsafe_allow_html=True,
    )
    for item in rows[:6]:
        st.markdown(
            f"""
<div class="handle-row">
  <div class="handle-title">{escape(str(item.get("path") or ""))}</div>
  <div class="handle-path">{escape(zh_required_reason(str(item.get("reason") or "")))}</div>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_quality_gates(data: dict[str, Any]) -> None:
    gates = [item for item in _items(data.get("quality_gates")) if isinstance(item, dict)]
    if not gates:
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">质量门</div>',
        unsafe_allow_html=True,
    )
    for item in gates[:7]:
        gate_id = str(item.get("id") or item.get("name") or "")
        st.markdown(
            f"""
<div class="handle-row">
  <div class="handle-title">{escape(zh_quality_gate_label(gate_id))}</div>
  <div class="handle-path">{escape(zh_status(item.get("status")))} / {escape(_display_value(item.get("required")))}</div>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_node_inspector(
    ctx: DashboardPageContext,
    data: dict[str, Any],
    project_dir: Path,
) -> None:
    canvas_value = data.get("canvas")
    canvas = canvas_value if isinstance(canvas_value, dict) else {}
    nodes = [item for item in _items(canvas.get("nodes")) if isinstance(item, dict)]
    inspector_value = data.get("node_inspector")
    inspector = inspector_value if isinstance(inspector_value, dict) else {}
    if not nodes or not inspector:
        return
    default_id = _default_focus_node_id(data, nodes)
    node_options = [str(node.get("id") or "") for node in nodes]
    if default_id not in node_options:
        default_id = node_options[0]
    selected_id = st.selectbox(
        "聚焦阶段",
        node_options,
        index=node_options.index(default_id),
        format_func=lambda value: _node_option_label(value, inspector),
        key="workbench_focus_node_id",
    )
    selected_value = inspector.get(selected_id)
    selected = selected_value if isinstance(selected_value, dict) else {}
    if not selected:
        return
    _render_selected_node_summary(selected)
    _render_selected_node_actions(ctx, project_dir, selected)


def _default_focus_node_id(data: dict[str, Any], nodes: list[dict[str, Any]]) -> str:
    session_value = data.get("workflow_session")
    session = session_value if isinstance(session_value, dict) else {}
    focus_id = str(session.get("focus_node_id") or "")
    if focus_id:
        return focus_id
    canvas_value = data.get("canvas")
    canvas = canvas_value if isinstance(canvas_value, dict) else {}
    focus_value = canvas.get("focus")
    focus = focus_value if isinstance(focus_value, dict) else {}
    if focus.get("id"):
        return str(focus.get("id"))
    return str(nodes[0].get("id") or "")


def _node_option_label(value: str, inspector: dict[Any, Any]) -> str:
    item_value = inspector.get(value)
    item = item_value if isinstance(item_value, dict) else {}
    stage = str(item.get("stage") or value)
    label = zh_stage_label(stage, str(item.get("label") or value))
    state = zh_status(item.get("state") or "pending")
    return f"{label} / {state}"


def _render_selected_node_summary(selected: dict[str, Any]) -> None:
    artifact_value = selected.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else {}
    upstream = _stage_sequence_labels(selected.get("upstream_ids"), selected.get("upstream"))
    downstream = _stage_sequence_labels(selected.get("downstream_ids"), selected.get("downstream"))
    blocking = _blocking_text(str(selected.get("blocking_reason") or "Ready for inspection."))
    artifact_path = str(artifact.get("relative_path") or artifact.get("path") or "")
    stage_doc = str(selected.get("stage_doc") or "none")
    approval = zh_status(selected.get("approval") or "unknown")
    stage_name = str(selected.get("stage") or "")
    selected_label = zh_stage_label(stage_name, str(selected.get("label") or ""))
    st.markdown(
        f"""
<div class="inspector-grid">
  <div class="inspector-panel">
    <div class="inspector-label">阶段</div>
    <div class="inspector-value">{escape(selected_label)}</div>
    <div class="dependency-meta">{escape(str(selected.get("intent") or ""))}</div>
  </div>
  <div class="inspector-panel">
    <div class="inspector-label">契约</div>
    <div class="inspector-value">{escape(zh_status(selected.get("stage_status") or selected.get("status") or ""))} / {escape(approval)}</div>
    <div class="dependency-meta">{escape(stage_doc)}</div>
  </div>
  <div class="inspector-panel">
    <div class="inspector-label">阻塞状态</div>
    <div class="inspector-value">{escape(blocking)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    dep_html = ['<div class="inspector-grid">']
    dep_html.append(_dependency_panel("上游", upstream))
    dep_html.append(_dependency_panel("下游", downstream))
    dep_html.append(
        _dependency_panel(
            "产物",
            [
                zh_status(artifact.get("status") or selected.get("status") or ""),
                artifact_path or "none",
            ],
        )
    )
    dep_html.append("</div>")
    st.markdown("".join(dep_html), unsafe_allow_html=True)
    contract_html = ['<div class="inspector-grid">']
    contract_html.append(
        _dependency_panel(
            "依赖",
            [zh_stage_label(str(item)) for item in _items(selected.get("depends_on"))],
        )
    )
    contract_html.append(
        _dependency_panel(
            "输出",
            [str(item) for item in _items(selected.get("outputs"))],
        )
    )
    contract_html.append(
        _dependency_panel(
            "队列",
            _queue_panel_rows(selected),
        )
    )
    contract_html.append("</div>")
    st.markdown("".join(contract_html), unsafe_allow_html=True)
    action_value = selected.get("handoff_next_action")
    action = action_value if isinstance(action_value, dict) else {}
    if action:
        st.code(str(action.get("command") or ""), language="bash")
    if bool(selected.get("production_boundary")):
        st.caption("供应商边界：生产调用前说明 provider、model、stage、reason，以及 sample/batch。")
    if artifact and artifact.get("exists") and str(artifact.get("kind")) == "text":
        _render_artifact_preview(artifact)


def _queue_panel_rows(selected: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in _items(selected.get("queue_items")):
        if not isinstance(item, dict):
            continue
        queue_id = str(item.get("id") or "")
        rows.append(
            f"{zh_artifact_label(queue_id, queue_id)}：{item.get('action_count') or 0} 个动作"
        )
    return rows


def _dependency_panel(label: str, values: list[str]) -> str:
    rows = values or ["无"]
    body = "".join(f"""
<div class="dependency-row">
  <div class="dependency-title">{escape(value)}</div>
</div>
""" for value in rows[:5])
    return f"""
<div class="inspector-panel">
  <div class="inspector-label">{escape(label)}</div>
  {body}
</div>
"""


def _stage_sequence_labels(ids_value: Any, fallback_value: Any) -> list[str]:
    ids = [str(item) for item in _items(ids_value)]
    if ids:
        return [
            (
                zh_artifact_label(item.removeprefix("queue:"), item)
                if item.startswith("queue:")
                else zh_stage_label(item, item)
            )
            for item in ids
        ]
    return [str(item) for item in _items(fallback_value)]


def _blocking_text(value: str) -> str:
    if not value or value == "Ready for inspection.":
        return "可检查。"
    if value == "Current pipeline cursor is here.":
        return "流水线当前指针停在这里。"
    if value == "Assistant handoff selected this stage for the next run.":
        return "Agent 交接包已选择该阶段作为下一次运行。"
    if value == "Rework queue has concrete work for this stage.":
        return "返工队列中已有该阶段的具体动作。"
    if value == "Supervisor or queue selected this stage for the next run.":
        return "影片监督或队列已选择该阶段作为下一次运行。"
    if value.startswith("Approval gate is "):
        return (
            f"审批门状态为 {zh_status(value.removeprefix('Approval gate is ').removesuffix('.'))}。"
        )
    if value.endswith(" has not been written yet."):
        return f"产物尚未写入：{value.removesuffix(' has not been written yet.')}。"
    if value.startswith("Artifact status is "):
        return (
            f"产物状态为 {zh_status(value.removeprefix('Artifact status is ').removesuffix('.'))}。"
        )
    if value == "Stage failed in pipeline state.":
        return "流水线状态记录该阶段失败。"
    if value.startswith("Provider boundary:"):
        return "供应商边界：生产调用前必须声明 provider、model、stage、reason 和 sample/batch。"
    return value


def _render_selected_node_actions(
    ctx: DashboardPageContext,
    project_dir: Path,
    selected: dict[str, Any],
) -> None:
    actions = [item for item in _items(selected.get("actions")) if isinstance(item, dict)]
    run_action = next((item for item in actions if item.get("mode") == "build"), {})
    approve_action = next((item for item in actions if item.get("mode") == "approve"), {})
    stage = str(selected.get("stage") or "")
    label = zh_stage_label(stage, str(selected.get("label") or stage))
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if run_action and st.button(
            f"运行 {label}",
            key=f"workbench_focus_run_{stage}",
            use_container_width=True,
            disabled=st.session_state.running_stage is not None,
        ):
            _run_stage(ctx, project_dir, stage)
    with col2:
        if approve_action and st.button(
            f"批准 {label}",
            key=f"workbench_focus_approve_{stage}",
            use_container_width=True,
            disabled=st.session_state.running_stage is not None,
        ):
            _approve_stage(ctx, project_dir, stage)
    with col3:
        if st.button(
            "刷新状态",
            key=f"workbench_focus_poll_{stage}",
            use_container_width=True,
            disabled=st.session_state.running_stage is not None,
        ):
            st.rerun()


def _render_artifact_drawer(data: dict[str, Any]) -> None:
    artifacts = [item for item in _items(data.get("artifacts")) if isinstance(item, dict)]
    st.markdown('<div class="panel-title">产物抽屉</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="artifact-strip">'
        + "".join(_artifact_tile_html(item) for item in artifacts)
        + "</div>",
        unsafe_allow_html=True,
    )

    focus = _focus_artifact(data)
    if focus:
        _render_artifact_preview(focus)


def _artifact_tile_html(item: dict[str, Any]) -> str:
    state = _artifact_state(item)
    artifact_id = str(item.get("id") or "")
    name = escape(zh_artifact_label(artifact_id, str(item.get("label") or "Artifact")))
    status = escape(zh_status(item.get("status") or "missing"))
    path = escape(str(item.get("relative_path") or item.get("file") or ""))
    modified = _fmt_mtime(float(item.get("modified") or 0.0))
    caption = modified or "未写入"
    return f"""
<div class="artifact-tile {state}">
  <div class="artifact-name">{name}</div>
  <div class="artifact-path">{path}</div>
  <div class="artifact-status">{status} / {escape(caption)}</div>
</div>
"""


def _focus_artifact(data: dict[str, Any]) -> dict[str, Any] | None:
    canvas_value = data.get("canvas")
    canvas = canvas_value if isinstance(canvas_value, dict) else {}
    focus_value = canvas.get("focus")
    focus = focus_value if isinstance(focus_value, dict) else {}
    artifact_value = focus.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else {}
    if artifact and artifact.get("exists"):
        return artifact
    for item in _items(data.get("artifacts")):
        if isinstance(item, dict) and item.get("exists"):
            return item
    return None


def _render_artifact_preview(item: dict[str, Any]) -> None:
    label = zh_artifact_label(str(item.get("id") or ""), str(item.get("label") or "Artifact"))
    path = Path(str(item.get("path") or ""))
    if not path.exists() or str(item.get("kind")) != "text":
        return
    st.caption(str(item.get("relative_path") or path.name))
    try:
        st.code(path.read_text(encoding="utf-8", errors="replace")[:2200], language="yaml")
    except OSError as exc:
        st.error(f"{label}: {exc}")


def _render_rework_console(rework_loop: dict[str, Any]) -> None:
    st.markdown('<div class="panel-title">审查循环</div>', unsafe_allow_html=True)
    metrics = [
        ("QA 错误", rework_loop.get("qa_error_count", 0)),
        ("QA 警告", rework_loop.get("qa_warning_count", 0)),
        ("动作", rework_loop.get("action_count", 0)),
        ("已执行", rework_loop.get("executed_count", 0)),
        ("创意建议", rework_loop.get("creative_recommendation_count", 0)),
        ("视觉发现", rework_loop.get("visual_finding_count", 0)),
    ]
    st.markdown(
        '<div class="review-grid">' + "".join(f"""
<div class="review-metric">
  <div class="review-value">{escape(str(value))}</div>
  <div class="review-label">{escape(label)}</div>
</div>
""" for label, value in metrics) + "</div>",
        unsafe_allow_html=True,
    )
    next_stages = rework_loop.get("next_stages") or []
    if next_stages:
        st.markdown(
            "<div style='color:#7e887a;font-size:0.62rem;margin-top:0.9rem'>下一阶段</div>",
            unsafe_allow_html=True,
        )
        st.code(" -> ".join(zh_stage_label(str(item)) for item in next_stages), language="text")


def _render_rework_queues(data: dict[str, Any]) -> None:
    queues = [item for item in _items(data.get("rework_queues")) if isinstance(item, dict)]
    if not queues:
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">返工队列</div>',
        unsafe_allow_html=True,
    )
    for item in queues:
        segment_ids = ", ".join(str(value) for value in _items(item.get("segment_ids")))
        meta = (
            f"{zh_status(item.get('status') or 'missing')} / "
            f"{item.get('action_count') or 0} 个动作 / "
            f"{zh_stage_label(str(item.get('target_stage') or ''))}"
        )
        if segment_ids:
            meta = f"{meta} / 段落 {segment_ids}"
        queue_id = str(item.get("id") or "")
        st.markdown(
            f"""
<div class="event-row">
  <div class="event-title">{escape(zh_artifact_label(queue_id, str(item.get("label") or "")))}</div>
  <div class="event-meta">{escape(meta)}</div>
  <div class="event-meta">{escape(str(item.get("relative_path") or item.get("path") or ""))}</div>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_artifact_events(data: dict[str, Any]) -> None:
    events = [item for item in _items(data.get("artifact_events")) if isinstance(item, dict)]
    if not events:
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">产物事件</div>',
        unsafe_allow_html=True,
    )
    for event in events[:6]:
        modified = _fmt_mtime(float(event.get("modified") or 0.0)) or "未写入"
        artifact_label = zh_artifact_label(
            str(event.get("stage") or ""), str(event.get("artifact") or "")
        )
        st.markdown(
            f"""
<div class="event-row">
  <div class="event-title">{escape(artifact_label)}</div>
  <div class="event-meta">{escape(zh_status(event.get("status") or ""))} / {escape(zh_status(event.get("stage_status") or ""))} / {escape(modified)}</div>
  <div class="event-meta">{escape(str(event.get("path") or ""))}</div>
</div>
""",
            unsafe_allow_html=True,
        )


def _run_stage(ctx: DashboardPageContext, project_dir: Path, stage: str) -> None:
    ctx.start_command(
        f"workbench:{stage}",
        build_stage_command(sys.executable, project_dir, stage, approve=True),
    )


def _approve_stage(ctx: DashboardPageContext, project_dir: Path, stage: str) -> None:
    ctx.start_command(
        f"workbench:approve:{stage}",
        approve_stage_command(sys.executable, project_dir, stage),
    )


def _render_command_log() -> None:
    running_stage = str(st.session_state.running_stage or "")
    if not running_stage.startswith("workbench:"):
        return
    st.markdown(
        '<div class="panel-title" style="margin-top:1rem">任务日志</div>', unsafe_allow_html=True
    )
    log_queue: queue.Queue[str] | None = st.session_state.log_queue
    if log_queue is not None:
        new_lines: list[str] = []
        while not log_queue.empty():
            try:
                new_lines.append(log_queue.get_nowait())
            except queue.Empty:
                break
        if new_lines:
            st.session_state.logs.extend(new_lines)
    if st.session_state.logs:
        st.code("\n".join(st.session_state.logs[-220:]), language=None)
    else:
        st.markdown(
            "<div style='color:#7e887a;font-size:0.74rem'>暂无输出...</div>",
            unsafe_allow_html=True,
        )
    if st.session_state.build_process is None:
        st.session_state.running_stage = None
        st.session_state.log_queue = None
        st.rerun()
    else:
        time.sleep(0.5)
        st.rerun()


def _artifact_state(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "missing")
    if status in {
        "blocked",
        "failed",
        "has_errors",
        "invalid",
        "missing",
        "missing_assets",
        "needs_attention",
        "needs_rework",
        "pending_supervisor",
    }:
        return "attention"
    if item.get("exists"):
        return "done"
    return "pending"


def _css_state(value: str) -> str:
    if value in {"done", "active", "attention", "missing"}:
        return value
    return "pending"


def _chip(label: str, value: str) -> str:
    return f'<span class="wb-chip">{escape(label)} <strong>{escape(value)}</strong></span>'


def _fmt_mtime(value: float) -> str:
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else []
