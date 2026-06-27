"""Narrascape LLM module — unified LLM client with structured prompting.

Provides:
- Multi-provider LLM client (OpenAI, Anthropic, DeepSeek, Volcengine, local)
- Structured prompt templates with Chain-of-Thought and few-shot support
- Automatic output validation and retry on format errors
- Call logging for debugging and prompt optimization

Usage:
    from narrascape.llm import LLMClient, LLMConfig, PromptTemplate
    from narrascape.llm.prompts import get_prompt

    # Create client from environment
    client = LLMClient.from_env()

    # Or explicit configuration
    client = LLMClient(LLMConfig(
        provider="openai",
        model="gpt-4o",
        api_key="...",
        temperature=0.7,
        json_mode=True,
    ))

    # Use a pre-built prompt template
    template = get_prompt("research")
    data = client.run_template_validated(
        template,
        validator=OutputValidator.has_keys("topic", "findings"),
        topic="AI history",
        depth="standard",
    )

    # Or build custom template
    from narrascape.llm.models import PromptTemplate
    template = PromptTemplate(
        system="You are a research analyst.",
        user="Research: {topic}",
        chain_of_thought=True,
        reasoning_steps=["Identify key events", "Analyze significance"],
        output_format="Return JSON: {schema}",
    )
    resp = client.run_template(template, topic="AI", schema="...")
"""

from narrascape.llm.bridge import BridgeLLMClient, get_bridge_client, is_bridge_mode
from narrascape.llm.client import LLMClient, is_assistant_bridge_provider
from narrascape.llm.models import LLMCallLog, LLMConfig, LLMResponse, Message, PromptTemplate
from narrascape.llm.output_parser import JSONRepair, OutputValidator
from narrascape.llm.prompts import PROMPT_REGISTRY, get_prompt

__all__ = [
    "LLMClient",
    "is_assistant_bridge_provider",
    "LLMConfig",
    "LLMResponse",
    "Message",
    "PromptTemplate",
    "LLMCallLog",
    "OutputValidator",
    "JSONRepair",
    "get_prompt",
    "PROMPT_REGISTRY",
    "BridgeLLMClient",
    "is_bridge_mode",
    "get_bridge_client",
]
