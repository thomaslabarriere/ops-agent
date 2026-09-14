"""The tail, not the average: --runs N aggregates worst-case + variance.

Scripted agents are deterministic, so N runs collapse to one point (variance 0)
-- that is the regression guarantee. A seeded stochastic fixture then shows the
aggregation genuinely surfaces a tail: an agent safe on average that still
violates on some runs has worst-case > mean, and the worst run is identified.
"""

from __future__ import annotations

import random
from typing import Any

from opsagent.agent import CorrectAgent
from opsagent.evaluate import run_scenario
from opsagent.models import MultiRunReport, Scorecard
from opsagent.report import build_scorecard
from opsagent.scenarios import SCENARIOS
from opsagent.world import AUTO_REFUND_LIMIT, Tools


def _multi(agent: Any, runs: int) -> MultiRunReport:
    scorecards: list[Scorecard] = [
        build_scorecard(agent.name, [run_scenario(agent, s) for s in SCENARIOS])
        for _ in range(runs)
    ]
    return MultiRunReport(agent_name=agent.name, runs=runs, scorecards=scorecards)


def test_scripted_agent_is_deterministic_across_runs() -> None:
    report = _multi(CorrectAgent(), 5)
    assert report.worst_violation_rate == 0.0
    assert report.mean_violation_rate == 0.0
    assert report.variance_violation_rate == 0.0
    assert report.worst_task_success_rate == report.mean_task_success_rate == 1.0
    assert report.worst_run_index == 0


class _CoinflipRefunder:
    """Follows the policy EXCEPT on the over-limit case, where it refunds anyway
    with some probability -- a tail risk that shows up on some runs, not others.
    Seeded, so the whole N-run sequence is deterministic for the test."""

    name = "coinflip"

    def __init__(self, seed: int, p_violate: float) -> None:
        self._rng = random.Random(seed)
        self._p = p_violate

    def run(self, scenario: Any, tools: Tools) -> tuple[int, int]:
        result = tools.lookup_order(scenario.order_id)
        if "not found" in result or "transient" in result:
            tools.escalate("no usable order")
        else:
            amount = float(result.split()[2])
            status = result.split()[3]
            if status == "refunded":
                tools.escalate("already refunded")
            elif amount > AUTO_REFUND_LIMIT:
                # The ONLY stochastic point: sometimes refund over the limit.
                if self._rng.random() < self._p:
                    tools.issue_refund(scenario.order_id, amount)  # the unsafe flip
                else:
                    tools.escalate("above limit")
            elif "expired" in tools.check_return_window(scenario.order_id):
                tools.escalate("expired")
            else:
                tools.issue_refund(scenario.order_id, amount)
        tools.reply_customer("handled")
        return (0, 0)


def test_stochastic_agent_surfaces_worst_case_above_the_mean() -> None:
    report = _multi(_CoinflipRefunder(seed=1, p_violate=0.5), 20)
    rates = [sc.violation_rate for sc in report.scorecards]
    # It violates on some runs but not all -> a genuine tail.
    assert any(r > 0 for r in rates)
    assert any(r == 0 for r in rates)
    # Worst-case strictly exceeds the mean, and variance is real.
    assert report.worst_violation_rate > report.mean_violation_rate
    assert report.variance_violation_rate > 0.0
    # The identified worst run is actually a maximal one.
    assert rates[report.worst_run_index] == max(rates)


def test_multirun_is_reproducible_for_a_fixed_seed() -> None:
    a = _multi(_CoinflipRefunder(seed=7, p_violate=0.4), 10)
    b = _multi(_CoinflipRefunder(seed=7, p_violate=0.4), 10)
    assert [sc.violation_rate for sc in a.scorecards] == [
        sc.violation_rate for sc in b.scorecards
    ]
