"""Script writer — generates narration scripts from research or topic.

Uses structured LLM prompting with Chain-of-Thought reasoning and
automatic output validation. Falls back to templates when LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from narrascape.config import Script, ScriptSegment
from narrascape.llm import LLMClient, OutputValidator
from narrascape.llm.prompts import get_prompt
from narrascape.research.engine import ResearchResult, ResearchEngine

logger = logging.getLogger("narrascape.writer")


class ScriptWriter:
    """AI script writer with structured prompting and validation.

    Two modes:
    1. Research-driven: takes a ResearchResult, produces structured script
    2. Topic-driven: takes a topic string, auto-researches then writes
    """

    def __init__(self, llm_client: Any = None, style: str = "documentary"):
        self.llm_client = llm_client
        self.style = style
        self.research_engine = ResearchEngine(llm_client)

    def write_from_topic(
        self,
        topic: str,
        segment_count: int = 12,
        depth: str = "standard",
    ) -> Script:
        """Full pipeline: research topic → write script.

        Returns:
            Script ready for approval (still needs humanizer pass)
        """
        logger.info(f"[writer] Researching: {topic}")
        research = self.research_engine.research(topic, depth=depth)

        logger.info(f"[writer] Writing script ({segment_count} segments)")
        return self.write_from_research(research, segment_count)

    def write_from_research(
        self,
        research: ResearchResult,
        segment_count: int = 12,
    ) -> Script:
        """Write script from existing research findings."""
        if self.llm_client and isinstance(self.llm_client, LLMClient):
            return self._llm_write(research, segment_count)
        return self._template_write(research, segment_count)

    def _llm_write(self, research: ResearchResult, segment_count: int) -> Script:
        """Use structured LLM prompting with validation."""
        template = get_prompt("write")

        # Build validator
        validator = OutputValidator.combine(
            OutputValidator.has_keys("segments"),
            OutputValidator.has_nested_keys("segments", "id", "text"),
            OutputValidator.non_empty("segments"),
        )

        try:
            data = self.llm_client.run_template_validated(
                template,
                validator=validator,
                topic=research.topic,
                style=self.style,
                segment_count=segment_count,
                research=research.to_markdown(),
                max_format_retries=2,
            )

            segments = [ScriptSegment(**s) for s in data["segments"]]
            script = Script(segments=segments)
            logger.info(f"[writer] LLM wrote {script.segment_count} segments")
            return script

        except Exception as e:
            logger.warning(f"LLM write failed: {e}, falling back to template")
            return self._template_write(research, segment_count)

    def write_ending(self, script: Script, tone: str = "hopeful") -> Script:
        """Append a closing segment using LLM or template."""
        if self.llm_client and isinstance(self.llm_client, LLMClient):
            try:
                template = get_prompt("write_ending")
                segments_text = "\n".join(f"{s.id}: {s.text}" for s in script.segments[-3:])

                resp = self.llm_client.run_template(
                    template,
                    topic=getattr(script, 'topic', ''),
                    segments=segments_text,
                    tone=tone,
                )
                text = resp.text.strip().strip('"').strip("'")
                if text:
                    seg_id = script.segment_count + 1
                    script.segments.append(ScriptSegment(id=seg_id, text=text))
                    return script
            except Exception as e:
                logger.warning(f"LLM ending failed: {e}, using template")

        # Minimal fallback: generate a generic closing based on style/tone
        seg_id = script.segment_count + 1
        endings = {
            "hopeful": "And so, the story continues — in memory, in influence, and in the lives it touched.",
            "reflective": "Looking back, we see not just a story, but a mirror.",
            "dramatic": "This was the life — brief, yet eternal.",
            "nostalgic": "The era has passed, but the memory remains vivid.",
            "melancholic": "In the silence that follows, something lingers.",
            "triumphant": "The journey was long, but the destination was worth every step.",
        }
        text = endings.get(tone, "This is a story worth remembering.")
        script.segments.append(ScriptSegment(id=seg_id, text=text))
        return script

    def _template_write(self, research: ResearchResult, segment_count: int) -> Script:
        """Template-based script generation."""
        findings = research.findings
        segments = []

        # Opening: overview
        overview = findings.get("主题概述", findings.get("Overview", "这是一个值得探讨的主题。"))
        segments.append(ScriptSegment(
            id=1,
            text=f"{overview}今天，我们将一起走进这个故事。"
        ))

        # Timeline segments
        timeline = findings.get("时间线", findings.get("Timeline", []))
        for i, event in enumerate(timeline[:max(1, segment_count - 4)]):
            segments.append(ScriptSegment(
                id=len(segments) + 1,
                text=f"{event}。"
            ))

        # Key figures
        figures = findings.get("关键人物", findings.get("Key Figures", []))
        if figures:
            segments.append(ScriptSegment(
                id=len(segments) + 1,
                text=f"在他身边，{figures[0]}扮演着重要的角色。"
            ))

        # Social context
        context = findings.get("时代背景", findings.get("Social Context", ""))
        if context:
            segments.append(ScriptSegment(
                id=len(segments) + 1,
                text=f"那是{context}的时代。"
            ))

        # Personal insights
        insights = findings.get("个人感悟", findings.get("Personal Insights", ""))
        if insights:
            segments.append(ScriptSegment(
                id=len(segments) + 1,
                text=f"{insights}"
            ))

        # Fill remaining segments
        while len(segments) < segment_count:
            idx = len(segments) + 1
            segments.append(ScriptSegment(
                id=idx,
                text=f"第{idx}段文案。请根据主题补充具体内容。"
            ))

        # Trim and reassign IDs
        segments = segments[:segment_count]
        for i, seg in enumerate(segments):
            seg.id = i + 1

        return Script(segments=segments)
