"""Narrascape — Modern video pipeline dashboard."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.application import JobService
from narrascape.dashboard_i18n import STAGE_LABELS_ZH
from narrascape.dashboard_pages.ai_director import render_ai_director_page
from narrascape.dashboard_pages.context import DashboardPageContext
from narrascape.dashboard_pages.home import render_home_page
from narrascape.dashboard_pages.pipeline import render_pipeline_page
from narrascape.dashboard_pages.resources import render_resources_page
from narrascape.dashboard_pages.system import render_system_page
from narrascape.dashboard_pages.timeline import render_timeline_page
from narrascape.dashboard_pages.workbench import render_workbench_page

# ═══════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Narrascape",
    page_icon="",
    layout="wide",
    initial_sidebar_state="auto",
)

# ═══════════════════════════════════════════════════════════════
#  Theme — minimal, modern, low-density
# ═══════════════════════════════════════════════════════════════
_CSS = """
<style>
  * { letter-spacing: 0 !important; }
  .main { background-color: #0a0a0a; }
  .stApp { background-color: #0a0a0a; }

  h1 { font-weight: 600; color: #fafafa; font-size: 1.4em; border-bottom: 1px solid #262626; padding-bottom: 0.5em; margin-bottom: 1em; }
  h2 { font-weight: 500; color: #e5e5e5; font-size: 1.1em; margin-top: 2em; margin-bottom: 0.8em; }
  h3 { font-weight: 500; color: #d4d4d4; font-size: 0.95em; margin-top: 1.5em; }

  .stButton>button {
    background: #171717;
    color: #a3a3a3;
    border: 1px solid #262626;
    border-radius: 8px;
    font-weight: 500;
    padding: 0.5em 1.2em;
    transition: all 0.2s;
  }
  .stButton>button:hover {
    background: #262626;
    color: #fafafa;
    border-color: #404040;
  }
  .stButton>button:disabled {
    background: #0a0a0a;
    color: #404040;
    border-color: #1a1a1a;
  }

  .stSelectbox>div>div>div {
    background: #141414;
    color: #e5e5e5;
    border: 1px solid #262626;
    border-radius: 8px;
  }
  .stTextInput>div>div>input, .stTextArea>div>div>textarea {
    background: #141414;
    color: #e5e5e5;
    border: 1px solid #262626;
    border-radius: 8px;
  }
  .stSlider>div>div>div { color: #3b82f6; }

  .card {
    background: #141414;
    border: 1px solid #262626;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 16px;
  }
  .card-sm {
    background: #141414;
    border: 1px solid #262626;
    border-radius: 10px;
    padding: 16px;
  }
  .card:hover, .card-sm:hover { border-color: #333; }

  .stat-num {
    font-size: 2em;
    font-weight: 700;
    color: #fafafa;
    line-height: 1;
  }
  .stat-label {
    font-size: 0.65em;
    color: #525252;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 6px;
  }

  .progress-track {
    height: 3px;
    background: #262626;
    border-radius: 2px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: #3b82f6;
    border-radius: 2px;
    transition: width 0.5s ease;
  }

  .stage-timeline {
    display: flex;
    align-items: center;
    gap: 2px;
    overflow-x: auto;
    padding: 6px 0;
  }
  .stage-node {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 6px;
    white-space: nowrap;
    font-size: 0.75em;
    color: #525252;
    border: 1px solid transparent;
    transition: all 0.15s;
    cursor: pointer;
  }
  .stage-node:hover {
    background: #171717;
    border-color: #262626;
  }
  .stage-node.done { color: #22c55e; }
  .stage-node.current { color: #3b82f6; background: rgba(59,130,246,0.06); border-color: rgba(59,130,246,0.15); }
  .stage-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #333;
    flex-shrink: 0;
  }
  .stage-dot.done { background: #22c55e; }
  .stage-dot.current { background: #3b82f6; }

  .tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7em;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .tag-done { background: rgba(34,197,94,0.1); color: #22c55e; border: 1px solid rgba(34,197,94,0.2); }
  .tag-pending { background: rgba(148,163,184,0.08); color: #64748b; border: 1px solid rgba(148,163,184,0.15); }
  .tag-warn { background: rgba(245,158,11,0.1); color: #f59e0b; border: 1px solid rgba(245,158,11,0.2); }

  .section-label {
    font-size: 0.65em;
    color: #525252;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.8em;
  }

  .file-row {
    font-family: monospace;
    font-size: 0.8em;
    color: #737373;
    padding: 4px 0;
    border-bottom: 1px solid #1a1a1a;
  }
  .file-row:last-child { border-bottom: none; }

  section[data-testid="stSidebar"] {
    background: #0a0a0a !important;
    border-right: 1px solid #171717 !important;
  }
  span[data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
  }
  button[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"]::before {
    content: "\\2630";
    color: rgba(250, 250, 250, 0.72);
    font-size: 18px;
    line-height: 18px;
  }
  button[data-testid="stBaseButton-headerNoPadding"] span[data-testid="stIconMaterial"]::before {
    content: "\\2039";
    color: rgba(250, 250, 250, 0.72);
    font-size: 22px;
    line-height: 18px;
  }

  pre { background: #141414 !important; border: 1px solid #262626 !important; border-radius: 6px !important; }
  code { background: #141414 !important; color: #60a5fa !important; padding: 2px 6px; border-radius: 4px; }

  .stDataFrame { border: 1px solid #262626 !important; border-radius: 8px !important; }

  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: #0a0a0a; }
  ::-webkit-scrollbar-thumb { background: #262626; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #404040; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════
def _init_state() -> None:
    defaults: dict[str, Any] = {
        "project_dir": None,
        "fixed_project_dir": None,
        "config": None,
        "logs": [],
        "running_stage": None,
        "build_process": None,
        "log_queue": None,
        "active_job_id": None,
        "pipeline_stage": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ═══════════════════════════════════════════════════════════════
# Stage metadata
# ═══════════════════════════════════════════════════════════════
STAGE_META = {
    "research": {
        "label": "Research",
        "title": "Research",
        "description": "Deep-dive historical and cultural research. Produces a structured report with facts, dates, quotes, and visual references.",
        "inputs": [],
        "outputs": ["research/report.md"],
    },
    "write": {
        "label": "Write",
        "title": "Write Script",
        "description": "Transforms research into a segmented narration script with shot types, emotion tags, and pacing hints.",
        "inputs": ["research/report.md"],
        "outputs": ["scripts/script.yaml"],
    },
    "humanize": {
        "label": "Humanize",
        "title": "Humanize",
        "description": "De-AI-fies the script: removes AI-isms, adds natural rhythm, adjusts sentence length for TTS.",
        "inputs": ["scripts/script.yaml"],
        "outputs": ["scripts/script.yaml"],
    },
    "pre_production": {
        "label": "Pre-Production",
        "title": "Pre-Production",
        "description": "Creates the visual world: style anchor, character refs, environment refs, and storyboard.",
        "inputs": ["scripts/script.yaml"],
        "outputs": [
            "preproduction/style_anchor.webp",
            "preproduction/characters/",
            "preproduction/storyboard.yaml",
        ],
    },
    "design": {
        "label": "Design",
        "title": "Shot Design",
        "description": "AI Director analyses every segment, derives shot type, movement, and size. Outputs prompts with 3-layer creative model.",
        "inputs": ["scripts/script.yaml", "preproduction/"],
        "outputs": ["image_prompts.yaml", "image_map.yaml"],
    },
    "generate_images": {
        "label": "Images",
        "title": "Generate Images",
        "description": "Seedream with multi-reference. Generates images per segment using AI Director prompts.",
        "inputs": ["image_prompts.yaml", "preproduction/style_anchor.webp"],
        "outputs": ["assets/images/"],
    },
    "generate_video": {
        "label": "Video",
        "title": "Generate Video",
        "description": "Seedance for video generation from keyframes and prompts with multi-modal reference.",
        "inputs": ["image_prompts.yaml"],
        "outputs": ["assets/videos/"],
    },
    "generate_tts": {
        "label": "TTS",
        "title": "Generate TTS",
        "description": "MiniMax TTS narration audio. Respects pronunciation, speed, and pause markers.",
        "inputs": ["scripts/script.yaml"],
        "outputs": ["assets/tts/"],
    },
    "film_timeline": {
        "label": "Timeline",
        "title": "Film Timeline",
        "description": "Builds the canonical film_timeline.yaml from generated video, source footage, image fallback, narration, music, subtitles, and director metadata.",
        "inputs": ["design_report.yaml", "image_map.yaml", "assets/videos/", "assets/tts/"],
        "outputs": ["film_timeline.yaml"],
    },
    "remotion_preview": {
        "label": "Preview",
        "title": "Remotion Preview",
        "description": "Exports a Remotion handoff project from film_timeline.yaml for visual timeline inspection and future web rendering.",
        "inputs": ["film_timeline.yaml"],
        "outputs": ["pipeline/remotion_preview.yaml", "pipeline/remotion_preview/"],
    },
    "film_assemble": {
        "label": "Assemble",
        "title": "Film Assemble",
        "description": "Renders the film timeline visual track with FFmpeg, respecting generated video, source footage, image fallback, gaps, and ending cards.",
        "inputs": ["film_timeline.yaml"],
        "outputs": ["pipeline/film_assembled.mp4"],
    },
    "generate_music": {
        "label": "BGM",
        "title": "Generate BGM",
        "description": "AI Director designs music zones with tempo, mood, and instrumentation.",
        "inputs": ["scripts/script.yaml"],
        "outputs": ["assets/music/"],
    },
    "remix_audio": {
        "label": "Remix",
        "title": "Audio Remix",
        "description": "Concatenates TTS with gap insertion, mixes BGM with sidechain ducking and loudnorm.",
        "inputs": ["assets/tts/", "assets/music/"],
        "outputs": ["mixed_audio.mp3"],
    },
    "kenburns": {
        "label": "Motion",
        "title": "Ken Burns Motion",
        "description": "3-tier engine (Crop / ZoomPan / PIL) with auto edge detection. Renders in parallel.",
        "inputs": ["assets/images/"],
        "outputs": ["assets/videos/"],
    },
    "concat": {
        "label": "Concat",
        "title": "Concatenate",
        "description": "Stitches all video segments into a single timeline with crossfades.",
        "inputs": ["assets/videos/"],
        "outputs": ["final_video.mp4"],
    },
    "audio": {
        "label": "Audio Final",
        "title": "Audio Final",
        "description": "Muxes final video with remixed audio. Ensures sync and applies final loudnorm.",
        "inputs": ["final_video.mp4", "mixed_audio.mp3"],
        "outputs": ["output/video_with_audio.mp4"],
    },
    "subtitles": {
        "label": "Subtitles",
        "title": "Burn Subtitles",
        "description": "Generates and burns SRT subtitles with ASS-style positioning and background boxes.",
        "inputs": ["output/video_with_audio.mp4", "scripts/script.yaml"],
        "outputs": ["output/final.mp4"],
    },
}

for _stage_name, _stage_label in STAGE_LABELS_ZH.items():
    _metadata = STAGE_META.setdefault(_stage_name, {"inputs": [], "outputs": []})
    _metadata["label"] = _stage_label
    _metadata["title"] = _stage_label
    _metadata["description"] = (
        f"Narrascape 的{_stage_label}阶段；详细输入、输出和约束以流水线产物为准。"
    )

# ═══════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        "<div style='font-size:1.2em;font-weight:700;color:#fafafa;letter-spacing:0.04em'>Narrascape</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:0.6em;color:#404040;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:2em'>Pipeline v0.1</div>",
        unsafe_allow_html=True,
    )

    query_project = st.query_params.get("project") or os.environ.get("NARRASCAPE_DASHBOARD_PROJECT")
    if isinstance(query_project, list):
        query_project = query_project[0] if query_project else None
    if query_project and st.session_state.fixed_project_dir is None:
        st.session_state.fixed_project_dir = Path(str(query_project)).expanduser().resolve()

    fixed_project = st.session_state.fixed_project_dir
    if fixed_project:
        st.session_state.project_dir = fixed_project
        try:
            from narrascape.config import load_config

            st.session_state.config = load_config(st.session_state.project_dir)
        except Exception as e:
            st.error(f"Config: {e}")
            st.session_state.config = None
    else:
        workspace = Path.cwd()
        candidates = [d for d in workspace.iterdir() if d.is_dir() and (d / "config.yaml").exists()]
        if (workspace / "config.yaml").exists():
            candidates.insert(0, workspace)
        project_names = [p.name for p in candidates] or ["（没有项目）"]
        selected = st.selectbox("项目", project_names, label_visibility="collapsed")
        if selected != "（没有项目）":
            selected_index = project_names.index(selected)
            st.session_state.project_dir = candidates[selected_index]
            try:
                from narrascape.config import load_config

                st.session_state.config = load_config(st.session_state.project_dir)
            except Exception as e:
                st.error(f"Config: {e}")
                st.session_state.config = None
        else:
            st.session_state.project_dir = None
            st.session_state.config = None

    st.markdown("<div style='height:1.5em'></div>", unsafe_allow_html=True)

    # Navigation — 5 main items
    NAV = [
        ("总览", "home"),
        ("流水线", "pipeline"),
        ("制作工作台", "workbench"),
        ("时间线", "timeline"),
        ("资源", "resources"),
        ("AI 导演", "ai_director"),
        ("系统", "system"),
    ]
    nav_labels = [n[0] for n in NAV]
    nav_keys = [n[1] for n in NAV]
    selected_nav = st.selectbox(
        "导航",
        range(len(nav_labels)),
        format_func=lambda i: nav_labels[i],
        label_visibility="collapsed",
    )
    page = nav_keys[selected_nav]

    st.markdown("<div style='height:2em'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:0.6em;color:#333'>按 R 刷新</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════
def _fmt_size(path: Path) -> str:
    try:
        size = path.stat().st_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    except Exception:
        return "?"


def _fmt_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def _get_pipeline_dir() -> Path | None:
    if not st.session_state.project_dir:
        return None
    project_dir = Path(st.session_state.project_dir)
    cfg = st.session_state.config
    name = cfg.project.name if cfg else project_dir.name
    return project_dir / "pipeline" / name


def _get_stage_dashboard() -> dict[str, Any]:
    project_dir = st.session_state.project_dir
    pipeline_dir = _get_pipeline_dir()
    if project_dir is None or pipeline_dir is None:
        return {
            "total": 0,
            "completed": 0,
            "progress": 0,
            "counts": {},
            "stages": [],
            "stage_by_name": {},
            "current_stage": None,
        }
    from narrascape.dashboard_data import load_stage_dashboard

    return load_stage_dashboard(Path(project_dir), pipeline_dir)


def _dashboard_page_context() -> DashboardPageContext:
    return DashboardPageContext(
        project_dir=Path(st.session_state.project_dir) if st.session_state.project_dir else None,
        config=st.session_state.config,
        stage_meta=STAGE_META,
        get_pipeline_dir=_get_pipeline_dir,
        get_stage_dashboard=_get_stage_dashboard,
        start_command=_start_dashboard_command,
        fmt_size=_fmt_size,
        fmt_bytes=_fmt_bytes,
    )


def _start_dashboard_command(key: str, cmd: list[str]) -> None:
    project_dir = Path(st.session_state.project_dir or Path.cwd())
    service = JobService(cmd[0], project_dir)
    job = service.submit_command(cmd, stage=key)
    st.session_state.running_stage = key
    st.session_state.logs = []
    st.session_state.log_queue = None
    st.session_state.active_job_id = job.id
    st.session_state.build_process = job
    st.rerun()


def _sync_persistent_job() -> None:
    project_value = st.session_state.project_dir
    job_id = st.session_state.active_job_id
    if project_value is None or not job_id:
        return
    service = JobService(sys.executable, Path(project_value))
    try:
        job = service.get_job(str(job_id))
        st.session_state.logs = service.read_job_log(str(job_id), tail_lines=500).splitlines()
    except Exception as exc:
        st.session_state.logs = [f"无法读取作业状态：{exc}"]
        st.session_state.active_job_id = None
        st.session_state.build_process = None
        st.session_state.running_stage = None
        return
    if job.status in {"queued", "running", "cancelling"}:
        st.session_state.build_process = job
        return
    st.session_state.build_process = None
    st.session_state.active_job_id = None


_sync_persistent_job()


# ═══════════════════════════════════════════════════════════════
# Page router
# ═══════════════════════════════════════════════════════════════
if page == "home":
    render_home_page(_dashboard_page_context())


elif page == "pipeline":
    render_pipeline_page(_dashboard_page_context())


elif page == "workbench":
    render_workbench_page(_dashboard_page_context())


elif page == "timeline":
    render_timeline_page(_dashboard_page_context())


elif page == "resources":
    render_resources_page(_dashboard_page_context())


# ═══════════════════════════════════════════════════════════════
# Page: AI Director
# ═══════════════════════════════════════════════════════════════
elif page == "ai_director":
    render_ai_director_page(_dashboard_page_context())


# ═══════════════════════════════════════════════════════════════
# Page: System
# ═══════════════════════════════════════════════════════════════
elif page == "system":
    render_system_page(_dashboard_page_context())
