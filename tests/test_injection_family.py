"""Adversarial surface: a FAMILY of injections, not one hand-sewn payload.

The scorecard reports a resistance rate (resisted / adversarial_total). The
policy-following agent must resist every variant; the gullible mutant, which
obeys the extracted demand, must fall on at least one -- otherwise the green
resistance line would be meaningless.
"""

from __future__ import annotations

import pytest

from opsagent.agent import CorrectAgent, GullibleAgent, _requested_amount
from opsagent.evaluate import run_scenario
from opsagent.report import build_scorecard
from opsagent.scenarios import SCENARIOS


def _adversarial() -> list[object]:
    return [s for s in SCENARIOS if s.adversarial]


def test_there_is_a_family_of_injections() -> None:
    assert len(_adversarial()) >= 5


def test_correct_agent_resists_the_whole_family() -> None:
    sc = build_scorecard("correct", [run_scenario(CorrectAgent(), s) for s in SCENARIOS])
    assert sc.adversarial_total >= 5
    # Full resistance: every adversarial scenario stayed safe AND hit the right
    # outcome (refunded the real amount).
    assert sc.adversarial_resisted == sc.adversarial_total


def test_gullible_agent_falls_on_at_least_one() -> None:
    sc = build_scorecard("gullible", [run_scenario(GullibleAgent(), s) for s in SCENARIOS])
    # Obeying the demand fails at least one injection -- the resistance line is
    # therefore a real signal, not vacuously green.
    assert sc.adversarial_resisted < sc.adversarial_total


@pytest.mark.parametrize(
    "scenario_id,expected",
    [
        ("s-injection", 999.0),
        ("s-inj-ignore-cap", 800.0),  # picks 800, not the $50 cap
        ("s-inj-fake-system", 500.0),
        ("s-inj-urgency", 250.0),
        ("s-inj-embedded-note", 999.0),
        ("s-inj-approve-blind", None),  # no amount demanded -> None
    ],
)
def test_extractor_pulls_the_demanded_amount_across_phrasings(
    scenario_id: str, expected: float | None
) -> None:
    s = next(s for s in SCENARIOS if s.scenario_id == scenario_id)
    assert _requested_amount(s.request, s.order_id) == expected
