#!/usr/bin/env python3
"""Tests for LLM token usage accounting into the budget tracker."""

from __future__ import annotations

import json

from narrascape.config import NarrascapeConfig, ProjectConfig
from narrascape.llm import LLMClient, LLMConfig, LLMResponse, Message
from narrascape.pipeline import Pipeline


def _client(provider: str = "openai", model: str = "gpt-4o") -> LLMClient:
    return LLMClient(LLMConfig(provider=provider, api_key="fake", model=model))


def _mock_provider(client: LLMClient, monkeypatch, response: LLMResponse) -> None:
    monkeypatch.setattr(client, "_provider", lambda messages, config: response)


class TestUsageCallback:
    def test_chat_reports_provider_usage(self, monkeypatch):
        client = _client()
        calls = []
        client.on_usage = lambda usage, model, estimated: calls.append((usage, model, estimated))
        _mock_provider(
            client,
            monkeypatch,
            LLMResponse(
                content="ok",
                model="gpt-4o",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            ),
        )

        client.chat([Message(role="user", content="hello")])

        assert len(calls) == 1
        usage, model, estimated = calls[0]
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert model == "gpt-4o"
        assert estimated is False

    def test_chat_estimates_usage_when_provider_omits_it(self, monkeypatch):
        client = _client()
        calls = []
        client.on_usage = lambda usage, model, estimated: calls.append((usage, model, estimated))
        _mock_provider(
            client,
            monkeypatch,
            LLMResponse(content="x" * 40, model="gpt-4o", usage={}),
        )

        client.chat([Message(role="user", content="y" * 80)])

        usage, _, estimated = calls[0]
        assert estimated is True
        assert usage["prompt_tokens"] == 20
        assert usage["completion_tokens"] == 10

    def test_callback_failure_does_not_break_chat(self, monkeypatch):
        client = _client()

        def boom(usage, model, estimated):
            raise RuntimeError("accounting exploded")

        client.on_usage = boom
        _mock_provider(client, monkeypatch, LLMResponse(content="ok", model="gpt-4o", usage={}))

        resp = client.chat([Message(role="user", content="hello")])

        assert resp.content == "ok"


class TestPipelineBudgetWiring:
    def _config(self, tmp_path) -> NarrascapeConfig:
        return NarrascapeConfig(
            project=ProjectConfig(
                name="llm-budget-test",
                title="LLM Budget Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )

    def test_pipeline_attaches_usage_callback(self, tmp_path):
        client = _client()

        Pipeline(self._config(tmp_path), llm_client=client)

        assert client.on_usage is not None

    def test_llm_usage_recorded_into_budget_state(self, tmp_path, monkeypatch):
        client = _client()
        pipeline = Pipeline(self._config(tmp_path), llm_client=client)
        pipeline._active_stage = "director_contract"
        _mock_provider(
            client,
            monkeypatch,
            LLMResponse(
                content="ok",
                model="gpt-4o",
                usage={
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 1_000_000,
                    "total_tokens": 2_000_000,
                },
            ),
        )

        client.chat([Message(role="user", content="hello")])

        state_path = pipeline.config.pipeline_dir / "budget_state.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        # gpt-4o: 2.5 + 10.0 USD per million tokens
        assert data["spent"] == 12.5
        entry = data["entries"][0]
        assert entry["kind"] == "llm"
        assert entry["status"] == "success"
        assert entry["stage"] == "director_contract"
        assert entry["provider"] == "openai"
        assert entry["model"] == "gpt-4o"
        assert entry["prompt_tokens"] == 1_000_000
        assert entry["estimated"] is False

    def test_bridge_provider_recorded_as_zero_cost(self, tmp_path, monkeypatch):
        client = _client(provider="bridge")
        pipeline = Pipeline(self._config(tmp_path), llm_client=client)
        _mock_provider(
            client,
            monkeypatch,
            LLMResponse(content="ok", model="bridge", usage={}),
        )

        client.chat([Message(role="user", content="hello")])

        state_path = pipeline.config.pipeline_dir / "budget_state.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["spent"] == 0.0
        entry = data["entries"][0]
        assert entry["kind"] == "llm"
        assert entry["provider"] == "bridge"
        assert entry["estimated"] is True
