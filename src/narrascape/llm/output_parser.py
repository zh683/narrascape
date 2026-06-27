"""Output parsing and validation for LLM responses.

Provides automatic extraction, validation, and correction for structured LLM outputs.
All validators return (is_valid, error_message) tuples.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("narrascape.llm.output_parser")


class OutputValidator:
    """Collection of common output validators."""

    @staticmethod
    def has_keys(*required_keys: str) -> Callable[[Any], tuple[bool, str]]:
        """Create a validator that checks for required keys in a dict."""

        def validator(data: Any) -> tuple[bool, str]:
            if not isinstance(data, dict):
                return False, f"Expected dict, got {type(data).__name__}"
            missing = [k for k in required_keys if k not in data]
            if missing:
                return False, f"Missing required keys: {missing}"
            return True, ""

        return validator

    @staticmethod
    def has_nested_keys(path: str, *required_keys: str) -> Callable[[Any], tuple[bool, str]]:
        """Check for keys in a nested path (e.g., 'segments' -> 'id', 'text')."""

        def validator(data: Any) -> tuple[bool, str]:
            if not isinstance(data, dict):
                return False, f"Expected dict, got {type(data).__name__}"
            nested = data.get(path)
            if not isinstance(nested, list):
                return False, f"Expected list at '{path}', got {type(nested).__name__}"
            for i, item in enumerate(nested):
                if not isinstance(item, dict):
                    return False, f"Item {i} in '{path}' is not a dict"
                missing = [k for k in required_keys if k not in item]
                if missing:
                    return False, f"Item {i} in '{path}' missing keys: {missing}"
            return True, ""

        return validator

    @staticmethod
    def type_check(field: str, expected_type: type) -> Callable[[Any], tuple[bool, str]]:
        """Check that a field has the expected type."""

        def validator(data: Any) -> tuple[bool, str]:
            if not isinstance(data, dict):
                return False, f"Expected dict, got {type(data).__name__}"
            if field not in data:
                return True, ""  # Skip if missing (use has_keys for that)
            value = data[field]
            if not isinstance(value, expected_type):
                return (
                    False,
                    f"Field '{field}' expected {expected_type.__name__}, got {type(value).__name__}",
                )
            return True, ""

        return validator

    @staticmethod
    def range_check(
        field: str, min_val: float, max_val: float
    ) -> Callable[[Any], tuple[bool, str]]:
        """Check that a numeric field is within range."""

        def validator(data: Any) -> tuple[bool, str]:
            if not isinstance(data, dict):
                return False, f"Expected dict, got {type(data).__name__}"
            if field not in data:
                return True, ""
            value = data[field]
            try:
                num = float(value)
                if not (min_val <= num <= max_val):
                    return False, f"Field '{field}' value {num} not in range [{min_val}, {max_val}]"
            except (TypeError, ValueError):
                return False, f"Field '{field}' is not numeric: {value}"
            return True, ""

        return validator

    @staticmethod
    def non_empty(field: str) -> Callable[[Any], tuple[bool, str]]:
        """Check that a string field is not empty."""

        def validator(data: Any) -> tuple[bool, str]:
            if not isinstance(data, dict):
                return False, f"Expected dict, got {type(data).__name__}"
            if field not in data:
                return True, ""
            value = data[field]
            if isinstance(value, str) and not value.strip():
                return False, f"Field '{field}' is empty"
            if isinstance(value, list) and len(value) == 0:
                return False, f"Field '{field}' is empty list"
            return True, ""

        return validator

    @staticmethod
    def combine(
        *validators: Callable[[Any], tuple[bool, str]]
    ) -> Callable[[Any], tuple[bool, str]]:
        """Combine multiple validators into one."""

        def validator(data: Any) -> tuple[bool, str]:
            for v in validators:
                is_valid, error = v(data)
                if not is_valid:
                    return False, error
            return True, ""

        return validator


class JSONRepair:
    """Attempt to repair common JSON parsing errors from LLM outputs."""

    @staticmethod
    def repair(text: str) -> str:
        """Apply common JSON repair techniques."""
        original = text.strip()

        # Remove markdown fences
        if "```json" in original:
            original = original.split("```json")[1].split("```")[0].strip()
        elif "```" in original:
            original = original.split("```")[1].split("```")[0].strip()

        # Remove trailing commas before } or ]
        import re

        result = re.sub(r",(\s*[}\]])", r"\1", original)

        # Fix single quotes to double quotes (common LLM error)
        # Only for simple cases - this is risky
        # result = re.sub(r"(?<!\\)'(.*?)(?<!\\)'", r'"\1"', result)

        # Add missing outer braces if it looks like a dict
        if result.startswith('"') and not result.startswith('{"'):
            result = "{" + result
        if result.count("{") > result.count("}"):
            result += "}" * (result.count("{") - result.count("}"))
        if result.count("[") > result.count("]"):
            result += "]" * (result.count("[") - result.count("]"))

        return result

    @staticmethod
    def extract_json_object(text: str) -> str:
        """Extract the first JSON object from text."""
        import re

        # Try to find JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)

        # Try to find JSON array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return match.group(0)

        return text
