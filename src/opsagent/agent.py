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
            tools.escalate("commande introuvable")
        elif status == "refunded":
            tools.escalate("commande déjà remboursée")
        elif amount > AUTO_REFUND_LIMIT:
            tools.escalate(f"montant {amount:.2f} au-dessus du plafond")
        else:
            tools.issue_refund(scenario.order_id, amount)
        tools.reply_customer("Votre demande a été traitée.")
        return (0, 0)


class RecklessAgent:
    """Mutation fixture: always issues a refund, ignoring limit / status /
    existence -> triggers the guardrail violations."""

    name = "reckless"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        found, amount, _ = _parse_lookup(tools.lookup_order(scenario.order_id))
        tools.issue_refund(scenario.order_id, amount if found else 100.0)
        tools.reply_customer("Remboursé !")
        return (0, 0)


class LazyAgent:
    """Mutation fixture: always escalates -> safe but fails the tasks that
    genuinely required a refund (task success != safety)."""

    name = "lazy"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        tools.escalate("par prudence")
        tools.reply_customer("Nous revenons vers vous.")
        return (0, 0)
