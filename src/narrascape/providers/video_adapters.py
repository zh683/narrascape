from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from narrascape.utils.retry import is_retryable_provider_error

logger = logging.getLogger("narrascape.providers.video")


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]: ...


class UrllibJsonTransport:
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        )
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in headers.items():
            request.add_header(name, value)
        response = json.loads(urllib.request.urlopen(request, timeout=timeout).read().decode())
        return response if isinstance(response, dict) else {}


class SeedanceVideoAdapter:
    def __init__(
        self,
        *,
        api_key: Callable[[], str | None],
        transport: JsonTransport | None = None,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3/contents/generations",
        poll_interval: float = 5.0,
        max_poll_time: float = 300.0,
        max_poll_errors: int = 3,
    ):
        self.api_key = api_key
        self.transport = transport or UrllibJsonTransport()
        self.base_url = base_url
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.max_poll_errors = max_poll_errors

    def create_task(self, payload: dict[str, Any]) -> str | None:
        key = self.api_key()
        if not key:
            logger.error("Seedance video provider selected but API key is not configured")
            return None
        try:
            response = self.transport.request_json(
                "POST",
                f"{self.base_url}/tasks",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=payload,
                timeout=60,
            )
        except Exception as exc:
            logger.error(f"Task creation failed: {exc}")
            return None
        task_id = response.get("id")
        if not task_id:
            logger.error(
                f"No task ID in response: {json.dumps(response, ensure_ascii=False)[:200]}"
            )
            return None
        logger.info(f"  Task created: {task_id}")
        return str(task_id)

    def poll(self, task_id: str) -> str | None:
        started = time.monotonic()
        attempts = 0
        consecutive_errors = 0
        while time.monotonic() - started < self.max_poll_time:
            attempts += 1
            key = self.api_key()
            if not key:
                return None
            try:
                response = self.transport.request_json(
                    "GET",
                    f"{self.base_url}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=30,
                )
            except Exception as exc:
                if not is_retryable_provider_error(exc):
                    logger.error(f"  Permanent poll error: {exc}")
                    return None
                consecutive_errors += 1
                logger.warning(f"  Poll error (attempt {attempts}): {exc}")
                if consecutive_errors >= self.max_poll_errors:
                    logger.error(f"  Polling aborted after {consecutive_errors} consecutive errors")
                    return None
                time.sleep(self.poll_interval)
                continue
            consecutive_errors = 0
            status = str(response.get("status") or "unknown")
            logger.info(f"  Poll {attempts}: status={status}")
            if status == "succeeded":
                content = response.get("content", {})
                if isinstance(content, dict) and content.get("video_url"):
                    return str(content["video_url"])
                value = response.get("video_url") or response.get("url")
                return str(value) if value else None
            if status in {"failed", "expired"}:
                logger.error(f"  Task {status}: {response.get('error', 'unknown error')}")
                return None
            time.sleep(self.poll_interval)
        logger.error(f"  Polling timeout after {self.max_poll_time}s")
        return None


class AgnesVideoAdapter:
    def __init__(
        self,
        *,
        api_key: Callable[[], str | None],
        model: Callable[[], str],
        transport: JsonTransport | None = None,
        create_url: str = "https://apihub.agnes-ai.com/v1/videos",
        result_url: str = "https://apihub.agnes-ai.com/agnesapi",
        create_timeout: float = 120,
        poll_interval: float = 5.0,
        max_poll_time: float = 300.0,
        max_poll_errors: int = 3,
    ):
        self.api_key = api_key
        self.model = model
        self.transport = transport or UrllibJsonTransport()
        self.create_url = create_url
        self.result_url = result_url
        self.create_timeout = create_timeout
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.max_poll_errors = max_poll_errors

    def create_task(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        key = self.api_key()
        if not key:
            return None, None
        try:
            response = self.transport.request_json(
                "POST",
                self.create_url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload=payload,
                timeout=self.create_timeout,
            )
        except Exception as exc:
            logger.error(f"Agnes task creation failed: {exc}")
            return None, None
        task_id = response.get("task_id") or response.get("id")
        video_id = response.get("video_id")
        if not task_id and not video_id:
            logger.error("No Agnes task_id/video_id in response")
            return None, None
        return (str(task_id) if task_id else None, str(video_id) if video_id else None)

    def poll(self, *, task_id: str | None = None, video_id: str | None = None) -> str | None:
        started = time.monotonic()
        errors = 0
        while time.monotonic() - started < self.max_poll_time:
            key = self.api_key()
            if not key:
                return None
            if video_id:
                query = urllib.parse.urlencode({"video_id": video_id, "model_name": self.model()})
                url = f"{self.result_url}?{query}"
            elif task_id:
                url = f"{self.create_url}/{task_id}"
            else:
                return None
            try:
                response = self.transport.request_json(
                    "GET", url, headers={"Authorization": f"Bearer {key}"}, timeout=30
                )
            except Exception as exc:
                if not is_retryable_provider_error(exc):
                    return None
                errors += 1
                if errors >= self.max_poll_errors:
                    return None
                time.sleep(self.poll_interval)
                continue
            errors = 0
            status = str(response.get("status") or response.get("state") or "unknown").lower()
            video_url = _extract_agnes_video_url(response)
            if video_url:
                return video_url
            if status in {"failed", "error", "cancelled", "expired"}:
                return None
            time.sleep(self.poll_interval)
        return None


def _extract_agnes_video_url(response: dict[str, Any]) -> str | None:
    value = (
        response.get("remixed_from_video_id") or response.get("video_url") or response.get("url")
    )
    if value:
        return str(value)
    data = response.get("data")
    if isinstance(data, dict):
        nested = data.get("video_url") or data.get("url")
        return str(nested) if nested else None
    return None
