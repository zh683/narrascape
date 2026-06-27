"""Unified LLM client with multi-provider support, retry, and structured output.

Supports: OpenAI, Anthropic, DeepSeek, Volcengine (Ark), and local models.
All calls automatically retry with exponential backoff.
All outputs validated against expected format with automatic re-prompting.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from narrascape.llm.models import LLMCallLog, LLMConfig, LLMResponse, Message, PromptTemplate
from narrascape.utils.retry import retry_with_backoff

logger = logging.getLogger("narrascape.llm")


ASSISTANT_BRIDGE_PROVIDERS = {"bridge", "ai_assistant"}


def is_assistant_bridge_provider(provider: str) -> bool:
    """Return True for providers that use file-based AI-assistant exchange."""
    return provider in ASSISTANT_BRIDGE_PROVIDERS


class LLMClient:
    """Unified LLM client that works across providers.

    Usage:
        client = LLMClient.from_env()  # Auto-detect from env vars
        # Or explicit:
        client = LLMClient(LLMConfig(provider="openai", model="gpt-4o", api_key="..."))

        # Simple completion
        resp = client.complete("Write a poem about stars")

        # Structured prompt
        template = PromptTemplate(
            system="You are a research analyst.",
            user="Research: {topic}",
            output_format="Return JSON: {schema}",
            chain_of_thought=True,
            reasoning_steps=["Identify key events", "Analyze significance"],
        )
        resp = client.run_template(template, topic="AI history", schema="{...}")
        data = resp.extract_json()

        # With validation - auto-retry if output doesn't match schema
        data = client.run_template_validated(template, validator=my_validator, **vars)
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._logs: list[LLMCallLog] = []
        self._provider = self._init_provider()
        self._bridge = None  # type: BridgeLLMClient | None

    @classmethod
    def from_env(cls, allow_bridge: bool = True) -> LLMClient:
        """Create LLM client from environment variables.

        Priority: AI_ASSISTANT > BRIDGE > OPENAI > DEEPSEEK > ANTHROPIC > ARK

        When no external API keys are found, defaults to AI Assistant mode
        (project-local bridge tasks processed by the current AI assistant).

        Args:
            allow_bridge: If True, allow bridge mode when NARRASCAPE_LLM_MODE=bridge
        """
        import os

        # Try AI Assistant mode first (when running in an AI assistant environment)
        if os.environ.get("NARRASCAPE_LLM_MODE", "").lower() == "ai_assistant":
            return cls(LLMConfig(provider="ai_assistant"))

        # Try bridge mode (AI assistant integration via file-based tasks)
        if allow_bridge and os.environ.get("NARRASCAPE_LLM_MODE", "").lower() == "bridge":
            return cls(LLMConfig(provider="bridge"))

        # Try OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return cls(LLMConfig(provider="openai", api_key=key, model="gpt-4o"))

        # Try DeepSeek (common in China)
        key = os.environ.get("DEEPSEEK_API_KEY")
        if key:
            base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            return cls(
                LLMConfig(provider="deepseek", api_key=key, base_url=base, model="deepseek-chat")
            )

        # Try Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return cls(
                LLMConfig(provider="anthropic", api_key=key, model="claude-3-sonnet-20240229")
            )

        # Try Volcengine / Ark
        key = os.environ.get("ARK_API_KEY")
        if key:
            base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
            model = os.environ.get("ARK_MODEL_ID", "doubao-pro-32k")
            return cls(LLMConfig(provider="openai", api_key=key, base_url=base, model=model))

        # Default: AI Assistant mode (project-local bridge tasks)
        # No external API keys needed - the AI assistant handles bridge tasks
        return cls(LLMConfig(provider="ai_assistant"))

    def _init_provider(self) -> Callable:
        """Initialize the provider-specific API client."""
        provider = self.config.provider

        if provider in ("openai", "deepseek", "volcengine"):
            return self._openai_provider
        elif provider == "anthropic":
            return self._anthropic_provider
        elif provider == "local":
            return self._local_provider
        elif provider == "bridge":
            return self._bridge_provider
        elif provider == "ai_assistant":
            return self._ai_assistant_provider
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _ai_assistant_provider(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """AI Assistant bridge provider.

        When the system is running in an AI assistant environment (like this conversation),
        the current AI assistant processes project-local task files. This is the primary mode when
        Codex, Kimi, or other AI assistants are driving the system.

        This provider uses the BridgeLLMClient to create task files and wait for the
        AI assistant to process them. No external API keys needed.
        """
        # Use bridge mechanism for real AI assistant interaction
        self._init_bridge()

        # Build full prompt from messages
        parts = []
        for m in messages:
            role_label = {"system": "System", "user": "User", "assistant": "AI"}.get(m.role, m.role)
            parts.append(f"[{role_label}]\n{m.content}")
        prompt = "\n\n".join(parts)

        logger.info("[AI Assistant] Using bridge mechanism for AI assistant interaction")
        logger.info(f"[AI Assistant] Prompt length: {len(prompt)} chars")

        # Create task file and wait for AI assistant response
        return self._bridge.complete(
            prompt, json_mode=config.json_mode, max_retries=config.max_retries
        )

    def _init_bridge(self) -> None:
        """Initialize bridge client for AI assistant integration."""
        if self._bridge is None:
            from narrascape.llm.bridge import BridgeLLMClient

            self._bridge = BridgeLLMClient()

    def _bridge_provider(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """Bridge provider that delegates to AI assistant via file-based tasks."""
        # ai_assistant and bridge are now unified — both use BridgeLLMClient
        return self._ai_assistant_provider(messages, config)

    def _bridge_complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Direct bridge completion for internal use."""
        self._init_bridge()
        return self._bridge.complete(prompt, **kwargs)

    def _bridge_chat(self, messages: list[Message], **kwargs) -> LLMResponse:
        """Direct bridge chat for internal use."""
        self._init_bridge()
        return self._bridge.chat(messages, **kwargs)

    # ── Public API ───────────────────────────

    def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Simple completion with a single user prompt."""
        messages = [Message(role="user", content=prompt)]
        return self.chat(messages, **kwargs)

    def chat(self, messages: list[Message], **kwargs) -> LLMResponse:
        """Send a chat completion request with retry."""
        config = self._merge_config(**kwargs)

        def _call():
            return self._provider(messages, config)

        # Bridge-backed assistant modes create task files; retrying creates duplicates.
        if is_assistant_bridge_provider(self.config.provider):
            return _call()

        return retry_with_backoff(
            _call,
            max_retries=config.max_retries,
            base_delay=config.retry_delay,
            retryable_exceptions=(Exception,),
            on_retry=lambda e, attempt, delay: logger.warning(
                f"LLM retry {attempt}/{config.max_retries} after {delay:.1f}s: {e}"
            ),
        )

    def run_template(self, template: PromptTemplate, **variables) -> LLMResponse:
        """Run a structured prompt template and return response."""
        messages = template.build(**variables)
        return self.chat(messages)

    def run_template_validated(
        self,
        template: PromptTemplate,
        validator: Callable[[Any], tuple[bool, str]],
        max_format_retries: int = 2,
        **variables,
    ) -> Any:
        """Run template with output validation. Auto-retry on format errors.

        Args:
            template: The prompt template to run
            validator: Function (data) -> (is_valid, error_message)
            max_format_retries: How many times to retry if output format is wrong
            **variables: Template variables

        Returns:
            Parsed and validated output

        Raises:
            ValueError: If validation fails after all retries
        """
        template_name = template.user[:50] if template.user else "unnamed"
        last_error = None

        # Bridge / AI Assistant mode: only one attempt, no retry (AI assistant handles it)
        attempts = (
            1 if is_assistant_bridge_provider(self.config.provider) else (max_format_retries + 1)
        )

        for attempt in range(attempts):
            start = time.monotonic()
            resp = self.run_template(template, **variables)
            latency = (time.monotonic() - start) * 1000

            # Try to parse JSON
            try:
                data = resp.extract_json()
            except (json.JSONDecodeError, ValueError) as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"[{template_name}] Parse failed (attempt {attempt+1}): {e}")
                self._log_call(
                    template_name,
                    template.build(**variables),
                    resp.text,
                    None,
                    False,
                    last_error,
                    latency,
                )

                # Add correction instruction for retry (only for non-bridge/ai_assistant)
                if attempt < max_format_retries and not is_assistant_bridge_provider(
                    self.config.provider
                ):
                    correction = f"\n\nYour previous response was not valid JSON. Error: {e}. Please fix the format and return ONLY valid JSON."
                    # Rebuild template with correction appended, then send directly via chat()
                    # 不创建新的 PromptTemplate，避免二次 format 导致大括号解析错误
                    messages = template.build(**variables)
                    messages[-1].content += correction
                    resp = self.chat(messages)
                    # 直接尝试从新响应中解析 JSON，不重新进入循环
                    try:
                        data = resp.extract_json()
                    except (json.JSONDecodeError, ValueError) as e2:
                        last_error = f"JSON parse error (retry): {e2}"
                        logger.warning(
                            f"[{template_name}] Retry parse failed (attempt {attempt+1}): {e2}"
                        )
                        continue
                else:
                    continue

            # Validate parsed data
            is_valid, error_msg = validator(data)
            if is_valid:
                self._log_call(
                    template_name,
                    template.build(**variables),
                    resp.text,
                    data,
                    True,
                    None,
                    latency,
                    resp.model,
                    resp.usage,
                )
                return data

            last_error = f"Validation error: {error_msg}"
            logger.warning(
                f"[{template_name}] Validation failed (attempt {attempt+1}): {error_msg}"
            )
            self._log_call(
                template_name,
                template.build(**variables),
                resp.text,
                data,
                False,
                last_error,
                latency,
                resp.model,
                resp.usage,
            )

            # Add correction instruction for retry (only for non-bridge/ai_assistant)
            if attempt < max_format_retries and not is_assistant_bridge_provider(
                self.config.provider
            ):
                correction = f"\n\nYour previous response had validation errors: {error_msg}. Please correct these issues and return valid JSON."
                # 不创建新的 PromptTemplate，避免二次 format 导致大括号解析错误
                messages = template.build(**variables)
                messages[-1].content += correction
                resp = self.chat(messages)
                # 直接尝试从新响应中解析 JSON 并验证
                try:
                    data = resp.extract_json()
                except (json.JSONDecodeError, ValueError) as e2:
                    last_error = f"JSON parse error (retry): {e2}"
                    logger.warning(
                        f"[{template_name}] Retry parse failed (attempt {attempt+1}): {e2}"
                    )
                    continue
                is_valid, error_msg = validator(data)
                if is_valid:
                    self._log_call(
                        template_name,
                        template.build(**variables),
                        resp.text,
                        data,
                        True,
                        None,
                        latency,
                        resp.model,
                        resp.usage,
                    )
                    return data
                last_error = f"Validation error (retry): {error_msg}"
                logger.warning(
                    f"[{template_name}] Retry validation failed (attempt {attempt+1}): {error_msg}"
                )

        raise ValueError(
            f"LLM output validation failed after {attempts} attempts. Last error: {last_error}"
        )

    def get_logs(self) -> list[LLMCallLog]:
        """Get all LLM call logs for debugging."""
        return self._logs.copy()

    def clear_logs(self) -> None:
        """Clear LLM call logs."""
        self._logs.clear()

    # ── Internal: Provider implementations ───────────────────────────

    def _openai_provider(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """OpenAI-compatible API (also works for DeepSeek, Volcengine/Ark)."""
        try:
            import openai
        except ImportError:
            return self._openai_fallback_http(messages, config)

        client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)

        kwargs = {
            "model": config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "top_p": config.top_p,
            "timeout": config.timeout,
        }

        if config.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)

        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=resp.model or config.model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            },
            finish_reason=resp.choices[0].finish_reason,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    def _openai_fallback_http(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """Fallback HTTP implementation when openai package is not installed."""
        import urllib.error
        import urllib.request

        url = f"{config.base_url or 'https://api.openai.com/v1'}/chat/completions"
        payload = {
            "model": config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "top_p": config.top_p,
        }

        if config.json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {config.api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=int(config.timeout)) as resp:
            result = json.loads(resp.read().decode())

        choice = result["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=result.get("model", config.model),
            usage=result.get("usage", {}),
            finish_reason=choice.get("finish_reason"),
            raw=result,
        )

    def _anthropic_provider(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """Anthropic Claude API."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

        client = anthropic.Anthropic(api_key=config.api_key)

        # Separate system from other messages
        system_msg = None
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
        }
        if system_msg:
            kwargs["system"] = system_msg

        resp = client.messages.create(**kwargs)

        return LLMResponse(
            content=resp.content[0].text if resp.content else "",
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.input_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.output_tokens if resp.usage else 0,
                "total_tokens": (
                    (resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else 0
                ),
            },
            finish_reason=resp.stop_reason,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    def _local_provider(self, messages: list[Message], config: LLMConfig) -> LLMResponse:
        """Local model via HTTP API (llama.cpp, ollama, etc.)."""
        import urllib.request

        url = config.base_url or "http://localhost:8000/v1/chat/completions"
        payload = {
            "model": config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=int(config.timeout)) as resp:
            result = json.loads(resp.read().decode())

        choice = result["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=result.get("model", config.model),
            usage=result.get("usage", {}),
            finish_reason=choice.get("finish_reason"),
            raw=result,
        )

    # ── Helpers ───────────────────────────

    def _merge_config(self, **kwargs) -> LLMConfig:
        """Create a config copy with runtime overrides."""
        return self.config.copy(**kwargs)

    def _log_call(
        self,
        template_name: str,
        messages: list[Message],
        response: str,
        parsed_output: Any,
        success: bool,
        error: str | None,
        latency_ms: float,
        model: str = "",
        usage: dict | None = None,
    ) -> None:
        """Log an LLM call for debugging."""
        from datetime import datetime

        log = LLMCallLog(
            timestamp=datetime.now().isoformat(),
            template_name=template_name,
            messages=[m.to_dict() for m in messages],
            response=response,
            parsed_output=parsed_output,
            success=success,
            error=error,
            latency_ms=latency_ms,
            model=model,
            usage=usage or {},
        )
        self._logs.append(log)
