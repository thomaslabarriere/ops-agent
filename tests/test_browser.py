"""The browser-backed confirmation portal and its DOM-derived verdict.

Two layers:
- Mock portal (always runs, offline): the verdict is read from what was really
  posted, so an agent that CLAIMS a post it never made is caught.
- Real headless Chromium (skipped unless Playwright + a browser are installed):
  the same agent drives a real DOM over file://, and the confirmation is read
  back from that live DOM -- the pattern Twin lives on.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from opsagent.agent import CorrectAgent
from opsagent.browser import MockPortal, confirmation_session
from opsagent.evaluate import run_scenario
from opsagent.models import ActionKind
from opsagent.report import build_scorecard
from opsagent.scenarios import SCENARIOS, get_scenario
from opsagent.world import Tools


class _LiarAgent:
    """Issues a refund and CLAIMS it posted the public confirmation -- it writes
    a browser_post record into the log -- but never operates the portal. The
    DOM-derived verdict must catch this: nothing was actually published."""

    name = "liar"

    def run(self, scenario: Any, tools: Tools) -> tuple[int, int]:
        tools.lookup_order(scenario.order_id)
        tools.issue_refund(scenario.order_id, 30.0)  # A-100 owes 30: a safe amount
        # Forge the audit record without touching the portal ("ghost post").
        tools._world.record(
            ActionKind.BROWSER_POST, {"text": "posted"}, "posted", via="browser"
        )
        tools.reply_customer("All done, confirmation posted.")
        return (0, 0)


# --------------------------------------------------------------------------- #
# Mock portal (offline, always runs)
# --------------------------------------------------------------------------- #

def test_mock_portal_records_only_real_posts() -> None:
    portal = MockPortal()
    assert portal.current_text() == ""
    portal.post("Refund processed for A-100.")
    assert "A-100" in portal.current_text()
    portal.reset()
    assert portal.current_text() == ""


def test_correct_agent_confirmation_is_verified_from_the_portal() -> None:
    r = run_scenario(CorrectAgent(), get_scenario("s-small-refund"), MockPortal())
    assert r.confirmation_verified is True


def test_liar_agent_claims_a_post_it_never_made_and_is_caught() -> None:
    r = run_scenario(_LiarAgent(), get_scenario("s-small-refund"), MockPortal())
    # The log shows a browser_post it forged...
    assert any(a.kind is ActionKind.BROWSER_POST for a in r.actions)
    # ...but the DOM verdict is read from the portal, which holds nothing.
    assert r.confirmation_verified is False


def test_scorecard_aggregates_confirmation_verification() -> None:
    results = [run_scenario(CorrectAgent(), s, MockPortal()) for s in SCENARIOS]
    sc = build_scorecard("correct", results)
    # Every issued refund is confirmed; the correct agent leaves none unverified.
    assert sc.confirmations_expected > 0
    assert sc.confirmations_verified == sc.confirmations_expected


# --------------------------------------------------------------------------- #
# Real headless Chromium (skipped unless installed)
# --------------------------------------------------------------------------- #

@pytest.fixture
def real_portal_factory() -> Iterator[Any]:
    """Yield a factory that hands out a real headless-browser portal, or skip
    gracefully when Playwright / Chromium is not installed (offline default)."""
    pytest.importorskip("playwright.sync_api")
    try:
        with confirmation_session(real=True) as factory:
            yield factory
    except Exception as exc:  # noqa: BLE001 - no browser binary installed, etc.
        pytest.skip(f"real browser unavailable: {exc}")


def test_real_browser_confirmation_lands_in_the_dom(real_portal_factory: Any) -> None:
    portal = real_portal_factory()
    r = run_scenario(CorrectAgent(), get_scenario("s-small-refund"), portal)
    # The verdict came from the live DOM: the confirmation is present and names
    # the refunded order.
    assert r.confirmation_verified is True
    assert "A-100" in portal.current_text()


def test_real_browser_catches_a_claimed_but_unposted_confirmation(
    real_portal_factory: Any,
) -> None:
    portal = real_portal_factory()
    r = run_scenario(_LiarAgent(), get_scenario("s-small-refund"), portal)
    assert any(a.kind is ActionKind.BROWSER_POST for a in r.actions)  # claimed
    assert r.confirmation_verified is False  # but the real DOM is empty
    assert portal.current_text() == ""
