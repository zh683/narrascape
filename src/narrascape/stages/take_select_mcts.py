"""MCTS-style UCT take selection (AniMaker-inspired, opt-in).

The legacy take_select path asks the LLM judge once per segment — a single
black-box verdict with no exploration and no answer to "why not the other
take". This module replaces that one-shot verdict with a structured search:

* The candidate takes of one segment form a shallow search tree: a root
  (the selection problem) with one leaf per take, and evaluation edges that
  are LLM **pairwise duels** between two leaves. Pairwise comparison is
  preferred over absolute scoring because it is far more stable across LLM
  calls and is naturally tree-shaped.
* A hard per-segment budget caps the number of duels. Each iteration picks
  the next pair by UCT (win_rate + c*sqrt(ln(total)/visits)), which balances
  exploiting the current duel leader against exploring rarely-compared
  takes. Unvisited takes have infinite UCT and are therefore compared first.
* The deterministic quality score (ffmpeg frame analysis, or byte-size
  fallback) enters as the Bayesian prior: it seeds the win-rate estimate of
  unvisited takes and breaks all ties, so a zero-information search degrades
  exactly to the legacy deterministic ranking.

Determinism: given identical LLM responses the search is fully deterministic
— UCT is closed-form and every tie is broken by (prior, take_number). No RNG
is used, which is stronger than a seeded policy.

Auditability is the primary goal: the complete trace (every duel's pair,
winner and reason; per-candidate visits/wins/win-rate/final-UCT; budget
usage; a human-readable summary) is returned for persistence into
take_selection.yaml.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("narrascape.stages.take_select.mcts")


@dataclass
class _CandidateState:
    """Mutable search state for one candidate take (a tree leaf)."""

    take_id: str
    take_number: int
    prior: float  # normalized deterministic quality score in [0, 1]
    visits: int = 0
    wins: float = 0.0

    @property
    def win_rate(self) -> float:
        """Observed duel win rate; unvisited leaves fall back to the prior."""
        if self.visits == 0:
            return self.prior
        return self.wins / self.visits


@dataclass
class MCTSSelection:
    """Outcome of one segment's MCTS search (trace is YAML-serializable)."""

    selected_take: str
    reason: str
    evaluations_used: int  # successful duels (errors excluded)
    errors: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def _prior_normalize(candidates: list[dict[str, Any]]) -> dict[str, float]:
    """Sum-normalize deterministic scores into [0, 1] priors.

    Works for both the 0-100 composite scale and raw byte sizes (fallback
    scoring). All-zero input degrades to a uniform prior.
    """
    scores = {str(c["id"]): max(0.0, float(c["score"])) for c in candidates}
    total = sum(scores.values())
    if total <= 0:
        uniform = 1.0 / max(len(scores), 1)
        return dict.fromkeys(scores, uniform)
    return {take_id: value / total for take_id, value in scores.items()}


class PairwiseUCTSelector:
    """Budget-capped UCT search over pairwise LLM comparisons."""

    def __init__(self, llm_client: Any, *, budget: int, exploration: float = 1.414):
        self.llm_client = llm_client
        self.budget = max(1, int(budget))
        self.exploration = float(exploration)

    # ── UCT core ──────────────────────────────────────────────────

    def _uct(self, state: _CandidateState, total_visits: int) -> float:
        if state.visits == 0:
            return math.inf  # unexplored leaves are always visited first
        return state.win_rate + self.exploration * math.sqrt(
            math.log(max(total_visits, 1)) / state.visits
        )

    def _rank(self, states: list[_CandidateState], total_visits: int) -> list[_CandidateState]:
        """Deterministic ranking: UCT desc, then prior desc, then take number asc."""
        return sorted(
            states,
            key=lambda s: (self._uct(s, total_visits), s.prior, -s.take_number),
            reverse=True,
        )

    def _pick_pair(
        self, states: list[_CandidateState], total_visits: int
    ) -> tuple[_CandidateState, _CandidateState]:
        ranked = self._rank(states, total_visits)
        return ranked[0], ranked[1]

    def _final_pick(self, states: list[_CandidateState]) -> _CandidateState:
        """Best leaf: win rate (prior for unvisited), then visits, prior, take no."""
        return self._rank_final(states)[0]

    def _rank_final(self, states: list[_CandidateState]) -> list[_CandidateState]:
        return sorted(
            states,
            key=lambda s: (s.win_rate, s.visits, s.prior, -s.take_number),
            reverse=True,
        )

    # ── LLM duel ──────────────────────────────────────────────────

    def _ask_llm_duel(
        self,
        *,
        segment_id: int,
        narration: str,
        left: _CandidateState,
        right: _CandidateState,
        qa_checks: dict[str, Any],
        scores: dict[str, float],
        byte_counts: dict[str, int],
    ) -> tuple[str, str]:
        """One pairwise comparison. Returns (winner_take_id_or_tie, reason)."""
        payload = {
            "A": {
                "take": left.take_id,
                "score": scores[left.take_id],
                "bytes": byte_counts[left.take_id],
            },
            "B": {
                "take": right.take_id,
                "score": scores[right.take_id],
                "bytes": byte_counts[right.take_id],
            },
        }
        prompt = (
            "You are the multi-take director comparing two generated-video takes for "
            "one film segment. Choose the better take for story clarity and "
            "continuity; use the QA scores as evidence when the choice is close.\n\n"
            f"Segment id: {segment_id}\n"
            f"Narration: {narration}\n"
            f"Candidates: {json.dumps(payload, ensure_ascii=False)}\n"
            f"QA checks: {json.dumps(qa_checks, ensure_ascii=False)}\n\n"
            'Return JSON only: {"winner": "A" or "B", "reason": "short reason"}.'
        )
        response = self.llm_client.complete(prompt, json_mode=True)
        if hasattr(response, "extract_json_safe"):
            data = response.extract_json_safe(default={})
        else:
            data = json.loads(getattr(response, "content", "{}"))
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")
        verdict = str(data.get("winner") or "").strip().upper()
        reason = str(data.get("reason") or "").strip()
        if verdict == "A":
            return left.take_id, reason or "LLM preferred take A"
        if verdict == "B":
            return right.take_id, reason or "LLM preferred take B"
        # Unparseable verdict: an honest tie, still auditable in the trace.
        return "tie", reason or f"unparseable verdict {verdict!r}; counted as tie"

    # ── Search ────────────────────────────────────────────────────

    def select(
        self,
        *,
        segment_id: int,
        narration: str,
        candidates: list[dict[str, Any]],
        qa_checks: dict[str, Any],
    ) -> MCTSSelection:
        """Run the budgeted UCT search for one segment.

        ``candidates`` are the stage's scored candidates (id/take_number/
        score/bytes). The budget caps LLM duel *attempts*; errored attempts
        consume budget (they may have cost money) but not visits.
        """
        priors = _prior_normalize(candidates)
        states = [
            _CandidateState(
                take_id=str(c["id"]),
                take_number=int(c["take_number"]),
                prior=priors[str(c["id"])],
            )
            for c in candidates
        ]
        scores = {str(c["id"]): float(c["score"]) for c in candidates}
        byte_counts = {str(c["id"]): int(c["bytes"]) for c in candidates}

        evaluations: list[dict[str, Any]] = []
        errors: list[str] = []
        attempts = 0
        while attempts < self.budget and len(states) > 1:
            left, right = self._pick_pair(states, attempts)
            event: dict[str, Any] = {
                "index": attempts,
                "pair": [left.take_id, right.take_id],
            }
            try:
                winner, reason = self._ask_llm_duel(
                    segment_id=segment_id,
                    narration=narration,
                    left=left,
                    right=right,
                    qa_checks=qa_checks,
                    scores=scores,
                    byte_counts=byte_counts,
                )
            except Exception as exc:
                errors.append(f"evaluation {attempts}: {exc}")
                event["winner"] = None
                event["error"] = str(exc)
                evaluations.append(event)
                attempts += 1
                logger.warning(
                    "take_select mcts: duel %s for segment %s failed (%s); "
                    "attempt counts against the budget",
                    attempts,
                    segment_id,
                    exc,
                )
                continue
            left.visits += 1
            right.visits += 1
            if winner == left.take_id:
                left.wins += 1.0
            elif winner == right.take_id:
                right.wins += 1.0
            else:  # tie
                left.wins += 0.5
                right.wins += 0.5
            event["winner"] = winner
            event["reason"] = reason
            evaluations.append(event)
            attempts += 1

        used = sum(1 for event in evaluations if event.get("winner"))
        ranked = self._rank_final(states)
        champion = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        total_visits = sum(s.visits for s in states)
        summary = (
            f"MCTS pairwise-UCT selected {champion.take_id} after {used}/{self.budget} "
            f"evaluations: win rate {champion.win_rate:.2f} "
            f"({champion.wins:g}/{champion.visits} duels), prior {champion.prior:.2f}."
        )
        if runner_up is not None:
            summary += (
                f" Runner-up {runner_up.take_id}: win rate {runner_up.win_rate:.2f} "
                f"({runner_up.wins:g}/{runner_up.visits} duels), prior {runner_up.prior:.2f}."
            )
        if errors:
            summary += f" {len(errors)} evaluation(s) failed (see evaluation_errors)."

        trace: dict[str, Any] = {
            "status": "completed",
            "strategy": "pairwise_uct",
            "budget": self.budget,
            "evaluations_used": used,
            "evaluation_errors": errors,
            "exploration": self.exploration,
            "tree": {
                "root": f"segment_{segment_id}",
                "leaves": [s.take_id for s in states],
                "evaluation_edges": len(evaluations),
            },
            "evaluations": evaluations,
            "candidates": [
                {
                    "take": s.take_id,
                    "prior": round(s.prior, 4),
                    "visits": s.visits,
                    "wins": s.wins,
                    "win_rate": round(s.win_rate, 4),
                    "final_uct": (
                        round(self._uct(s, total_visits), 4)
                        if math.isfinite(self._uct(s, total_visits))
                        else "inf"
                    ),
                }
                for s in self._rank(states, total_visits)
            ],
            "summary": summary,
        }
        return MCTSSelection(
            selected_take=champion.take_id,
            reason=summary,
            evaluations_used=used,
            errors=errors,
            trace=trace,
        )


def fallback_trace(
    *, budget: int, exploration: float, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Audit trace recorded when MCTS was requested but no LLM is configured.

    The stage still selects deterministically; this block documents that the
    MCTS path was requested and why it did not run, so the reviewer is never
    left guessing which process produced the selection.
    """
    priors = _prior_normalize(candidates)
    return {
        "status": "fallback_no_llm",
        "strategy": "pairwise_uct",
        "budget": budget,
        "evaluations_used": 0,
        "evaluation_errors": [],
        "exploration": exploration,
        "tree": {
            "root": "unsearched",
            "leaves": [str(c["id"]) for c in candidates],
            "evaluation_edges": 0,
        },
        "evaluations": [],
        "candidates": [
            {
                "take": str(c["id"]),
                "prior": round(priors[str(c["id"])], 4),
                "visits": 0,
                "wins": 0.0,
                "win_rate": round(priors[str(c["id"])], 4),
                "final_uct": "inf",
            }
            for c in candidates
        ],
        "summary": (
            "MCTS selection was requested (selection_strategy=mcts) but no LLM "
            "client is configured; the deterministic quality-score ranking was "
            "used instead."
        ),
    }
