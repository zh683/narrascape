#!/usr/bin/env python3
"""Tests for budget tracker."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from narrascape.catalog import core_artifact_templates
from narrascape.config import BudgetConfig, NarrascapeConfig, ProjectConfig
from narrascape.utils.budget import (
    DEFAULT_COSTS,
    BudgetTracker,
    estimate_llm_cost,
    estimate_tokens,
    write_cost_report,
)


class TestBudgetTracker:
    def test_load_spent_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            state_path.write_text(json.dumps({"spent": 1.5}), encoding="utf-8")
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            assert budget.spent == 1.5
            assert budget.remaining() == 8.5

    def test_load_spent_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            assert budget.spent == 0.0
            assert budget.remaining() == 10.0

    def test_can_spend_observe_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="observe"), state_path)
            allowed, msg = budget.can_spend(100.0)
            assert allowed is True
            assert "observe" in msg.lower()

    def test_can_spend_warn_mode_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="warn"), state_path)
            allowed, msg = budget.can_spend(5.0)
            assert allowed is True
            assert "OK" in msg

    def test_can_spend_warn_mode_exceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="warn"), state_path)
            allowed, msg = budget.can_spend(15.0)
            assert allowed is True  # warn mode still allows
            assert "WARNING" in msg

    def test_can_spend_cap_mode_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="cap"), state_path)
            allowed, msg = budget.can_spend(5.0)
            assert allowed is True
            assert "OK" in msg

    def test_can_spend_cap_mode_exceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="cap"), state_path)
            allowed, msg = budget.can_spend(15.0)
            assert allowed is False
            assert "CAP exceeded" in msg

    def test_record_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            budget.record(0.5)
            assert budget.spent == 0.5
            # Verify persistence
            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 0.5

    def test_record_multiple(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            budget.record(0.5)
            budget.record(1.0)
            assert budget.spent == 1.5

    def test_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            budget.record(5.0)
            budget.reset()
            assert budget.spent == 0.0
            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 0.0

    def test_get_cost_estimate_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            assert budget.get_cost_estimate("image", 10) == DEFAULT_COSTS["image_per_image"] * 10
            assert budget.get_cost_estimate("tts", 10) == DEFAULT_COSTS["tts_per_segment"] * 10
            assert budget.get_cost_estimate("music", 5) == DEFAULT_COSTS["music_per_zone"] * 5
            assert budget.get_cost_estimate("video", 2) == DEFAULT_COSTS["video_per_segment"] * 2

    def test_try_spend_reloads_state_under_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            first = BudgetTracker(BudgetConfig(total_usd=1.0, mode="cap"), state_path)
            second = BudgetTracker(BudgetConfig(total_usd=1.0, mode="cap"), state_path)

            allowed, _ = first.try_spend(0.7)
            blocked, msg = second.try_spend(0.7)

            assert allowed is True
            assert blocked is False
            assert "CAP exceeded" in msg
            assert json.loads(state_path.read_text(encoding="utf-8"))["spent"] == 0.7

    def test_reserve_prevents_concurrent_cap_overrun(self, tmp_path):
        state_path = tmp_path / "budget_state.json"
        config = BudgetConfig(total_usd=1.0, mode="cap")
        first = BudgetTracker(config, state_path)
        second = BudgetTracker(config, state_path)

        allowed, _ = first.reserve("video:1", 0.7)
        blocked, message = second.reserve("video:2", 0.7)

        assert allowed is True
        assert blocked is False
        assert "reserved" in message.lower() or "CAP exceeded" in message
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["spent"] == 0.0
        assert state["reservations"] == {"video:1": 0.7}

    def test_commit_reservation_moves_amount_to_spent(self, tmp_path):
        state_path = tmp_path / "budget_state.json"
        budget = BudgetTracker(BudgetConfig(total_usd=1.0, mode="cap"), state_path)
        assert budget.reserve("video:1", 0.4)[0] is True

        committed, _ = budget.commit_reservation("video:1")

        assert committed is True
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["spent"] == 0.4
        assert state["reservations"] == {}

    def test_existing_reservation_blocks_automatic_duplicate_call(self, tmp_path):
        state_path = tmp_path / "budget_state.json"
        budget = BudgetTracker(BudgetConfig(total_usd=1.0, mode="cap"), state_path)
        assert budget.reserve("video:1", 0.4)[0] is True

        allowed, message = BudgetTracker(
            BudgetConfig(total_usd=1.0, mode="cap"), state_path
        ).reserve("video:1", 0.4)

        assert allowed is False
        assert "pending" in message.lower()

    def test_get_cost_estimate_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(
                BudgetConfig(
                    total_usd=10.0,
                    images_estimated=0.1,
                    tts_estimated=0.002,
                    music_estimated=0.05,
                    video_estimated=0.25,
                ),
                state_path,
            )
            assert budget.get_cost_estimate("image", 5) == 0.5
            assert budget.get_cost_estimate("tts", 10) == 0.02
            assert budget.get_cost_estimate("music", 2) == 0.1
            assert budget.get_cost_estimate("video", 2) == 0.5

    def test_get_cost_estimate_accepts_explicit_zero_for_free_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(
                BudgetConfig(
                    total_usd=0.0,
                    images_estimated=0.0,
                    tts_estimated=0.0,
                    music_estimated=0.0,
                    video_estimated=0.0,
                ),
                state_path,
            )

            assert budget.get_cost_estimate("image", 5) == 0.0
            assert budget.get_cost_estimate("tts", 10) == 0.0
            assert budget.get_cost_estimate("music", 2) == 0.0
            assert budget.get_cost_estimate("video", 2) == 0.0

    def test_remaining_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=5.0), state_path)
            budget.record(3.0)
            assert budget.remaining() == 2.0
            budget.record(5.0)
            assert budget.remaining() == 0.0  # Cannot go negative


class TestCostEntries:
    def test_record_actual_failed_call_charges_and_marks_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)

            budget.record_actual(
                0.5, kind="video", status="failed", stage="generate_video", detail="vid_01"
            )

            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 0.5
            assert len(data["entries"]) == 1
            entry = data["entries"][0]
            assert entry["kind"] == "video"
            assert entry["status"] == "failed"
            assert entry["stage"] == "generate_video"
            assert entry["cost"] == 0.5

    def test_record_actual_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)

            budget.record_actual(0.5, kind="video", status="failed")
            budget.record_actual(0.5, kind="video", status="failed")

            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 1.0
            assert len(data["entries"]) == 2

    def test_network_error_entry_is_zero_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)

            budget.record_actual(0.0, kind="tts", status="network_error", detail="seg_01")

            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 0.0
            assert data["entries"][0]["status"] == "network_error"

    def test_legacy_state_file_without_entries_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            state_path.write_text(json.dumps({"spent": 1.5}), encoding="utf-8")
            budget = BudgetTracker(BudgetConfig(total_usd=10.0, mode="cap"), state_path)

            assert budget.spent == 1.5
            allowed, _ = budget.try_spend(0.5, kind="image", stage="generate_images")

            assert allowed is True
            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 2.0
            assert len(data["entries"]) == 1

    def test_cap_mode_triggers_with_failed_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=1.0, mode="cap"), state_path)

            # Failed provider-billed calls consume real budget.
            budget.record_actual(0.8, kind="video", status="failed")
            allowed, msg = budget.can_spend(0.5)

            assert allowed is False
            assert "CAP exceeded" in msg

    def test_try_spend_records_entry_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)

            budget.try_spend(0.05, kind="image", stage="generate_images", provider="seedream")

            entry = json.loads(state_path.read_text(encoding="utf-8"))["entries"][0]
            assert entry["kind"] == "image"
            assert entry["status"] == "success"
            assert entry["provider"] == "seedream"

    def test_reset_clears_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=10.0), state_path)
            budget.record_actual(0.5, kind="video", status="failed")

            budget.reset()

            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["spent"] == 0.0
            assert data["entries"] == []


class TestLLMRates:
    def test_default_rates_present_and_conservative_fallback(self):
        config = BudgetConfig()
        assert "gpt-4o" in config.llm_rates
        assert config.llm_default_rate.input_per_million_usd == 5.0
        assert config.llm_default_rate.output_per_million_usd == 15.0

    def test_rate_override_via_config(self):
        config = BudgetConfig(
            llm_rates={"my-model": {"input_per_million_usd": 1.0, "output_per_million_usd": 2.0}}
        )
        cost = estimate_llm_cost(
            config.llm_rates, config.llm_default_rate, "my-model", 1_000_000, 500_000
        )
        assert cost == pytest.approx(2.0)

    def test_unknown_model_uses_default_rate(self):
        config = BudgetConfig()
        cost = estimate_llm_cost(
            config.llm_rates, config.llm_default_rate, "unknown-model", 1_000_000, 1_000_000
        )
        assert cost == pytest.approx(20.0)

    def test_known_model_uses_table_rate(self):
        config = BudgetConfig()
        cost = estimate_llm_cost(
            config.llm_rates, config.llm_default_rate, "gpt-4o", 1_000_000, 100_000
        )
        assert cost == pytest.approx(3.5)

    def test_estimate_tokens_minimum_one(self):
        assert estimate_tokens("") == 1
        assert estimate_tokens("abcd" * 10) == 10


class TestCostReport:
    def _config(self, tmp_path):
        return NarrascapeConfig(
            project=ProjectConfig(
                name="cost-report-test",
                title="Cost Report Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )

    def test_write_cost_report_aggregates_entries(self, tmp_path):
        config = self._config(tmp_path)
        config.pipeline_dir.mkdir(parents=True)
        tracker = BudgetTracker(config.budget, config.pipeline_dir / "budget_state.json")
        tracker.try_spend(0.5, kind="video", stage="generate_video", provider="seedance")
        tracker.record_actual(0.5, kind="video", status="failed", stage="generate_video")
        tracker.record_actual(
            0.01,
            kind="llm",
            stage="director_contract",
            provider="openai",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=200,
        )

        out_path = write_cost_report(config)

        assert out_path == config.pipeline_dir / "cost_report.yaml"
        report = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert report["schema_version"] == "cost_report.v1"
        assert report["totals"]["calls"] == 3
        assert report["totals"]["failed"] == 1
        assert report["totals"]["failed_cost_usd"] == 0.5
        assert report["totals"]["cost_usd"] == pytest.approx(1.01)
        assert report["by_kind"]["video"]["calls"] == 2
        assert report["by_stage"]["generate_video"]["failed"] == 1
        assert report["llm"]["calls"] == 1
        assert report["llm"]["prompt_tokens"] == 1000
        assert report["llm"]["completion_tokens"] == 200
        assert report["budget"]["spent_usd"] == pytest.approx(1.01)

    def test_write_cost_report_handles_missing_state(self, tmp_path):
        config = self._config(tmp_path)

        out_path = write_cost_report(config)

        report = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert report["totals"]["calls"] == 0
        assert report["totals"]["cost_usd"] == 0.0

    def test_cost_report_registered_in_catalog(self):
        template = core_artifact_templates()["cost_report"]
        assert template == "pipeline/{name}/cost_report.yaml"
