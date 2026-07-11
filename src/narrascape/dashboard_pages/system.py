from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from narrascape.dashboard_pages.context import DashboardPageContext


def render_system_page(ctx: DashboardPageContext) -> None:
    st.header("系统诊断")

    _render_cache(ctx)
    _render_budget(ctx)
    _render_health()
    _render_tests()


def _render_cache(ctx: DashboardPageContext) -> None:
    st.markdown("<div class='section-label'>构建缓存</div>", unsafe_allow_html=True)
    if not ctx.project_dir or not ctx.config:
        _select_project()
        return
    try:
        from narrascape.cache import BuildCache

        cache_dir = Path(ctx.config.pipeline_dir) / ".cache"
        BuildCache(cache_dir)
        entries: list[Path] = list(cache_dir.iterdir()) if cache_dir.exists() else []
        st.markdown(
            "<div style='color:#525252;font-size:0.8em'>"
            f"{len(entries)} 个条目 &middot; {cache_dir}</div>",
            unsafe_allow_html=True,
        )
        if entries:
            _render_cache_rows(ctx, entries)
    except Exception as exc:
        st.error(f"缓存检查失败：{exc}")


def _render_cache_rows(ctx: DashboardPageContext, entries: list[Path]) -> None:
    cache_rows: list[dict[str, Any]] = []
    for entry in entries[:30]:
        try:
            stat = entry.stat()
            cache_rows.append(
                {
                    "文件": entry.name[:20],
                    "大小": ctx.fmt_size(entry),
                    "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
            )
        except Exception:
            pass
    st.dataframe(cache_rows, use_container_width=True, hide_index=True)


def _render_budget(ctx: DashboardPageContext) -> None:
    st.markdown("<div class='section-label'>预算</div>", unsafe_allow_html=True)
    if not ctx.project_dir or not ctx.config:
        _select_project()
        return
    try:
        from narrascape.utils.budget import BudgetTracker

        tracker = BudgetTracker(
            ctx.config.budget,
            ctx.config.pipeline_dir / "budget_state.json",
        )
        st.markdown(
            f"<div style='font-family:monospace;font-size:0.8em;color:#737373'>"
            f"已使用：{tracker.spent:.4f} &middot; 状态文件：{tracker.state_path}</div>",
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.error(f"预算检查失败：{exc}")


def _render_health() -> None:
    st.markdown("<div class='section-label'>运行环境</div>", unsafe_allow_html=True)
    checks = []
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        checks.append(
            (
                "FFmpeg",
                result.returncode == 0,
                result.stdout.splitlines()[0] if result.stdout else "未知",
            )
        )
    except Exception as exc:
        checks.append(("FFmpeg", False, str(exc)))

    try:
        from narrascape.api_keys import APIKeys

        openai_key = bool(APIKeys.openai())
        ark_key = bool(APIKeys.ark())
        checks.append(("OpenAI", openai_key, "正常" if openai_key else "缺失"))
        checks.append(("ARK", ark_key, "正常" if ark_key else "缺失"))
    except Exception as exc:
        checks.append(("API 密钥", False, str(exc)))

    try:
        import narrascape

        checks.append(("软件包", True, narrascape.__version__))
    except Exception as exc:
        checks.append(("软件包", False, str(exc)))

    for name, ok, detail in checks:
        color = "#22c55e" if ok else "#ef4444"
        icon = "&#10003;" if ok else "&#10007;"
        st.markdown(
            f"<div style='color:{color};font-family:monospace;font-size:0.85em;padding:2px 0'>"
            f"{icon} {name} &mdash; {detail}</div>",
            unsafe_allow_html=True,
        )


def _render_tests() -> None:
    st.markdown("<div class='section-label'>测试</div>", unsafe_allow_html=True)
    if st.button("运行 pytest"):
        with st.spinner("正在运行…"):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                st.code(result.stdout + "\n" + result.stderr, language=None)
            except Exception as exc:
                st.error(f"测试失败：{exc}")


def _select_project() -> None:
    st.markdown(
        "<div style='color:#404040;font-style:italic'>请选择项目。</div>",
        unsafe_allow_html=True,
    )
