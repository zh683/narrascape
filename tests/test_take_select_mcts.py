"""Tests for the opt-in MCTS take-selection strategy (pairwise UCT).

Covers: convergence to the true best take under a noisy judge (where the
legacy single-pass judge fails), the hard per-segment evaluation budget,
decision-trace completeness with legacy fields untouched, determinism,
the no-LLM fallback path, tie handling, and total-judge-failure fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from narrascape.config import (
    NarrascapeConfig,
    ProjectConfig,
    TakeSelectConfig,
    load_script,
)
from narrascape.stages.base import StageContext
from narrascape.stages.take_select import TakeSelectStage

# ─────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────


def _config(
    tmp_path: Path,
    *,
    strategy: str = "mcts",
    budget: int = 5,
    exploration: float = 1.414,
) -> NarrascapeConfig:
    project_dir = tmp_path / "mcts_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "Mira studies the machine."}]}),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="mcts-project",
            title="MCTS Project",
            script_file="scripts/script.yaml",
        ),
        take_select=TakeSelectConfig(
            selection_strategy=strategy,  # type: ignore[arg-type]
            mcts_budget=budget,
            mcts_exploration=exploration,
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(config=config, script=load_script(config.script_path))


def _write_dummy_take(config: NarrascapeConfig, name: str, size: int) -> Path:
    path = config.project_dir / "assets" / "videos" / f"{name}.mp4"
    path.write_bytes(b"\0" * size)
    return path


def _fake_analyze(composites: dict[str, float]):
    def fake(path: Path, *, expected_duration: float | None, work_dir: Path) -> dict[str, Any]:
        composite = composites[path.stem]
        return {
            "status": "ok",
            "composite": composite,
            "sharpness": composite,
            "brightness": 100.0,
            "duration_score": 100.0,
            "stability": 100.0,
            "mean_luminance": 120.0,
            "laplacian_variance": 250.0,
            "duration_seconds": 5.0,
            "expected_duration_seconds": expected_duration,
            "frames_analyzed": 3,
        }

    return fake


class _Response:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def extract_json_safe(self, default: Any = None) -> dict[str, Any]:
        return self._data


def _duel_pair(prompt: str) -> dict[str, str]:
    """Extract {"A": take_id, "B": take_id} from the duel prompt."""
    for line in prompt.splitlines():
        if line.startswith("Candidates: "):
            payload = json.loads(line[len("Candidates: ") :])
            return {"A": payload["A"]["take"], "B": payload["B"]["take"]}
    raise AssertionError(f"no Candidates line in prompt: {prompt!r}")


class _RankedDuelLLM:
    """Pairwise judge with a fixed intrinsic take ranking.

    Answers every duel by picking the higher-ranked member of the pair,
    except the first ``wrong_calls`` calls which are inverted — simulating
    judge noise that a single-pass judge cannot recover from.
    """

    def __init__(self, ranking: list[str], wrong_calls: int = 0):
        self.ranking = ranking
        self.wrong_calls = wrong_calls
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> _Response:
        pair = _duel_pair(prompt)
        better = min(pair.values(), key=lambda take: self.ranking.index(take))
        worse = pair["B"] if better == pair["A"] else pair["A"]
        winner = worse if self.calls < self.wrong_calls else better
        self.calls += 1
        self.prompts.append(prompt)
        letter = "A" if pair["A"] == winner else "B"
        return _Response({"winner": letter, "reason": f"{winner} is stronger"})


def _run_mcts_stage(tmp_path: Path, monkeypatch, llm: Any, *, budget: int = 5):
    config = _config(tmp_path, budget=budget)
    composites = {"vid_01_take_01": 80.0, "vid_01_take_02": 60.0, "vid_01_take_03": 40.0}
    for name in composites:
        _write_dummy_take(config, name, 1000)
    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", _fake_analyze(composites))
    result = TakeSelectStage(llm_client=llm).run(_context(config))
    artifact = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    return result, artifact


# ─────────────────────────────────────────────
# Convergence under noise
# ─────────────────────────────────────────────


def test_mcts_recovers_from_noisy_first_duel(tmp_path, monkeypatch):
    """True best is take_02 (prior ranks it second); the judge's first duel is
    wrong, which would doom a single-pass judge — UCT re-evaluation recovers."""
    ranking = ["vid_01_take_02", "vid_01_take_01", "vid_01_take_03"]
    llm = _RankedDuelLLM(ranking, wrong_calls=1)

    result, artifact = _run_mcts_stage(tmp_path, monkeypatch, llm, budget=5)

    assert result.success
    selection = artifact["selections"][0]
    assert selection["selected_take"] == "vid_01_take_02"
    assert selection["mcts"]["evaluations_used"] == 5
    # The noisy first duel is visible in the audit trail.
    first = selection["mcts"]["evaluations"][0]
    assert first["winner"] != "vid_01_take_02"
    assert artifact["selection_process"]["llm_status"] == "used"
    assert artifact["selection_process"]["mode"] == "qa_plus_llm"


def test_single_pass_judge_cannot_recover_from_same_noise(tmp_path, monkeypatch):
    """Contrast case: legacy auto strategy + one wrong verdict = wrong take."""
    config = _config(tmp_path, strategy="auto")
    composites = {"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}
    for name in composites:
        _write_dummy_take(config, name, 1000)
    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", _fake_analyze(composites))

    class _WrongSingleJudge:
        def complete(self, prompt: str, **kwargs: Any) -> _Response:
            return _Response({"selected_take": "vid_01_take_01", "reason": "noisy verdict"})

    result = TakeSelectStage(llm_client=_WrongSingleJudge()).run(_context(config))

    assert result.success
    artifact = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    assert artifact["selections"][0]["selected_take"] == "vid_01_take_01"
    assert "mcts" not in artifact["selections"][0]


# ─────────────────────────────────────────────
# Budget hard cap
# ─────────────────────────────────────────────


def test_mcts_budget_is_a_hard_cap(tmp_path, monkeypatch):
    ranking = ["vid_01_take_02", "vid_01_take_01", "vid_01_take_03"]
    llm = _RankedDuelLLM(ranking)

    result, artifact = _run_mcts_stage(tmp_path, monkeypatch, llm, budget=2)

    assert result.success
    assert llm.calls == 2, "evaluation attempts must never exceed mcts_budget"
    mcts = artifact["selections"][0]["mcts"]
    assert mcts["budget"] == 2
    assert mcts["evaluations_used"] == 2
    assert len(mcts["evaluations"]) == 2


# ─────────────────────────────────────────────
# Trace completeness + legacy fields
# ─────────────────────────────────────────────


def test_mcts_trace_complete_and_legacy_fields_unchanged(tmp_path, monkeypatch):
    ranking = ["vid_01_take_01", "vid_01_take_02", "vid_01_take_03"]
    llm = _RankedDuelLLM(ranking)

    result, artifact = _run_mcts_stage(tmp_path, monkeypatch, llm, budget=4)

    assert result.success  # validate_artifact("take_selection") passed inside run()
    assert artifact["schema_version"] == "take_selection.v1"
    process = artifact["selection_process"]
    # Legacy process fields intact.
    assert process["judges"] == ["qa", "llm"]
    assert process["mode"] == "qa_plus_llm"
    assert process["llm_status"] == "used"
    assert process["quality_signals"] == ["sharpness", "brightness", "duration", "stability"]
    assert process["bytes_fallback_segments"] == []
    # New process-level audit fields.
    assert process["selection_strategy"] == "mcts"
    assert process["mcts"]["budget"] == 4
    assert process["mcts"]["segments"] == [1]
    assert process["mcts"]["fallback_segments"] == []

    selection = artifact["selections"][0]
    # Legacy selection fields intact.
    assert selection["segment_id"] == 1
    assert selection["selected_path"] == "assets/videos/vid_01_take_01.mp4"
    assert selection["scoring"] == "frame_analysis"
    assert {c["take"] for c in selection["candidates"]} == {
        "vid_01_take_01",
        "vid_01_take_02",
        "vid_01_take_03",
    }

    mcts = selection["mcts"]
    assert mcts["status"] == "completed"
    assert mcts["strategy"] == "pairwise_uct"
    assert mcts["tree"]["root"] == "segment_1"
    assert set(mcts["tree"]["leaves"]) == {
        "vid_01_take_01",
        "vid_01_take_02",
        "vid_01_take_03",
    }
    assert mcts["tree"]["evaluation_edges"] == 4
    for index, event in enumerate(mcts["evaluations"]):
        assert event["index"] == index
        assert len(event["pair"]) == 2
        assert event["winner"] in mcts["tree"]["leaves"] + ["tie"]
        assert isinstance(event["reason"], str)
    stats = {c["take"]: c for c in mcts["candidates"]}
    assert sum(c["visits"] for c in stats.values()) == 8  # 4 duels x 2 participants
    winner = stats[selection["selected_take"]]
    assert winner["win_rate"] == max(c["win_rate"] for c in stats.values())
    for entry in stats.values():
        assert set(entry) == {"take", "prior", "visits", "wins", "win_rate", "final_uct"}
    assert selection["reason"] == mcts["summary"]
    assert "MCTS pairwise-UCT selected" in mcts["summary"]


# ─────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────


def test_mcts_is_deterministic_across_runs(tmp_path, monkeypatch):
    ranking = ["vid_01_take_02", "vid_01_take_01", "vid_01_take_03"]
    _, first = _run_mcts_stage(tmp_path / "run1", monkeypatch, _RankedDuelLLM(ranking), budget=5)
    _, second = _run_mcts_stage(tmp_path / "run2", monkeypatch, _RankedDuelLLM(ranking), budget=5)

    sel_first = first["selections"][0]
    sel_second = second["selections"][0]
    assert sel_first["selected_take"] == sel_second["selected_take"]
    assert sel_first["mcts"]["evaluations"] == sel_second["mcts"]["evaluations"]
    assert sel_first["mcts"]["candidates"] == sel_second["mcts"]["candidates"]


# ─────────────────────────────────────────────
# Fallback paths
# ─────────────────────────────────────────────


def test_mcts_falls_back_to_deterministic_without_llm(tmp_path, monkeypatch, caplog):
    config = _config(tmp_path)
    composites = {"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}
    for name in composites:
        _write_dummy_take(config, name, 1000)
    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", _fake_analyze(composites))

    with caplog.at_level(logging.WARNING, logger="narrascape.stages.take_select"):
        result = TakeSelectStage(llm_client=None).run(_context(config))

    assert result.success
    artifact = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    selection = artifact["selections"][0]
    # Deterministic favorite wins; the trace documents why MCTS did not run.
    assert selection["selected_take"] == "vid_01_take_01"
    assert selection["mcts"]["status"] == "fallback_no_llm"
    assert selection["mcts"]["evaluations"] == []
    assert selection["mcts"]["evaluations_used"] == 0
    assert "no LLM client is configured" in selection["mcts"]["summary"]
    process = artifact["selection_process"]
    assert process["mode"] == "deterministic_quality_score"
    assert process["llm_status"] == "not_configured"
    assert process["mcts"]["fallback_segments"] == [1]
    assert "requires an LLM client" in caplog.text


def test_mcts_total_judge_failure_falls_back_to_prior(tmp_path, monkeypatch):
    config = _config(tmp_path, budget=3)
    composites = {"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}
    for name in composites:
        _write_dummy_take(config, name, 1000)
    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", _fake_analyze(composites))

    class _BrokenLLM:
        def complete(self, prompt: str, **kwargs: Any) -> _Response:
            raise RuntimeError("LLM backend down")

    result = TakeSelectStage(llm_client=_BrokenLLM()).run(_context(config))

    assert result.success
    artifact = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    selection = artifact["selections"][0]
    assert selection["selected_take"] == "vid_01_take_01"  # prior favorite
    assert selection["mcts"]["evaluations_used"] == 0
    assert len(selection["mcts"]["evaluation_errors"]) == 3
    assert all("error" in event for event in selection["mcts"]["evaluations"])
    process = artifact["selection_process"]
    assert process["mode"] == "deterministic_quality_score"
    assert process["llm_status"] == "fallback_after_error"
    assert process["llm_errors"]


def test_mcts_unparseable_verdict_counts_as_tie(tmp_path, monkeypatch):
    config = _config(tmp_path, budget=2)
    composites = {"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}
    for name in composites:
        _write_dummy_take(config, name, 1000)
    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", _fake_analyze(composites))

    class _GibberishLLM:
        def complete(self, prompt: str, **kwargs: Any) -> _Response:
            return _Response({"winner": "maybe", "reason": "cannot decide"})

    result = TakeSelectStage(llm_client=_GibberishLLM()).run(_context(config))

    assert result.success
    selection = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )["selections"][0]
    events = selection["mcts"]["evaluations"]
    assert all(event["winner"] == "tie" for event in events)
    stats = {c["take"]: c for c in selection["mcts"]["candidates"]}
    assert stats["vid_01_take_01"]["visits"] == 2
    assert stats["vid_01_take_01"]["wins"] == 1.0  # 0.5 per tie x 2
    # Prior decides between identical tie records: higher-prior take_01 wins.
    assert selection["selected_take"] == "vid_01_take_01"


def test_mcts_single_take_segment_makes_no_llm_calls(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_dummy_take(config, "vid_01_take_01", 1000)
    monkeypatch.setattr(
        "narrascape.stages.take_select.analyze_take",
        _fake_analyze({"vid_01_take_01": 80.0}),
    )

    class _CountingLLM:
        calls = 0

        def complete(self, prompt: str, **kwargs: Any) -> _Response:
            self.calls += 1
            return _Response({"winner": "A", "reason": "only one"})

    llm = _CountingLLM()
    result = TakeSelectStage(llm_client=llm).run(_context(config))

    assert result.success
    assert llm.calls == 0
    selection = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )["selections"][0]
    assert selection["selected_take"] == "vid_01_take_01"
    assert selection["mcts"]["evaluations_used"] == 0
