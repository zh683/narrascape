from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_i18n import zh_source


def fmt_seconds(value: float) -> str:
    minutes = int(value // 60)
    seconds = value - minutes * 60
    if minutes:
        return f"{minutes} 分 {seconds:04.1f} 秒"
    return f"{seconds:.1f} 秒"


def clip_rows(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clip in clips:
        rows.append(
            {
                "片段": clip.get("id"),
                "段落": clip.get("segment_id"),
                "来源": zh_source(str(clip.get("source") or "unknown")),
                "入点": fmt_seconds(float(clip.get("start") or 0.0)),
                "时长": fmt_seconds(float(clip.get("duration") or 0.0)),
                "景别": clip.get("shot_type") or "",
                "运动": clip.get("movement") or "",
                "素材": "正常" if clip.get("asset_exists") else "缺失",
            }
        )
    return rows


def render_source_mix(source_counts: dict[str, int]) -> None:
    if not source_counts:
        st.markdown(
            "<div style='color:#404040;font-style:italic'>暂无画面片段。</div>",
            unsafe_allow_html=True,
        )
        return
    total = max(sum(source_counts.values()), 1)
    colors = {
        "generated_video": "#3b82f6",
        "source_media": "#22c55e",
        "generated_image": "#f59e0b",
        "ending_card": "#71717a",
    }
    for source, count in sorted(source_counts.items()):
        pct = int(count / total * 100)
        color = colors.get(source, "#64748b")
        st.markdown(
            f"""
<div style="margin:8px 0">
  <div style="display:flex;justify-content:space-between;color:#737373;font-size:0.78em">
    <span>{zh_source(source)}</span><span>{count} 个片段 &middot; {pct}%</span>
  </div>
  <div class="progress-track"><div class="progress-fill" style="width:{pct}%;background:{color}"></div></div>
</div>
""",
            unsafe_allow_html=True,
        )


def path_exists(project_dir: Path, rel_path: str, fmt_size: Any) -> tuple[bool, str]:
    input_path = project_dir / rel_path
    if input_path.is_file():
        return True, fmt_size(input_path)
    if input_path.is_dir():
        count = sum(1 for item in input_path.rglob("*") if item.is_file())
        return True, f"{count} 个文件"
    alt = project_dir.parent.parent / rel_path
    if alt.is_file():
        return True, fmt_size(alt)
    if alt.is_dir():
        count = sum(1 for item in alt.rglob("*") if item.is_file())
        return True, f"{count} 个文件"
    return False, "缺失"
