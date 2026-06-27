#!/usr/bin/env python3
"""Tests for budget tracker."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from narrascape.config import BudgetConfig
from narrascape.utils.budget import BudgetTracker, DEFAULT_COSTS


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

    def test_get_cost_estimate_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(
                BudgetConfig(total_usd=10.0, images_estimated=0.1, tts_estimated=0.002, music_estimated=0.05),
                state_path,
            )
            assert budget.get_cost_estimate("image", 5) == 0.5
            assert budget.get_cost_estimate("tts", 10) == 0.02
            assert budget.get_cost_estimate("music", 2) == 0.1

    def test_remaining_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "budget_state.json"
            budget = BudgetTracker(BudgetConfig(total_usd=5.0), state_path)
            budget.record(3.0)
            assert budget.remaining() == 2.0
            budget.record(5.0)
            assert budget.remaining() == 0.0  # Cannot go negative
