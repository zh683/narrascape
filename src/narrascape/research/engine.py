"""Research module — gather background information for video narration.

Supports both LLM-powered research (with structured prompting and validation)
and template-based research outlines when LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from narrascape.llm import LLMClient, OutputValidator
from narrascape.llm.prompts import get_prompt

logger = logging.getLogger("narrascape.research")


class ResearchResult:
    """Container for research findings."""

    def __init__(self, topic: str, findings: dict[str, Any]):
        self.topic = topic
        self.findings = findings

    def to_markdown(self) -> str:
        """Export research as a readable markdown report."""
        lines = [f"# Research Report: {self.topic}", ""]
        for section, content in self.findings.items():
            if section == "narrative_arc":
                lines.append(f"> **Narrative Arc:** {content}")
                lines.append("")
                continue
            lines.append(f"## {section}")
            if isinstance(content, list):
                for item in content:
                    lines.append(f"- {item}")
            else:
                lines.append(str(content))
            lines.append("")
        return "\n".join(lines)


class ResearchEngine:
    """AI research engine with structured prompting and output validation."""

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def research(self, topic: str, depth: str = "standard") -> ResearchResult:
        """Research a topic with LLM-powered structured prompting.

        Args:
            topic: The subject to research (e.g. "托尔斯泰的生平")
            depth: "brief" | "standard" | "deep"
        """
        logger.info(f"[research] Starting research on: {topic} (depth={depth})")

        if self.llm_client and isinstance(self.llm_client, LLMClient):
            return self._llm_research(topic, depth)
        return self._template_research(topic, depth)

    def _llm_research(self, topic: str, depth: str) -> ResearchResult:
        """Use LLM with structured prompting and validation."""
        template = get_prompt("research")

        # Build validator for expected output structure
        validator = OutputValidator.combine(
            OutputValidator.has_keys("topic", "narrative_arc", "findings"),
            OutputValidator.has_nested_keys("findings", "时间线", "关键人物", "重要事件"),
        )

        try:
            data = self.llm_client.run_template_validated(
                template,
                validator=validator,
                topic=topic,
                depth=depth,
                max_format_retries=2,
            )

            findings = data.get("findings", {})
            if data.get("narrative_arc"):
                findings["narrative_arc"] = data["narrative_arc"]

            logger.info(f"[research] LLM research complete: {len(findings)} sections")
            return ResearchResult(topic, findings)

        except Exception as e:
            logger.warning(f"LLM research failed: {e}, falling back to template")
            return self._template_research(topic, depth)

    def _template_research(self, topic: str, depth: str) -> ResearchResult:
        """Generic template-based research when LLM is unavailable.

        Returns a structured outline with placeholder prompts for each section.
        The user should fill in the actual research content, or run with LLM
        for automatic generation.
        """
        findings = {
            "主题概述": f"{topic} 是一个值得深入探讨的主题。请补充核心叙事和背景。",
            "时间线": ["请补充关键时间节点和具体事件"],
            "关键人物": ["请补充相关人物及其关系"],
            "重要事件": ["请补充核心事件及其影响"],
            "时代背景": "请补充历史与社会背景",
            "个人感悟": "请补充思考与感悟，连接个人故事与普世主题",
            "视觉意象": ["请补充可用于画面的具体视觉元素：场景、光线、色彩、天气等"],
            "情感转折点": ["请补充情感起伏的关键时刻"],
        }

        return ResearchResult(topic, findings)


def load_research_report(path: str) -> ResearchResult:
    """Load a research report from markdown file."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Research report not found: {path}")

    text = p.read_text(encoding="utf-8")
    # Simple parsing: extract sections
    findings = {}
    current_section = "Overview"
    lines = text.split("\n")
    for line in lines:
        if line.startswith("## "):
            current_section = line[3:].strip()
            findings[current_section] = []
        elif line.startswith("- ") and current_section in findings:
            if isinstance(findings[current_section], list):
                findings[current_section].append(line[2:].strip())
            else:
                findings[current_section] = [line[2:].strip()]
        elif line.strip() and current_section in findings:
            if isinstance(findings[current_section], list) and findings[current_section]:
                findings[current_section].append(line.strip())
            else:
                findings[current_section] = line.strip()

    return ResearchResult("loaded", findings)
