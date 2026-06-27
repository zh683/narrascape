"""Bridge LLM client for AI assistant integration (e.g., Codex, Copilot).

When external LLM APIs are not available, this client allows AI assistants
to act as the LLM by reading/writing structured task files.

Usage:
    # In narrascape:
    client = BridgeLLMClient(task_dir=Path(".narrascape/bridge"))
    resp = client.complete("Design shots for this script...")
    
    # AI assistant reads task file, writes response file
    # System reads response and continues

Environment:
    NARRASCAPE_BRIDGE_DIR - Directory for task/response files
    NARRASCAPE_BRIDGE_TIMEOUT - Max seconds to wait for response (default: 300)
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any

from narrascape.llm.models import LLMConfig, LLMResponse, Message, PromptTemplate

logger = logging.getLogger("narrascape.llm.bridge")


class BridgeLLMClient:
    """Bridge client that communicates with AI assistants via files.

    Workflow:
    1. System writes a task file (markdown with JSON schema)
    2. AI assistant reads task, generates response
    3. AI assistant writes response file (JSON)
    4. System reads response and returns LLMResponse

    This enables Codex/Copilot and other AI tools to act as the LLM
    without requiring external API keys.
    """

    def __init__(self, task_dir: Path | None = None, timeout: int = 300):
        """
        Args:
            task_dir: Directory for task/response files. Defaults to .narrascape/bridge
            timeout: Max seconds to wait for AI assistant response
        """
        if task_dir is None:
            task_dir = Path(os.environ.get("NARRASCAPE_BRIDGE_DIR", ".narrascape/bridge"))
        self.task_dir = Path(task_dir)
        self.pending_dir = self.task_dir / "pending"
        self.completed_dir = self.task_dir / "completed"
        self.timeout = int(os.environ.get("NARRASCAPE_BRIDGE_TIMEOUT", timeout))
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create bridge directories."""
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)

    def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Submit a task and wait for AI assistant response."""
        messages = [Message(role="user", content=prompt)]
        return self.chat(messages, **kwargs)

    def chat(self, messages: list[Message], **kwargs) -> LLMResponse:
        """Submit a chat task and wait for AI assistant response."""
        # Build the full conversation
        conversation = []
        for msg in messages:
            role_label = {"system": "System", "user": "User", "assistant": "AI"}.get(msg.role, msg.role)
            conversation.append(f"## {role_label}\n\n{msg.content}")
        
        conversation_text = "\n\n".join(conversation)
        
        # Determine expected output format
        json_mode = kwargs.get("json_mode", False)
        schema_hint = kwargs.get("schema_hint", "")
        task_id = self._task_id(conversation_text, json_mode, schema_hint)
        
        # Write task file
        task_file = self.pending_dir / f"task_{task_id}.md"
        task_content = self._format_task(task_id, conversation_text, json_mode, schema_hint)
        task_file.write_text(task_content, encoding="utf-8")
        
        logger.info(f"[bridge] Task created: {task_file}")
        logger.info(f"[bridge] Waiting for AI assistant response... (timeout={self.timeout}s)")
        
        # Log instructions for the AI assistant
        self._log_instructions(task_id, task_file)
        
        # Wait for response
        response_file = self.completed_dir / f"response_{task_id}.json"
        start = time.monotonic()
        
        existing_response = self._read_response(task_id, task_file, response_file)
        if existing_response:
            return existing_response

        while time.monotonic() - start < self.timeout:
            response = self._read_response(task_id, task_file, response_file)
            if response:
                return response
            time.sleep(1)
        
        # Timeout
        raise RuntimeError(
            f"Bridge timeout: AI assistant did not respond within {self.timeout}s.\n"
            f"Task file: {task_file}\n"
            f"Please ask your AI assistant to process this task and write the response "
            f"to {self.completed_dir}/response_{task_id}.json"
        )

    def run_template(self, template: PromptTemplate, **variables) -> LLMResponse:
        """Run a template and return response via bridge."""
        messages = template.build(**variables)
        return self.chat(messages)

    def run_template_validated(self, template, validator, max_format_retries=2, **variables):
        """Run template with validation via bridge."""
        # For bridge, we do a single pass and let the AI handle it
        return self.run_template(template, **variables)

    def _read_response(
        self,
        task_id: str,
        task_file: Path,
        response_file: Path,
    ) -> LLMResponse | None:
        """Read and archive a completed response if it exists."""
        if not response_file.exists():
            return None
        try:
            data = json.loads(response_file.read_text(encoding="utf-8"))
            archive_dir = self.task_dir / "archive"
            archive_dir.mkdir(exist_ok=True)
            if task_file.exists():
                task_file.rename(archive_dir / task_file.name)
            response_file.rename(archive_dir / response_file.name)

            logger.info(f"[bridge] Response received for task {task_id}")
            return LLMResponse(
                content=data.get("content", ""),
                model="bridge-ai-assistant",
                usage=data.get("usage", {}),
                raw=data,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[bridge] Invalid response file: {e}")
            raise RuntimeError(
                f"AI assistant response file is invalid. Please ensure the response "
                f"file at {response_file} follows the expected JSON format."
            )

    def _task_id(self, conversation: str, json_mode: bool, schema_hint: str) -> str:
        """Return a stable task id so timed-out tasks can be resumed."""
        payload = json.dumps(
            {
                "conversation": conversation,
                "json_mode": json_mode,
                "schema_hint": schema_hint,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def _format_task(self, task_id: str, conversation: str, json_mode: bool, schema_hint: str) -> str:
        """Format a task file for the AI assistant."""
        output_format = "```json\n{...}\n```" if json_mode else "natural language text"
        
        return f"""# Narrascape AI Assistant Task — ID: {task_id}

## Your Role
You are the AI Director for a video production pipeline. You are being asked to perform a creative design task that will be consumed by an automated system.

## Task
{conversation}

## Output Format
Please respond in the following format:

{output_format}

## Instructions
1. Read the task carefully
2. Generate the best possible creative response
3. Write your response to:
   `{self.completed_dir}/response_{task_id}.json`

The JSON file must have this structure:
```json
{{
  "content": "your full response here",
  "usage": {{"prompt_tokens": 0, "completion_tokens": 0}}
}}
```

{schema_hint}

## Notes
- Be specific and detailed in your response
- Use cinematic/photographic terminology where appropriate
- The response will be parsed automatically, so ensure valid JSON
"""

    def _log_instructions(self, task_id: str, task_file: Path) -> None:
        """Log instructions for the user/AI assistant."""
        logger.info("=" * 60)
        logger.info("[bridge] AI ASSISTANT TASK CREATED")
        logger.info("=" * 60)
        logger.info(f"Task ID: {task_id}")
        logger.info(f"Task file: {task_file}")
        logger.info(f"Response should be written to: {self.completed_dir}/response_{task_id}.json")
        logger.info("If you are an AI assistant, please process this task and write the response.")
        logger.info("If you are a human user, you can ask your AI assistant to handle this task.")
        logger.info("=" * 60)


# Helper: Check if bridge mode is requested
def is_bridge_mode() -> bool:
    """Check if bridge mode is enabled via environment."""
    return os.environ.get("NARRASCAPE_LLM_MODE", "").lower() == "bridge"


def get_bridge_client() -> BridgeLLMClient | None:
    """Create bridge client if bridge mode is enabled."""
    if is_bridge_mode():
        return BridgeLLMClient()
    return None
