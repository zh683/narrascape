"""Narrascape — Modern video pipeline dashboard."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# ═══════════════════════════════════════════════════════════════
#  Page config
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Narrascape",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════
#  Theme — minimal, modern, low-density
# ═══════════════════════════════════════════════════════════════
_CSS = """
<style>
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
#  Session state
# ═══════════════════════════════════════════════════════════════
def _init_state():
    defaults = {
        "project_dir": None,
        "config": None,
        "logs": [],
        "running_stage": None,
        "build_process": None,
        "log_queue": None,
        "pipeline_stage": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ═══════════════════════════════════════════════════════════════
#  Stage metadata
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

# ═══════════════════════════════════════════════════════════════
#  Sidebar
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

    workspace = Path.cwd()
    candidates = [d for d in workspace.iterdir() if d.is_dir() and (d / "config.yaml").exists()]
    project_names = [p.name for p in candidates] or ["(no projects)"]
    selected = st.selectbox("Project", project_names, label_visibility="collapsed")
    if selected != "(no projects)":
        st.session_state.project_dir = workspace / selected
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
        ("Overview", "home"),
        ("Pipeline", "pipeline"),
        ("Resources", "resources"),
        ("AI Director", "ai_director"),
        ("System", "system"),
    ]
    nav_labels = [n[0] for n in NAV]
    nav_keys = [n[1] for n in NAV]
    selected_nav = st.selectbox(
        "Navigate",
        range(len(nav_labels)),
        format_func=lambda i: nav_labels[i],
        label_visibility="collapsed",
    )
    page = nav_keys[selected_nav]

    st.markdown("<div style='height:2em'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:0.6em;color:#333;letter-spacing:0.1em'>Press R to refresh</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
#  Helpers
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


def _run_command(cmd: list[str], q: queue.Queue) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(Path.cwd()),
    )
    st.session_state.build_process = proc
    for line in proc.stdout:
        q.put(line.rstrip())
    proc.stdout.close()
    proc.wait()
    st.session_state.build_process = None


def _get_pipeline_dir() -> Path | None:
    if not st.session_state.project_dir:
        return None
    cfg = st.session_state.config
    name = cfg.project.name if cfg else st.session_state.project_dir.name
    return st.session_state.project_dir / "pipeline" / name


def _resolve_stage_name(obj) -> str:
    raw = getattr(obj, "name", None)
    if isinstance(raw, property):
        return raw.fget(obj) if hasattr(raw, "fget") else obj.__name__.replace("Stage", "").lower()
    if raw:
        return raw
    return obj.__name__.replace("Stage", "").lower()


def _get_stage_status(stage_name: str) -> dict:
    pdir = _get_pipeline_dir()
    if not pdir:
        return {"done": False, "files": [], "size": 0, "dir": None}
    stage_dir = pdir / stage_name
    done = stage_dir.exists()
    files = []
    total_size = 0
    if done:
        for f in stage_dir.rglob("*"):
            if f.is_file():
                files.append(f)
                try:
                    total_size += f.stat().st_size
                except Exception:
                    pass
    return {"done": done, "files": files, "size": total_size, "dir": stage_dir}


def _path_exists(pdir: Path, rel_path: str) -> tuple[bool, str]:
    inp_path = pdir / rel_path
    if inp_path.is_file():
        return True, _fmt_size(inp_path)
    elif inp_path.is_dir():
        count = sum(1 for _ in inp_path.rglob("*") if _.is_file())
        return True, f"{count} files"
    alt = pdir.parent.parent / rel_path
    if alt.is_file():
        return True, _fmt_size(alt)
    elif alt.is_dir():
        count = sum(1 for _ in alt.rglob("*") if _.is_file())
        return True, f"{count} files"
    return False, "missing"


def _render_stage_page(stage_name: str) -> None:
    meta = STAGE_META.get(stage_name, {})
    title = meta.get("title", stage_name)
    description = meta.get("description", "")

    st.header(title)
    st.markdown(
        f"<div style='color:#737373;font-size:0.9em;line-height:1.6;margin-bottom:1.5em'>{description}</div>",
        unsafe_allow_html=True,
    )

    pdir = st.session_state.project_dir
    cfg = st.session_state.config
    status = _get_stage_status(stage_name)

    # Status header
    tag = "done" if status["done"] else "pending"
    tag_text = "Done" if status["done"] else "Pending"
    st.markdown(
        f"""
<div style='display:flex;align-items:center;gap:16px;margin-bottom:1.5em'>
  <span class="tag tag-{tag}">{tag_text}</span>
  <span style='color:#525252;font-size:0.8em'>{len(status['files'])} files &middot; {_fmt_bytes(status['size'])}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    # Inputs
    st.markdown("<div class='section-label'>Inputs</div>", unsafe_allow_html=True)
    inputs = meta.get("inputs", [])
    if not inputs:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>No upstream inputs — first stage.</div>",
            unsafe_allow_html=True,
        )
    else:
        for inp in inputs:
            found, info = _path_exists(pdir, inp)
            color = "#22c55e" if found else "#ef4444"
            icon = "&#10003;" if found else "&#10007;"
            st.markdown(
                f"<div style='color:{color};font-family:monospace;font-size:0.8em;padding:2px 0'>{icon} {inp} <span style='color:#404040'>{info}</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:1em'></div>", unsafe_allow_html=True)

    # Outputs
    st.markdown("<div class='section-label'>Outputs</div>", unsafe_allow_html=True)
    if not status["done"]:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>Not yet executed. Run below to generate.</div>",
            unsafe_allow_html=True,
        )
    elif not status["files"]:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>Directory exists but empty.</div>",
            unsafe_allow_html=True,
        )
    else:
        images = [
            f for f in status["files"] if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        ]
        video = [f for f in status["files"] if f.suffix.lower() in (".mp4", ".mov")]
        audio = [f for f in status["files"] if f.suffix.lower() in (".mp3", ".wav", ".aac")]
        text = [
            f
            for f in status["files"]
            if f.suffix.lower() in (".md", ".yaml", ".yml", ".json", ".txt", ".srt")
        ]
        other = [f for f in status["files"] if f not in images + video + audio + text]

        if images:
            cols = st.columns(min(4, len(images[:8])))
            for i, f in enumerate(images[:8]):
                with cols[i % len(cols)]:
                    st.image(str(f), use_container_width=True)
                    st.caption(f"{f.name}")
        if video:
            for f in video[:3]:
                st.video(str(f))
                st.caption(f"{f.name} &middot; {_fmt_size(f)}")
        if audio:
            for f in audio[:4]:
                st.audio(str(f), format=f"audio/{f.suffix.lstrip('.')}")
                st.caption(f"{f.name} &middot; {_fmt_size(f)}")
        if text:
            for f in text[:6]:
                with st.expander(f"{f.name}"):
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        st.code(
                            content[:1500],
                            language=(
                                f.suffix.lstrip(".")
                                if f.suffix in (".yaml", ".yml", ".json")
                                else None
                            ),
                        )
                    except Exception as e:
                        st.error(f"Read: {e}")
        if other:
            for f in other[:10]:
                st.markdown(
                    f"<div class='file-row'>{f.name} &middot; {_fmt_size(f)}</div>",
                    unsafe_allow_html=True,
                )

    st.markdown("<div style='height:1.5em'></div>", unsafe_allow_html=True)

    # Controls
    st.markdown("<div class='section-label'>Controls</div>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        dry = st.checkbox("Dry", key=f"dry_{stage_name}")
    with c2:
        force = st.checkbox("Force", key=f"force_{stage_name}")
    with c3:
        if st.button(
            "Run",
            use_container_width=True,
            key=f"run_{stage_name}",
            disabled=st.session_state.running_stage is not None,
        ):
            st.session_state.running_stage = stage_name
            st.session_state.logs = []
            q = queue.Queue()
            st.session_state.log_queue = q
            cmd = [
                sys.executable,
                "-m",
                "narrascape.cli",
                "build",
                "-p",
                str(pdir),
                "--stage",
                stage_name,
            ]
            if force:
                cmd.append("--force")
            if dry:
                cmd.append("--dry-run")
            t = threading.Thread(target=_run_command, args=(cmd, q), daemon=True)
            t.start()
            st.rerun()
    with c4:
        if st.button("Clean", use_container_width=True, key=f"clean_{stage_name}"):
            if status["dir"] and status["dir"].exists():
                import shutil

                shutil.rmtree(status["dir"], ignore_errors=True)
                st.success("Cleaned")
                time.sleep(0.3)
                st.rerun()

    # Log
    if st.session_state.running_stage == stage_name:
        st.markdown("<div class='section-label'>Log</div>", unsafe_allow_html=True)
        q = st.session_state.log_queue
        if q is not None:
            new_lines = []
            while not q.empty():
                try:
                    new_lines.append(q.get_nowait())
                except queue.Empty:
                    break
            if new_lines:
                st.session_state.logs.extend(new_lines)
        if st.session_state.logs:
            log_text = "\n".join(st.session_state.logs[-200:])
            st.code(log_text, language=None)
        else:
            st.markdown(
                "<div style='color:#333;font-style:italic'>No output...</div>",
                unsafe_allow_html=True,
            )
        if st.session_state.build_process is None:
            st.session_state.running_stage = None
            st.session_state.log_queue = None
            st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  PAGE: Home
# ═══════════════════════════════════════════════════════════════
if page == "home":
    cfg = st.session_state.config
    pdir = st.session_state.project_dir

    if pdir is None:
        st.info("No project found. Create one with:  narrascape init my-video")
        st.stop()

    # Title + description
    title = cfg.project.title if cfg else pdir.name
    st.markdown(
        f"<div style='font-size:1.6em;font-weight:600;color:#fafafa'>{title}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='color:#525252;font-size:0.85em;margin-bottom:1.5em'>{pdir.name}</div>",
        unsafe_allow_html=True,
    )

    # Stats
    from narrascape.pipeline import ALL_STAGES

    stages_done = 0
    pipeline_dir = pdir / "pipeline" / pdir.name
    if pipeline_dir.exists():
        stages_done = sum(1 for d in pipeline_dir.iterdir() if d.is_dir())
    total_stages = len(ALL_STAGES)
    pct = int(stages_done / total_stages * 100)

    assets = pdir / "assets"
    img_count = (
        sum(1 for _ in (assets / "images").rglob("*") if _.is_file())
        if (assets / "images").exists()
        else 0
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{stages_done}/{total_stages}</div>
  <div class="stat-label">Stages</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{pct}%</div>
  <div class="stat-label">Progress</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
<div class="card-sm" style="text-align:center">
  <div class="stat-num">{img_count}</div>
  <div class="stat-label">Images</div>
</div>
""",
            unsafe_allow_html=True,
        )

    # Progress bar
    st.markdown(
        f"""
<div style="margin:1.5em 0">
  <div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Stage timeline
    st.markdown("<div class='section-label'>Pipeline</div>", unsafe_allow_html=True)
    timeline_html = '<div class="stage-timeline">'
    for i, cls in enumerate(ALL_STAGES):
        name = _resolve_stage_name(cls)
        meta = STAGE_META.get(name, {})
        label = meta.get("label", name)
        status = _get_stage_status(name)
        dot_cls = "done" if status["done"] else "current" if i == stages_done else "pending"
        node_cls = "done" if status["done"] else "current" if i == stages_done else ""
        timeline_html += f'<div class="stage-node {node_cls}"><div class="stage-dot {dot_cls}"></div>{label}</div>'
        if i < len(ALL_STAGES) - 1:
            timeline_html += '<span style="color:#262626">&rsaquo;</span>'
    timeline_html += "</div>"
    st.markdown(timeline_html, unsafe_allow_html=True)

    # Recent files
    st.markdown(
        "<div class='section-label' style='margin-top:2em'>Recent Files</div>",
        unsafe_allow_html=True,
    )
    if pipeline_dir.exists():
        all_files = sorted(
            [
                (f, f.stat().st_mtime)
                for d in pipeline_dir.rglob("*")
                if d.is_dir()
                for f in d.rglob("*")
                if f.is_file()
            ],
            key=lambda x: x[1],
            reverse=True,
        )[:10]
        for f, mtime in all_files:
            rel = f.relative_to(pipeline_dir)
            ts = datetime.fromtimestamp(mtime).strftime("%H:%M")
            st.markdown(
                f"<div class='file-row'>{rel} &middot; {_fmt_size(f)} &middot; {ts}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            "<div style='color:#404040;font-size:0.85em;font-style:italic'>No output yet.</div>",
            unsafe_allow_html=True,
        )

    # Quick actions
    st.markdown(
        "<div class='section-label' style='margin-top:2em'>Quick Actions</div>",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 1])
    with c1:
        dry = st.checkbox("Dry run", key="dry_full_home")
    with c2:
        force = st.checkbox("Force rebuild", key="force_full_home")
    if st.button(
        "Build Full Pipeline",
        use_container_width=True,
        disabled=st.session_state.running_stage is not None,
    ):
        st.session_state.running_stage = "full_pipeline"
        st.session_state.logs = []
        q = queue.Queue()
        st.session_state.log_queue = q
        cmd = [sys.executable, "-m", "narrascape.cli", "build", "-p", str(pdir)]
        if force:
            cmd.append("--force")
        if dry:
            cmd.append("--dry-run")
        t = threading.Thread(target=_run_command, args=(cmd, q), daemon=True)
        t.start()
        st.rerun()

    if st.session_state.running_stage == "full_pipeline":
        st.markdown("<div class='section-label'>Build Log</div>", unsafe_allow_html=True)
        q = st.session_state.log_queue
        if q is not None:
            new_lines = []
            while not q.empty():
                try:
                    new_lines.append(q.get_nowait())
                except queue.Empty:
                    break
            if new_lines:
                st.session_state.logs.extend(new_lines)
        if st.session_state.logs:
            st.code("\n".join(st.session_state.logs[-300:]), language=None)
        else:
            st.markdown(
                "<div style='color:#333;font-style:italic'>No output...</div>",
                unsafe_allow_html=True,
            )
        if st.session_state.build_process is None:
            st.session_state.running_stage = None
            st.session_state.log_queue = None
            st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  PAGE: Pipeline
# ═══════════════════════════════════════════════════════════════
elif page == "pipeline":
    st.header("Pipeline")

    if st.session_state.project_dir is None:
        st.info("Select a project from the sidebar.")
        st.stop()

    from narrascape.pipeline import ALL_STAGES

    # Stage selector
    stage_names = [_resolve_stage_name(cls) for cls in ALL_STAGES]
    stage_labels = [STAGE_META.get(n, {}).get("label", n) for n in stage_names]
    selected = st.selectbox(
        "Stage", range(len(stage_labels)), format_func=lambda i: f"{i+1}. {stage_labels[i]}"
    )
    selected_stage = stage_names[selected]

    # Divider
    st.markdown("<div style='height:0.5em'></div>", unsafe_allow_html=True)

    # Render selected stage
    _render_stage_page(selected_stage)


# ═══════════════════════════════════════════════════════════════
#  PAGE: Resources
# ═══════════════════════════════════════════════════════════════
elif page == "resources":
    st.header("Resources")

    if st.session_state.project_dir is None:
        st.info("Select a project from the sidebar.")
        st.stop()

    pdir = st.session_state.project_dir
    assets = pdir / "assets"
    tabs = st.tabs(["Images", "TTS", "BGM", "Video", "Output"])

    with tabs[0]:
        img_dir = assets / "images"
        if img_dir.exists():
            files = sorted(img_dir.rglob("*"))
            img_files = [f for f in files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{len(img_files)} images</div>",
                unsafe_allow_html=True,
            )
            if img_files:
                cols = st.columns(4)
                for i, f in enumerate(img_files[:16]):
                    with cols[i % 4]:
                        st.image(str(f), use_container_width=True)
                        st.caption(f.name, unsafe_allow_html=False)
            else:
                st.markdown(
                    "<div style='color:#404040;font-style:italic'>No images.</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                "<div style='color:#404040;font-style:italic'>No images directory.</div>",
                unsafe_allow_html=True,
            )

    with tabs[1]:
        tts_dir = assets / "tts"
        if tts_dir.exists():
            files = sorted([f for f in tts_dir.rglob("*") if f.suffix.lower() in (".mp3", ".wav")])
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{len(files)} files</div>",
                unsafe_allow_html=True,
            )
            for f in files:
                st.audio(str(f))
                st.caption(f"{f.name} &middot; {_fmt_size(f)}")
        else:
            st.markdown(
                "<div style='color:#404040;font-style:italic'>No TTS audio.</div>",
                unsafe_allow_html=True,
            )

    with tabs[2]:
        music_dir = assets / "music"
        if music_dir.exists():
            files = sorted(
                [f for f in music_dir.rglob("*") if f.suffix.lower() in (".mp3", ".wav")]
            )
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{len(files)} files</div>",
                unsafe_allow_html=True,
            )
            for f in files:
                st.audio(str(f))
                st.caption(f"{f.name} &middot; {_fmt_size(f)}")
        else:
            st.markdown(
                "<div style='color:#404040;font-style:italic'>No BGM.</div>", unsafe_allow_html=True
            )

    with tabs[3]:
        video_dir = assets / "videos"
        if video_dir.exists():
            files = sorted(
                [f for f in video_dir.rglob("*") if f.suffix.lower() in (".mp4", ".mov")]
            )
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{len(files)} files</div>",
                unsafe_allow_html=True,
            )
            for f in files[:6]:
                st.video(str(f))
                st.caption(f"{f.name} &middot; {_fmt_size(f)}")
        else:
            st.markdown(
                "<div style='color:#404040;font-style:italic'>No videos.</div>",
                unsafe_allow_html=True,
            )

    with tabs[4]:
        out_dir = pdir / "output"
        if out_dir.exists():
            files = sorted(out_dir.rglob("*"))
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em;margin-bottom:1em'>{len(files)} files</div>",
                unsafe_allow_html=True,
            )
            for f in files:
                if f.suffix.lower() in (".mp4", ".mov"):
                    st.video(str(f))
                elif f.suffix.lower() in (".png", ".jpg"):
                    st.image(str(f))
                st.caption(f.name)
        else:
            st.markdown(
                "<div style='color:#404040;font-style:italic'>No output.</div>",
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════════
#  PAGE: AI Director
# ═══════════════════════════════════════════════════════════════
elif page == "ai_director":
    st.header("AI Director")
    st.markdown(
        "<div style='color:#737373;font-size:0.9em'>Debug PromptDirector logic without LLM calls.</div>",
        unsafe_allow_html=True,
    )

    from narrascape.agent.prompt_director import PromptDirector
    from narrascape.config import ShotType

    director = PromptDirector(llm_client=None)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("<div class='section-label'>Shot Type Parser</div>", unsafe_allow_html=True)
        shot_input = st.text_input("Type", "close-up", label_visibility="collapsed")
        if shot_input:
            try:
                result = director._parse_shot_type(shot_input)
                st.markdown(
                    f"<div style='color:#22c55e;font-family:monospace;font-size:0.85em'>{result}</div>",
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(str(e))

        st.markdown("<div class='section-label'>Movement Parser</div>", unsafe_allow_html=True)
        mov_input = st.text_input("Movement", "zoom_in_slow", label_visibility="collapsed")
        if mov_input:
            try:
                result = director._parse_movement_type(mov_input)
                st.markdown(
                    f"<div style='color:#22c55e;font-family:monospace;font-size:0.85em'>{result}</div>",
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(str(e))

        st.markdown("<div class='section-label'>Size Deriver</div>", unsafe_allow_html=True)
        size_input = st.selectbox("Shot", [e.value for e in ShotType], label_visibility="collapsed")
        if size_input:
            try:
                from narrascape.motion.factory import derive_size

                size = derive_size(ShotType(size_input), None)
                st.markdown(
                    f"<div style='color:#22c55e;font-family:monospace;font-size:0.85em'>{size}</div>",
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(str(e))

    with col2:
        st.markdown("<div class='section-label'>Duration Estimator</div>", unsafe_allow_html=True)
        text_sample = st.text_area(
            "Text", "Test text for duration.", height=60, label_visibility="collapsed"
        )
        speed = st.slider("Speed", 0.5, 2.0, 1.0, 0.1, label_visibility="collapsed")
        if text_sample:
            try:
                from narrascape.config import NarrascapeConfig, ProjectConfig, TTSConfig

                cfg = NarrascapeConfig(
                    project=ProjectConfig(
                        name="debug", title="Debug", script_file="scripts/script.yaml"
                    ),
                    tts=TTSConfig(speed=speed),
                )
                duration = director._estimate_duration(text_sample, cfg)
                st.markdown(
                    f"<div style='color:#22c55e;font-family:monospace;font-size:0.85em'>{duration:.1f}s</div>",
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(str(e))

        st.markdown("<div class='section-label'>Consistency</div>", unsafe_allow_html=True)
        design_json = st.text_area(
            "JSON",
            '{"director_vision": "A man", "cinematic_format": "A man, 85mm", "image_prompt": "A man"}',
            height=80,
            label_visibility="collapsed",
        )
        if st.button("Verify"):
            try:
                data = json.loads(design_json)
                ok = director._verify_three_layer_consistency(data)
                color = "#22c55e" if ok else "#ef4444"
                text = "Consistent" if ok else "Inconsistent"
                st.markdown(
                    f'<div style="color:{color};font-family:monospace;font-size:0.85em">{text}</div>',
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(str(e))

    st.markdown("<div class='section-label'>Template Selector</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        tpl_text = st.text_input("Segment", "Short text.", label_visibility="collapsed")
    with c2:
        tpl_know = st.text_input("Knowledge", "Brief knowledge.", label_visibility="collapsed")
    with c3:
        tpl_model = st.selectbox(
            "Model",
            ["deepseek-v3", "claude-3-5-sonnet", "gpt-4o", "doubao-pro"],
            label_visibility="collapsed",
        )
    if st.button("Select"):
        try:
            tpl = director._select_template(tpl_text, tpl_know, tpl_model)
            st.markdown(
                f"<div style='color:#3b82f6;font-family:monospace;font-size:0.85em'>{tpl.__class__.__name__}</div>",
                unsafe_allow_html=True,
            )
            with st.expander("Preview"):
                st.code(tpl.system[:500] + "...")
        except Exception as e:
            st.error(str(e))


# ═══════════════════════════════════════════════════════════════
#  PAGE: System
# ═══════════════════════════════════════════════════════════════
elif page == "system":
    st.header("System")

    # Cache
    st.markdown("<div class='section-label'>Cache</div>", unsafe_allow_html=True)
    if st.session_state.project_dir and st.session_state.config:
        try:
            from narrascape.cache import BuildCache

            cache = BuildCache(st.session_state.config.pipeline_dir / ".cache")
            entries = list(cache.cache_dir.iterdir()) if cache.cache_dir.exists() else []
            st.markdown(
                f"<div style='color:#525252;font-size:0.8em'>{len(entries)} entries &middot; {cache.cache_dir}</div>",
                unsafe_allow_html=True,
            )
            if entries:
                data = []
                for e in entries[:30]:
                    try:
                        stat = e.stat()
                        data.append(
                            {
                                "file": e.name[:20],
                                "size": _fmt_size(e),
                                "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                                    "%Y-%m-%d %H:%M"
                                ),
                            }
                        )
                    except Exception:
                        pass
                st.dataframe(data, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Cache: {e}")
    else:
        st.markdown(
            "<div style='color:#404040;font-style:italic'>Select a project.</div>",
            unsafe_allow_html=True,
        )

    # Budget
    st.markdown("<div class='section-label'>Budget</div>", unsafe_allow_html=True)
    if st.session_state.project_dir and st.session_state.config:
        try:
            from narrascape.utils.budget import BudgetTracker

            bt = BudgetTracker(
                st.session_state.config.budget,
                st.session_state.config.pipeline_dir / "budget_state.json",
            )
            st.markdown(
                f"<div style='font-family:monospace;font-size:0.8em;color:#737373'>Spent: {bt.spent:.4f} &middot; File: {bt.state_path}</div>",
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"Budget: {e}")
    else:
        st.markdown(
            "<div style='color:#404040;font-style:italic'>Select a project.</div>",
            unsafe_allow_html=True,
        )

    # Health
    st.markdown("<div class='section-label'>Health</div>", unsafe_allow_html=True)
    checks = []
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        checks.append(
            (
                "FFmpeg",
                result.returncode == 0,
                result.stdout.splitlines()[0] if result.stdout else "unknown",
            )
        )
    except Exception as e:
        checks.append(("FFmpeg", False, str(e)))

    try:
        from narrascape.api_keys import APIKeys

        openai_key = bool(APIKeys.openai())
        ark_key = bool(APIKeys.ark())
        checks.append(("OpenAI", openai_key, "ok" if openai_key else "missing"))
        checks.append(("ARK", ark_key, "ok" if ark_key else "missing"))
    except Exception as e:
        checks.append(("API Keys", False, str(e)))

    try:
        import narrascape

        checks.append(("Package", True, narrascape.__version__))
    except Exception as e:
        checks.append(("Package", False, str(e)))

    for name, ok, detail in checks:
        color = "#22c55e" if ok else "#ef4444"
        icon = "&#10003;" if ok else "&#10007;"
        st.markdown(
            f"<div style='color:{color};font-family:monospace;font-size:0.85em;padding:2px 0'>{icon} {name} &mdash; {detail}</div>",
            unsafe_allow_html=True,
        )

    # Tests
    st.markdown("<div class='section-label'>Tests</div>", unsafe_allow_html=True)
    if st.button("Run pytest"):
        with st.spinner("Running..."):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                st.code(result.stdout + "\n" + result.stderr, language=None)
            except Exception as e:
                st.error(f"Tests: {e}")
