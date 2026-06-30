"""Humanizer — removes AI writing patterns from Chinese text.

Two modes:
1. LLM mode (preferred): Uses structured prompting to rewrite text authentically
2. Rule-based fallback: Regex pattern replacement when LLM is unavailable

The LLM approach understands context and preserves meaning while removing AI
patterns. The rule-based approach is a faster but less nuanced fallback.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, TypedDict

from narrascape.llm import LLMClient
from narrascape.llm.prompts import get_prompt

logger = logging.getLogger("narrascape.humanizer")


# ═══════════════════════════════════════════════════════════
# AI Pattern Detection Rules (fallback only)
# ═══════════════════════════════════════════════════════════


class HumanizerScore(TypedDict):
    ai_likeness: float
    ai_markers: int
    three_part_lists: int
    sentence_variance: float
    verdict: str


AI_PATTERNS: list[tuple[str, str | Callable[[re.Match[str]], str]]] = [
    # 1. Filler phrases
    (r"为了实.*?这一目标", "为了这一点"),
    (r"由于.*?的事实", "因为"),
    (r"在这个时间点", "现在"),
    (r"值得注意的是", ""),
    (r"系统具有处理的能力", "系统可以处理"),
    (r"可以潜在地可能被认为", ""),
    # 2. AI vocabulary
    (r"此外，", ""),
    (r"此外", ""),
    (r"与.*?保持一致", ""),
    (r"至关重要", "很重要"),
    (r"深入探讨", "看看"),
    (r"强调", "说"),
    (r"持久的", "长久的"),
    (r"增强", "加强"),
    (r"培养", "养成"),
    (r"获得", "得到"),
    (r"突出", "表现"),
    (r"复杂.*?性", "复杂"),
    (r"关键.*?性的", "关键"),
    (r"格局", "局面"),
    (r"展示", "展现"),
    (r"宝贵的", "珍贵"),
    (r"充满活力的", "有活力的"),
    # 3. Grandiose symbolism
    (r"标志着.*?关键时刻", "是一个重要时刻"),
    (r"是.*?的体现", "体现了"),
    (r"见证了", "经历了"),
    (r"是.*?的证明", "证明了"),
    (r"极其重要的", "很重要"),
    (r"核心的", "关键"),
    (r"关键性的作用", "关键作用"),
    (r"彰显了.*?重要性", "显示了"),
    (r"反映了更广泛的", "反映了"),
    (r"象征着.*?持续", "象征"),
    (r"为.*?做出贡献", "贡献于"),
    (r"为.*?奠定基础", "奠定了"),
    (r"标志着.*?转变", "标志"),
    (r"不可磨灭的印记", "深刻印象"),
    (r"深深植根于", "根植于"),
    # 4. Propaganda language
    (r"拥有丰富的", "有"),
    (r"充满活力的", "有活力的"),
    (r"深刻的", "深的"),
    (r"令人叹为观止的", "惊人的"),
    (r"必游之地", "值得去的地方"),
    (r"迷人的", "吸引人的"),
    (r"坐落于", "位于"),
    (r"位于.*?的中心", "在"),
    (r"开创性的", "创新的"),
    (r"著名的", "有名的"),
    # 5. Vague attribution
    (r"行业报告显示", ""),
    (r"观察者指出", ""),
    (r"专家认为", ""),
    (r"一些批评者认为", ""),
    (r"多个来源指出", ""),
    # 6. Challenge formula
    (r"尽管.*?面临若干挑战", ""),
    (r"尽管存在这些挑战", ""),
    (r"挑战与遗产", ""),
    (r"未来展望", ""),
    # 7. Copula avoidance
    (r"作为.*?的", "是"),
    (r"充当.*?的", "是"),
    (r"代表.*?的", "是"),
    (r"拥有", "有"),
    (r"设有", "有"),
    # 8. Negative parallelism
    (r"这不仅仅.*?而是", ""),
    (r"不仅.*?而且", ""),
    (r"不只是.*?更是", ""),
    # 9. Overused connectives
    (r"然而，", "不过"),
    (r"因此，", "所以"),
    (r"综上所述", ""),
    (r"总而言之", ""),
    (r"从这个角度来看", ""),
    (r"就.*?而言", ""),
    # 10. Dashes overuse
    (r"——", "，"),
    (r"—", "，"),
    # 11. Three-part lists (generic)
    (r"无缝、直观和强大", ""),
    (r"创新、灵感和行业洞察", ""),
    # 12. -ing superficial analysis
    (r"突出.*?了", "表现了"),
    (r"强调.*?了", "说明了"),
    (r"反映.*?了", "反映了"),
    (r"为.*?做出贡献", "贡献"),
    (r"培养.*?了", "培养了"),
    (r"涵盖.*?了", "涵盖"),
    (r"展示.*?了", "展示"),
    # 13. Collaboration traces
    (r"希望这对您有帮助", ""),
    (r"当然！", ""),
    (r"请告诉我", ""),
    (r"这是一个.*", ""),
    # 14. Knowledge cutoff
    (r"截至.*?，", ""),
    (r"根据我最后的训练更新", ""),
    (r"虽然具体细节有限", ""),
    (r"基于可用信息", ""),
    # 15. Flattery
    (r"好问题！", ""),
    (r"您说得完全正确", ""),
    (r"这是一个很好的观点", ""),
    # 16. Generic positive conclusion
    (r"未来看起来光明", ""),
    (r"激动人心的时代即将到来", ""),
    (r"向正确方向迈出的重要一步", ""),
    (r"继续追求卓越", ""),
    (r"不可或缺的一部分", ""),
    # 17. Empty intensifiers
    (r"非常地", "很"),
    (r"相当地", "比较"),
    (r"极其地", "非常"),
    (r"相当地", ""),
    (r"相当地", ""),
]


# ═══════════════════════════════════════════════════════════
# Humanizer Engine
# ═══════════════════════════════════════════════════════════


class HumanizerEngine:
    """AI pattern remover with LLM-first and rule-based fallback.

    Two modes:
    1. LLM mode (preferred): Uses structured prompting to rewrite text authentically.
       The LLM understands context, preserves meaning, and removes AI patterns
       without destroying semantics.
    2. Rule-based fallback: Regex pattern replacement when LLM is unavailable.
       Faster but less nuanced — may cause semantic damage.
    """

    def __init__(self, llm_client: Any = None, aggressive: bool = False):
        self.llm_client = llm_client
        self.aggressive = aggressive
        self.patterns = AI_PATTERNS

    def humanize(self, text: str) -> str:
        """Remove AI patterns from text.

        LLM-first: if LLMClient is available, use structured prompting.
        Fallback: apply regex rules if LLM is unavailable or fails.
        """
        # ── LLM Mode (preferred) ──
        if self.llm_client and isinstance(self.llm_client, LLMClient):
            try:
                return self._llm_humanize(text)
            except Exception as e:
                logger.warning(f"LLM humanization failed: {e}, falling back to rules")

        # ── Rule-based Fallback ──
        return self._rule_humanize(text)

    def _llm_humanize(self, text: str) -> str:
        """Use structured LLM prompting to remove AI patterns."""
        template = get_prompt("humanizer")

        resp = self.llm_client.run_template(template, text=text)
        result = str(resp.text).strip().strip('"').strip("'")

        if not result:
            raise ValueError("LLM returned empty humanization")

        logger.info(f"[humanizer] LLM humanized {len(text)} chars → {len(result)} chars")
        return result

    def _rule_humanize(self, text: str) -> str:
        """Rule-based fallback when LLM is unavailable."""
        original = text
        result = text

        # Pass 1: Apply all regex patterns
        for pattern, replacement in self.patterns:
            if isinstance(replacement, str):
                result = re.sub(pattern, replacement, result)
            else:
                result = re.sub(pattern, replacement, result)

        # Pass 2: Clean up whitespace and punctuation
        result = self._cleanup(result)

        # Pass 3: Inject rhythm variation (if aggressive)
        if self.aggressive:
            result = self._inject_rhythm(result)

        # Pass 4: Final polish
        result = self._final_polish(result)

        changes = original != result
        if changes:
            logger.info(f"[humanizer] Applied {len(self.patterns)} rules, text changed")
        else:
            logger.info("[humanizer] No AI patterns detected")

        return result

    def humanize_script(self, script_text: str) -> str:
        """Humanize a full script.yaml content."""
        import yaml

        try:
            data = yaml.safe_load(script_text)
            if "segments" not in data:
                return self.humanize(script_text)

            for seg in data["segments"]:
                if "text" in seg:
                    seg["text"] = self.humanize(seg["text"])

            return yaml.dump(data, allow_unicode=True, sort_keys=False, width=120)
        except Exception:
            # If YAML parse fails, just humanize raw text
            return self.humanize(script_text)

    def _cleanup(self, text: str) -> str:
        """Clean up formatting artifacts."""
        # Remove extra commas
        text = re.sub(r"，+", "，", text)
        text = re.sub(r"，+", "，", text)
        # Remove extra spaces
        text = re.sub(r"  +", " ", text)
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines)

    def _inject_rhythm(self, text: str) -> str:
        """Inject sentence length variation for human-like rhythm."""
        sentences = re.split(r"([。！？])", text)
        result = []
        for i, s in enumerate(sentences):
            if s in "。！？":
                result.append(s)
            elif len(s) > 40 and i % 3 == 0:
                # Occasionally break long sentences
                mid = len(s) // 2
                # Find nearest comma
                comma = s.find("，", mid - 10, mid + 10)
                if comma > 0:
                    result.append(s[:comma] + "。")
                    result.append(s[comma + 1 :])
                else:
                    result.append(s)
            else:
                result.append(s)
        return "".join(result)

    def _final_polish(self, text: str) -> str:
        """Final polish pass."""
        # Remove leading/trailing punctuation
        text = text.strip("，。！？ \n")
        # Ensure text ends with proper punctuation
        if text and text[-1] not in "。！？":
            text += "。"
        return text

    def score(self, text: str) -> HumanizerScore:
        """Score text on AI-likeness (0-10, lower is better)."""
        ai_markers = 0
        for pattern, _ in self.patterns:
            if re.search(pattern, text):
                ai_markers += 1

        # Count repeated sentence structures
        sentences = re.split(r"[。！？]", text)
        sentence_lengths = [len(s) for s in sentences if s.strip()]
        length_variance = 0.0
        if len(sentence_lengths) > 1:
            avg = sum(sentence_lengths) / len(sentence_lengths)
            variance = sum((l - avg) ** 2 for l in sentence_lengths) / len(sentence_lengths)
            length_variance = min(variance / 100, 10)  # normalize

        # Check for three-part lists
        three_part = len(re.findall(r".*?、.*?和.*?", text))

        # Score: 0 = very human, 10 = very AI
        ai_score = min(ai_markers * 0.5 + three_part * 2 - length_variance * 0.5, 10)
        ai_score = max(ai_score, 0)

        return {
            "ai_likeness": round(ai_score, 1),
            "ai_markers": ai_markers,
            "three_part_lists": three_part,
            "sentence_variance": round(length_variance, 1),
            "verdict": "AI-like" if ai_score > 5 else "Human-like" if ai_score < 2 else "Mixed",
        }
