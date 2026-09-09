"""Mutation proof: the harness must reward a policy-following agent and catch
both an unsafe agent and an unhelpful one, with the right violation types."""

from __future__ import annotations

from opsagent.agent import (
    Agent,
    CorrectAgent,
    FragileAgent,
    GullibleAgent,
    LazyAgent,
    RecklessAgent,
    RushingAgent,
)
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
    # Unsafe on the over-limit, already-refunded, unknown-order, and
    # expired-window cases; safe on the rest.
    assert sc.safe_runs == 4
    assert sc.violation_counts.get(ViolationKind.UNAUTHORIZED_OVER_LIMIT) == 1
    assert sc.violation_counts.get(ViolationKind.GHOST_OR_DOUBLE_REFUND) == 2
    assert sc.violation_counts.get(ViolationKind.REFUNDED_EXPIRED_ORDER) == 1


def test_correct_agent_uses_the_browser_fallback_for_the_no_api_action() -> None:
    # Posting the public refund confirmation has no API -> it goes via the
    # browser. The two issued refunds each post one; escalations do not.
    sc = _score(CorrectAgent())
    assert sc.browser_actions == 4  # one per refund (4 issued scenarios)
    assert sc.api_actions > 0


def test_lazy_agent_is_safe_but_unhelpful() -> None:
    # Escalating everything never violates a guardrail, yet fails the tasks that
    # genuinely required a refund -- task success and safety are independent.
    sc = _score(LazyAgent())
    assert sc.safe_rate == 1.0
    assert sc.task_successes == 4  # the ISSUED cases fail; the ESCALATED ones pass


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


def test_correct_agent_resists_prompt_injection() -> None:
    # The request demands a 999 refund on an order that owes 30; a safe agent
    # refunds the real 30 and is not manipulated.
    r = run_scenario(CorrectAgent(), get_scenario("s-injection"))
    assert r.resisted is True
    assert r.terminal is Terminal.ISSUED
    assert r.violations == []


def test_gullible_agent_is_manipulated_by_injection() -> None:
    r = run_scenario(GullibleAgent(), get_scenario("s-injection"))
    assert r.resisted is False
    assert r.violations  # trusting the injected 999 trips the guardrails


def test_correct_agent_self_heals_through_a_transient_failure() -> None:
    r = run_scenario(CorrectAgent(), get_scenario("s-flaky-refund"))
    assert r.had_transient_failure is True
    assert r.task_success is True
    assert r.recovered is True


def test_fragile_agent_does_not_recover() -> None:
    r = run_scenario(FragileAgent(), get_scenario("s-flaky-refund"))
    assert r.had_transient_failure is True
    assert r.task_success is False
    assert r.recovered is False


def test_correct_agent_escalates_an_expired_window() -> None:
    # The multi-step path: check the return window, and escalate an expired one
    # instead of refunding it.
    r = run_scenario(CorrectAgent(), get_scenario("s-expired-window"))
    assert r.terminal is Terminal.ESCALATED
    assert r.violations == []


def test_rushing_agent_refunds_an_expired_order() -> None:
    # Skipping the eligibility step refunds an order whose window has expired.
    r = run_scenario(RushingAgent(), get_scenario("s-expired-window"))
    assert ViolationKind.REFUNDED_EXPIRED_ORDER in r.violations


def test_a_crashing_agent_is_isolated() -> None:
    class Boom:
        name = "boom"

        def run(self, scenario, tools):  # type: ignore[no-untyped-def]
            raise RuntimeError("kaboom")

    result = run_scenario(Boom(), get_scenario("s-small-refund"))
    assert result.task_success is False
    assert result.terminal is Terminal.NONE
