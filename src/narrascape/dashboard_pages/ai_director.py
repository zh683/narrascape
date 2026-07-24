from __future__ import annotations

import json

import streamlit as st

from narrascape.agent.prompt_director import PromptDirector
from narrascape.dashboard_pages.context import DashboardPageContext


def render_ai_director_page(ctx: DashboardPageContext) -> None:
    st.header("AI 导演诊断")
    st.markdown(
        "<div style='color:#737373;font-size:0.9em'>在不调用 LLM 的情况下检查 PromptDirector 解析逻辑。</div>",
        unsafe_allow_html=True,
    )

    director = PromptDirector(llm_client=None)
    left, right = st.columns([1, 1])
    with left:
        _render_parser_panel(director)
    with right:
        _render_estimator_panel(director)
    _render_template_selector(director)


def _render_parser_panel(director: PromptDirector) -> None:
    from narrascape.config import ShotType

    st.markdown("<div class='section-label'>景别解析器</div>", unsafe_allow_html=True)
    shot_input = st.text_input("Type", "close-up", label_visibility="collapsed")
    if shot_input:
        try:
            parsed_shot_type = director._parse_shot_type(shot_input)
            _result(str(parsed_shot_type), "#22c55e")
        except Exception as exc:
            st.error(str(exc))

    st.markdown("<div class='section-label'>镜头运动解析器</div>", unsafe_allow_html=True)
    movement_input = st.text_input("Movement", "zoom_in_slow", label_visibility="collapsed")
    if movement_input:
        try:
            parsed_movement = director._parse_movement_type(movement_input)
            _result(str(parsed_movement), "#22c55e")
        except Exception as exc:
            st.error(str(exc))

    st.markdown("<div class='section-label'>画幅尺寸推导</div>", unsafe_allow_html=True)
    size_input = st.selectbox(
        "Shot", [item.value for item in ShotType], label_visibility="collapsed"
    )
    if size_input:
        try:
            from narrascape.motion.factory import derive_size

            size = derive_size(ShotType(size_input), None)
            _result(str(size), "#22c55e")
        except Exception as exc:
            st.error(str(exc))


def _render_estimator_panel(director: PromptDirector) -> None:
    st.markdown("<div class='section-label'>时长估算</div>", unsafe_allow_html=True)
    text_sample = st.text_area(
        "文本", "用于估算时长的测试文本。", height=60, label_visibility="collapsed"
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
            _result(f"{duration:.1f}s", "#22c55e")
        except Exception as exc:
            st.error(str(exc))

    st.markdown("<div class='section-label'>三层一致性</div>", unsafe_allow_html=True)
    design_json = st.text_area(
        "JSON",
        '{"director_vision": "A man", "cinematic_format": "A man, 85mm", "image_prompt": "A man"}',
        height=80,
        label_visibility="collapsed",
    )
    if st.button("验证"):
        try:
            data = json.loads(design_json)
            ok = director._verify_three_layer_consistency(data)
            _result("一致" if ok else "不一致", "#22c55e" if ok else "#ef4444")
        except Exception as exc:
            st.error(str(exc))


def _render_template_selector(director: PromptDirector) -> None:
    st.markdown("<div class='section-label'>提示模板选择</div>", unsafe_allow_html=True)
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
    if st.button("选择模板"):
        try:
            template = director._select_template(tpl_text, tpl_know, tpl_model)
            _result(template.__class__.__name__, "#3b82f6")
            with st.expander("模板预览"):
                st.code(str(template.system or "")[:500] + "...")
        except Exception as exc:
            st.error(str(exc))


def _result(text: str, color: str) -> None:
    st.markdown(
        f"<div style='color:{color};font-family:monospace;font-size:0.85em'>{text}</div>",
        unsafe_allow_html=True,
    )
