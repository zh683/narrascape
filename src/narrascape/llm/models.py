"""LLM module data models.

Unified data structures for LLM interactions across all providers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    """A single message in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None  # For tool messages

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class LLMConfig:
    """Configuration for LLM client."""

    provider: Literal[
        "openai", "anthropic", "deepseek", "volcengine", "local", "bridge", "ai_assistant"
    ] = "openai"
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 1.0
    timeout: float = 120.0
    max_retries: int = 3
    retry_delay: float = 2.0
    system_prompt: str | None = None
    json_mode: bool = False  # Force JSON output if provider supports it

    def copy(self, **overrides) -> LLMConfig:
        """Create a copy with overrides."""
        return LLMConfig(
            provider=overrides.get("provider", self.provider),
            model=overrides.get("model", self.model),
            api_key=overrides.get("api_key", self.api_key),
            base_url=overrides.get("base_url", self.base_url),
            temperature=overrides.get("temperature", self.temperature),
            max_tokens=overrides.get("max_tokens", self.max_tokens),
            top_p=overrides.get("top_p", self.top_p),
            timeout=overrides.get("timeout", self.timeout),
            max_retries=overrides.get("max_retries", self.max_retries),
            retry_delay=overrides.get("retry_delay", self.retry_delay),
            system_prompt=overrides.get("system_prompt", self.system_prompt),
            json_mode=overrides.get("json_mode", self.json_mode),
        )


@dataclass
class LLMResponse:
    """Structured response from LLM."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    raw: dict | None = None  # Provider-specific raw response

    @property
    def text(self) -> str:
        """Alias for content."""
        return self.content

    def extract_json(self) -> Any:
        """Extract JSON from response content, handling markdown fences."""
        raw = self.content.strip()
        candidates = list(_json_candidates(raw))
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                last_error = e
        if last_error:
            raise last_error
        return json.loads(raw)

    def extract_json_safe(self, default: Any = None) -> Any:
        """Safely extract JSON, returning default on failure."""
        try:
            return self.extract_json()
        except (json.JSONDecodeError, ValueError):
            return default


def _json_candidates(text: str) -> list[str]:
    """Return likely JSON substrings without assuming one exact fence format."""
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

    lines = text.splitlines()
    in_fence = False
    fence_lang = ""
    block: list[str] = []
    for line in lines:
        marker = line.strip()
        if marker.startswith("```"):
            if in_fence:
                if not fence_lang or "json" in fence_lang.lower():
                    candidate = "\n".join(block).strip()
                    if candidate:
                        candidates.append(candidate)
                in_fence = False
                fence_lang = ""
                block = []
            else:
                in_fence = True
                fence_lang = marker[3:].strip()
                block = []
            continue
        if in_fence:
            block.append(line)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            candidates.append(stripped[start : end + 1])

    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


@dataclass
class PromptTemplate:
    """A structured prompt template with variable substitution."""

    system: str | None = None
    user: str = ""
    few_shot_examples: list[tuple[str, str]] = field(default_factory=list)
    output_format: str | None = None
    chain_of_thought: bool = False
    reasoning_steps: list[str] | None = None

    def build(self, **variables) -> list[Message]:
        """Build a list of messages from template and variables."""
        messages = []

        # Auto-inject reasoning_steps for template placeholders
        local_vars = dict(variables)
        if self.chain_of_thought and self.reasoning_steps:
            formatted_steps = "\n".join(
                f"{i}. {step.format(**local_vars)}"
                for i, step in enumerate(self.reasoning_steps, 1)
            )
            local_vars.setdefault("reasoning_steps", formatted_steps)

        # System prompt
        if self.system:
            system_text = self.system.format(**local_vars)
            messages.append(Message(role="system", content=system_text))

        # Few-shot examples
        for user_msg, assistant_msg in self.few_shot_examples:
            messages.append(Message(role="user", content=user_msg.format(**local_vars)))
            messages.append(Message(role="assistant", content=assistant_msg.format(**local_vars)))

        # User prompt with CoT if enabled
        try:
            user_text = self.user.format(**local_vars)
        except KeyError as e:
            print(f"MODELS DEBUG: KeyError {e}")
            print(f"MODELS DEBUG: self id={id(self)}")
            print(f"MODELS DEBUG: user type={type(self.user)}")
            print(f"MODELS DEBUG: user id={id(self.user)}")
            print(f"MODELS DEBUG: user len={len(self.user)}")
            print(f"MODELS DEBUG: user[:200]={repr(self.user[:200])}")
            print(f"MODELS DEBUG: local_vars keys={sorted(local_vars.keys())}")
            for k in sorted(local_vars.keys()):
                v = local_vars[k]
                print(
                    f"MODELS DEBUG: {k} type={type(v).__name__} len={len(str(v))} has_brace={('{' in str(v) or '}' in str(v))}"
                )
            # Compare with all known templates
            from narrascape.llm.prompts import (
                ANALYZER_PROMPT,
                COMPACT_SHOT_DESIGN_PROMPT,
                SHOT_DESIGN_PROMPT,
            )

            for name, tmpl in [
                ("SHOT", SHOT_DESIGN_PROMPT),
                ("COMPACT", COMPACT_SHOT_DESIGN_PROMPT),
                ("ANALYZER", ANALYZER_PROMPT),
            ]:
                print(f"MODELS DEBUG: {name} id={id(tmpl)} self is {name}: {self is tmpl}")
                print(f"MODELS DEBUG: {name}.user len={len(tmpl.user)}")
            raise

        if self.chain_of_thought and self.reasoning_steps:
            # Only append if reasoning_steps wasn't already embedded in user template
            if "{reasoning_steps}" not in self.user:
                user_text += (
                    "\n\nBefore giving your final answer, think through this step by step:\n"
                )
                for i, step in enumerate(self.reasoning_steps, 1):
                    user_text += f"\n{i}. {step.format(**local_vars)}"

        # Output format instruction
        if self.output_format:
            user_text += f"\n\n{self.output_format}"

        messages.append(Message(role="user", content=user_text))
        return messages

    def with_examples(self, examples: list[tuple[str, str]]) -> PromptTemplate:
        """Return a new template with additional few-shot examples."""
        return PromptTemplate(
            system=self.system,
            user=self.user,
            few_shot_examples=self.few_shot_examples + examples,
            output_format=self.output_format,
            chain_of_thought=self.chain_of_thought,
            reasoning_steps=self.reasoning_steps,
        )

    def with_cot(self, steps: list[str]) -> PromptTemplate:
        """Return a new template with Chain-of-Thought reasoning steps."""
        return PromptTemplate(
            system=self.system,
            user=self.user,
            few_shot_examples=self.few_shot_examples,
            output_format=self.output_format,
            chain_of_thought=True,
            reasoning_steps=steps,
        )


@dataclass
class LLMCallLog:
    """Log of an LLM call for debugging and optimization."""

    timestamp: str
    template_name: str
    messages: list[dict]
    response: str
    parsed_output: Any
    success: bool
    error: str | None = None
    latency_ms: float = 0.0
    model: str = ""
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "template_name": self.template_name,
            "messages": self.messages,
            "response": self.response[:500] if len(self.response) > 500 else self.response,
            "parsed_output": self.parsed_output,
            "success": self.success,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "usage": self.usage,
        }
