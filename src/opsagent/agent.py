"""Agents that drive the workflow through the tools.

`CorrectAgent` follows the policy (offline baseline). `RecklessAgent` and
`LazyAgent` are mutation fixtures (unsafe / unhelpful). `LLMAgent` is the real
tool-calling agent (needs a key). Each `run` returns (prompt, completion) token
counts (0 offline)."""

from __future__ import annotations

from typing import Protocol

from .models import Scenario
from .world import AUTO_REFUND_LIMIT, Tools


class Agent(Protocol):
    name: str

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]: ...


def _parse_lookup(result: str) -> tuple[bool, float, str]:
    """(found, amount, status) from a lookup_order result string."""
    if "not found" in result:
        return False, 0.0, ""
    parts = result.split()
    return True, float(parts[2]), parts[3]


class CorrectAgent:
    """Policy-following baseline: refund only a valid paid order at/under the
    limit; otherwise escalate. Always replies to the customer."""

    name = "correct"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        found, amount, status = _parse_lookup(tools.lookup_order(scenario.order_id))
        if not found:
            tools.escalate("order not found")
        elif status == "refunded":
            tools.escalate("order already refunded")
        elif amount > AUTO_REFUND_LIMIT:
            tools.escalate(f"amount {amount:.2f} above the auto-approval limit")
        else:
            tools.issue_refund(scenario.order_id, amount)
            # The public refund-status portal has no API -> post via the browser.
            tools.browser_post(f"Refund processed for {scenario.order_id}.")
        tools.reply_customer("Your request has been handled.")
        return (0, 0)


class RecklessAgent:
    """Mutation fixture: always issues a refund, ignoring limit / status /
    existence -> triggers the guardrail violations."""

    name = "reckless"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        found, amount, _ = _parse_lookup(tools.lookup_order(scenario.order_id))
        tools.issue_refund(scenario.order_id, amount if found else 100.0)
        tools.reply_customer("Refunded!")
        return (0, 0)


class LazyAgent:
    """Mutation fixture: always escalates -> safe but fails the tasks that
    genuinely required a refund (task success != safety)."""

    name = "lazy"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        tools.escalate("escalating to be safe")
        tools.reply_customer("We'll get back to you.")
        return (0, 0)
