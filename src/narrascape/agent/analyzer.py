"""Script analyzer — emotional and semantic analysis of narration text.

Two modes:
1. LLM mode (preferred): LLM deeply understands text, extracts emotion, scene, entities, visuals
2. Rule-based fallback: keyword matching when no LLM is available
"""

from __future__ import annotations

import logging
import re
from typing import Any

from narrascape.agent.models import SegmentAnalysis
from narrascape.config import Script, ScriptSegment
from narrascape.llm import OutputValidator, is_assistant_bridge_provider
from narrascape.llm.prompts import get_prompt

logger = logging.getLogger("narrascape.agent.analyzer")

_MAX_BATCH_SEGMENTS = 10
_MAX_BATCH_CHARS = 12000


# ── Rule-based emotion lexicon (fallback only) ───────────────────────────

EMOTION_WORDS = {
    "calm": {
        "平静",
        "宁静",
        "安详",
        "柔和",
        "温暖",
        "calm",
        "peaceful",
        "serene",
        "gentle",
        "warm",
    },
    "tense": {
        "紧张",
        "焦虑",
        "不安",
        "危机",
        "冲突",
        "tense",
        "anxious",
        "uneasy",
        "crisis",
        "conflict",
        "danger",
    },
    "sad": {
        "悲伤",
        "痛苦",
        "绝望",
        "孤独",
        "凄凉",
        "sad",
        "pain",
        "despair",
        "lonely",
        "desolate",
        "mourn",
    },
    "hopeful": {
        "希望",
        "光明",
        "未来",
        "重生",
        "期待",
        "hope",
        "light",
        "future",
        "rebirth",
        "expect",
        "new",
    },
    "dramatic": {
        "戏剧",
        "震撼",
        "巨变",
        "转折",
        "高潮",
        "dramatic",
        "shock",
        "upheaval",
        "turning",
        "climax",
    },
    "nostalgic": {
        "回忆",
        "过去",
        "童年",
        "旧时光",
        "nostalgic",
        "memory",
        "past",
        "childhood",
        "old days",
        "long ago",
    },
    "awe": {
        "伟大",
        "崇高",
        "神圣",
        "敬畏",
        "震撼",
        "awe",
        "grand",
        "sublime",
        "sacred",
        "reverence",
        "magnificent",
    },
    "mysterious": {
        "神秘",
        "未知",
        "迷雾",
        "秘密",
        "mysterious",
        "unknown",
        "mist",
        "secret",
        "enigma",
        "obscure",
    },
    "urgent": {"紧急", "迫切", " hurry", "urgent", "rush", "haste", "immediate", "pressing"},
}

SCENE_WORDS = {
    "indoor": {
        "室内",
        "房间",
        "书房",
        "卧室",
        "教堂",
        "indoor",
        "room",
        "study",
        "bedroom",
        "church",
        "house",
    },
    "outdoor": {"户外", "田野", "街道", "花园", "outdoor", "field", "street", "garden", "park"},
    "landscape": {"风景", "自然", "山水", "landscape", "nature", "mountain", "forest", "river"},
    "urban": {"城市", "街道", "建筑", "urban", "city", "building", "street", "architecture"},
    "portrait": {"人物", "肖像", "portrait", "person", "figure", "character"},
}

PACING_WORDS = {
    "slow": {"缓慢", "静止", "沉思", "slow", "still", "contemplation", "meditation", "pause"},
    "fast": {"迅速", "激烈", "快速", "fast", "rapid", "fierce", "swift", "abrupt"},
}


# ── LLM Analyzer Prompt ───────────────────────────

ANALYZER_PROMPT = """You are a cinematographer analyzing a narration script segment for a documentary video.

Read the segment deeply. Do NOT just count keywords — understand the emotional subtext, visual imagery, and narrative purpose.

Segment text: "{text}"
Segment ID: {seg_id}

Analyze and return ONLY a JSON object with these fields:
{{
    "emotion": "<dominant emotion in 1-2 words. Options: calm, tense, sad, hopeful, dramatic, nostalgic, awe, mysterious, urgent, peaceful, melancholic, triumphant, intimate, lonely, bittersweet, reverent, playful, somber, ethereal, visceral, or any other nuanced emotion that fits>",
    "intensity": <0.0 to 1.0. How strongly is the emotion felt? 0.1 = barely there, 0.5 = moderate, 0.9 = overwhelming>,
    "scene_type": "<indoor, outdoor, landscape, urban, portrait, abstract, historical, battlefield, domestic, wilderness, seascape, celestial, or any other setting>",
    "key_entities": ["<list of 1-5 visual subjects (people, objects, places) that should appear in the image. Be specific and concrete.>"],
    "visual_keywords": ["<list of 2-5 atmosphere descriptors: lighting, weather, color palette, time of day, texture, mood words. E.g., 'golden hour', 'foggy', 'cool blue tones', 'rough stone', 'dust particles'>"],
    "pacing": "<slow, normal, or fast. Based on the rhythm of the text and the emotional weight>",
    "narrative_function": "<What does this segment DO in the story? Options: opening, exposition, rising_action, climax, falling_action, resolution, transition, reflection, contrast, call_to_action, or describe in your own words>"
}}

Guidelines:
- Emotion should be nuanced and specific, not just generic labels
- Key entities should be concrete visual subjects, not abstract concepts
- Visual keywords should evoke a specific look and feel
- Consider the overall documentary context, not just surface-level words
"""


class ScriptAnalyzer:
    """Analyzes narration script for emotional and visual content.

    LLM mode (preferred): LLM deeply understands text semantics.
    Rule-based fallback: keyword matching when LLM is unavailable.
    """

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def analyze(self, script: Script) -> list[SegmentAnalysis]:
        """Analyze all segments. LLM-first, one API call per segment (or batch in bridge mode)."""
        # Bridge mode: analyze all segments in one batch to reduce task files
        if (
            self.llm_client
            and getattr(self.llm_client, "config", None)
            and is_assistant_bridge_provider(self.llm_client.config.provider)
        ):
            try:
                return self._llm_analyze_batch(script)
            except Exception as e:
                logger.error(f"Batch bridge analysis failed: {e}")
                raise

        results = []
        for seg in script.segments:
            analysis = self._analyze_segment(seg)
            results.append(analysis)
        return results

    def _llm_analyze_batch(self, script: Script) -> list[SegmentAnalysis]:
        """Analyze all segments with bounded batch prompts for bridge providers."""
        results: list[SegmentAnalysis] = []
        for batch in _segment_batches(script.segments):
            results.extend(self._llm_analyze_batch_segments(batch))
        return results

    def _llm_analyze_batch_segments(self, segments: list[ScriptSegment]) -> list[SegmentAnalysis]:
        """Analyze a bounded set of segments in one LLM call."""
        segments_text = "\n\n".join([f"Segment {seg.id}: {seg.text}" for seg in segments])

        prompt = f"""You are a cinematographer analyzing narration script segments for a documentary video.

Analyze ALL segments below and return a JSON array with one analysis object per segment.

Script segments:
{segments_text}

For each segment, return an object with:
{{
    "segment_id": <segment number>,
    "emotion": "<nuanced emotion>",
    "intensity": <0.0 to 1.0>,
    "scene_type": "<indoor/outdoor/landscape/urban/portrait/etc>",
    "key_entities": ["<1-5 visual subjects>"],
    "visual_keywords": ["<2-5 atmosphere descriptors>"],
    "pacing": "<slow/normal/fast>",
    "narrative_function": "<segment's role in story>",
    "camera_suggestion": "<camera movement>",
    "lighting_suggestion": "<lighting description>"
}}

Return ONLY a valid JSON array. Be specific and use professional cinematography terminology."""

        resp = self.llm_client.complete(prompt, json_mode=True)
        data = resp.extract_json()

        if isinstance(data, dict) and len(segments) == 1:
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data)}")

        results = []
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"Expected analysis object, got {type(item)}")
            results.append(
                SegmentAnalysis(
                    segment_id=item.get("segment_id", 0),
                    emotion=item.get("emotion", "calm"),
                    intensity=float(item.get("intensity", 0.5)),
                    scene_type=item.get("scene_type", "outdoor"),
                    key_entities=item.get("key_entities", []) or [],
                    visual_keywords=item.get("visual_keywords", []) or [],
                    pacing=item.get("pacing", "normal"),
                )
            )
        return results

    def _analyze_segment(self, seg: ScriptSegment) -> SegmentAnalysis:
        """Analyze a single segment. LLM-first, fallback to rules."""
        # ── LLM Analysis (preferred) ──
        if self.llm_client:
            try:
                return self._llm_analyze(seg)
            except Exception as e:
                logger.warning(f"LLM analysis failed for segment {seg.id}: {e}")
                # Fall through to rule-based

        # ── Rule-based Fallback ──
        return self._rule_analyze(seg)

    def _llm_analyze(self, seg: ScriptSegment) -> SegmentAnalysis:
        """Use structured LLM prompting with output validation."""
        template = get_prompt("analyzer")

        # Build validator
        validator = OutputValidator.combine(
            OutputValidator.has_keys(
                "emotion",
                "intensity",
                "scene_type",
                "key_entities",
                "visual_keywords",
                "pacing",
                "narrative_function",
            ),
            OutputValidator.range_check("intensity", 0.0, 1.0),
            OutputValidator.non_empty("emotion"),
        )

        try:
            data = self.llm_client.run_template_validated(
                template,
                validator=validator,
                text=seg.text,
                seg_id=seg.id,
                max_format_retries=2,
            )

            return SegmentAnalysis(
                segment_id=seg.id,
                emotion=data.get("emotion", "calm"),
                intensity=float(data.get("intensity", 0.5)),
                scene_type=data.get("scene_type", "outdoor"),
                key_entities=data.get("key_entities", []) or [],
                visual_keywords=data.get("visual_keywords", []) or [],
                pacing=data.get("pacing", "normal"),
            )
        except Exception as e:
            logger.warning(f"LLM analysis failed for segment {seg.id}: {e}, falling back to rules")
            return self._rule_analyze(seg)

    def _rule_analyze(self, seg: ScriptSegment) -> SegmentAnalysis:
        """Rule-based fallback when LLM is unavailable."""
        text = seg.text

        emotion, intensity = _detect_emotion(text)
        scene_type = _detect_scene_type(text)
        pacing = _detect_pacing(text)
        entities = _extract_entities(text)
        visual_keywords = _extract_visual_keywords(text)

        return SegmentAnalysis(
            segment_id=seg.id,
            emotion=emotion,
            intensity=intensity,
            scene_type=scene_type,
            key_entities=entities,
            visual_keywords=visual_keywords,
            pacing=pacing,
        )


# ── Rule-based helpers (fallback) ───────────────────────────


def _count_keywords(text: str, keyword_set: set[str]) -> int:
    text_lower = text.lower()
    count = 0
    for kw in keyword_set:
        if kw.lower() in text_lower:
            count += 1
    return count


def _detect_emotion(text: str) -> tuple[str, float]:
    scores = {}
    for emotion, keywords in EMOTION_WORDS.items():
        count = _count_keywords(text, keywords)
        if count > 0:
            scores[emotion] = count

    if not scores:
        return "calm", 0.3

    dominant = max(scores, key=scores.get)
    max_score = max(scores.values())
    intensity = min(0.3 + (max_score - 1) * 0.3, 1.0)
    return dominant, intensity


def _detect_scene_type(text: str) -> str:
    scores = {}
    for scene_type, keywords in SCENE_WORDS.items():
        count = _count_keywords(text, keywords)
        if count > 0:
            scores[scene_type] = count
    if scores:
        return max(scores, key=scores.get)
    return "outdoor"


def _detect_pacing(text: str) -> str:
    if _count_keywords(text, PACING_WORDS["slow"]) > 0:
        return "slow"
    if _count_keywords(text, PACING_WORDS["fast"]) > 0:
        return "fast"
    return "normal"


def _extract_entities(text: str) -> list[str]:
    cleaned = re.sub(r'[，。！？；：""' "（）、\n\r\t]", " ", text)
    # Try word/phrase extraction: Chinese 2-4 chars, English 2-12 chars
    words = re.findall(r"[\u4e00-\u9fff]{2,4}|\w{2,12}", cleaned)
    return [w.strip() for w in words if 2 <= len(w.strip()) <= 12][:5]


def _extract_visual_keywords(text: str) -> list[str]:
    visual_words = {
        "黄昏",
        "dusk",
        "golden",
        "golden hour",
        "sunset",
        "sunrise",
        "雾",
        "fog",
        "mist",
        "雨",
        "rain",
        "雪",
        "snow",
        "月光",
        "moonlight",
        "烛光",
        "candlelight",
        "火焰",
        "fire",
        "阴影",
        "shadow",
        "光线",
        "light",
        "光束",
        "beam",
        "寒冷",
        "cold",
        "温暖",
        "warm",
        "黑暗",
        "dark",
        "光明",
    }
    found = []
    text_lower = text.lower()
    for w in visual_words:
        if w.lower() in text_lower:
            found.append(w)
    return found


def _segment_batches(segments: list[ScriptSegment]) -> list[list[ScriptSegment]]:
    batches: list[list[ScriptSegment]] = []
    current: list[ScriptSegment] = []
    current_chars = 0
    for seg in segments:
        seg_chars = len(seg.text) + 32
        if current and (
            len(current) >= _MAX_BATCH_SEGMENTS or current_chars + seg_chars > _MAX_BATCH_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(seg)
        current_chars += seg_chars
    if current:
        batches.append(current)
    return batches
