"""Mutation proof: the harness must reward a policy-following agent and catch
both an unsafe agent and an unhelpful one, with the right violation types."""

from __future__ import annotations

from opsagent.agent import Agent, CorrectAgent, LazyAgent, RecklessAgent
from opsagent.evaluate import run_scenario
from opsagent.models import Scenario, Terminal, ViolationKind
from opsagent.report import build_scorecard
from opsagent.scenarios import SCENARIOS, get_scenario


def _score(agent: Agent):  # type: ignore[no-untyped-def]
    return build_scorecard(agent.name, [run_scenario(agent, s) for s in SCENARIOS])


def test_correct_agent_is_perfect_and_safe() -> None:
    sc = _score(CorrectAgent())
    assert sc.task_success_rate == 1.0
    assert sc.safe_rate == 1.0
    assert sc.violation_counts == {}


def test_reckless_agent_is_caught_on_exactly_the_dangerous_cases() -> None:
    sc = _score(RecklessAgent())
    # It correctly refunds the two small valid orders, but is unsafe on the
    # over-limit, already-refunded, and unknown-order cases.
    assert sc.safe_runs == 2
    assert sc.violation_counts.get(ViolationKind.UNAUTHORIZED_OVER_LIMIT) == 1
    assert sc.violation_counts.get(ViolationKind.GHOST_OR_DOUBLE_REFUND) == 2


def test_lazy_agent_is_safe_but_unhelpful() -> None:
    # Escalating everything never violates a guardrail, yet fails the tasks that
    # genuinely required a refund -- task success and safety are independent.
    sc = _score(LazyAgent())
    assert sc.safe_rate == 1.0
    assert sc.task_successes == 3  # the two ISSUED cases fail, three ESCALATED pass


def test_over_amount_is_detected() -> None:
    # An agent that refunds MORE than the order owed is flagged, even under the
    # auto-limit and on a valid order.
    class GreedyAgent:
        name = "greedy"

        def run(self, scenario: Scenario, tools):  # type: ignore[no-untyped-def]
            tools.lookup_order(scenario.order_id)
            tools.issue_refund(scenario.order_id, 49.0)  # A-100 owes 30
            return (0, 0)

    result = run_scenario(GreedyAgent(), get_scenario("s-small-refund"))
    assert ViolationKind.OVER_AMOUNT in result.violations


def test_a_crashing_agent_is_isolated() -> None:
    class Boom:
        name = "boom"

        def run(self, scenario, tools):  # type: ignore[no-untyped-def]
            raise RuntimeError("kaboom")

    result = run_scenario(Boom(), get_scenario("s-small-refund"))
    assert result.task_success is False
    assert result.terminal is Terminal.NONE
