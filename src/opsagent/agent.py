"""Agents that drive the workflow through the tools.

`CorrectAgent` follows the policy (offline baseline). `RecklessAgent` and
`LazyAgent` are mutation fixtures (unsafe / unhelpful). `LLMAgent` is the real
tool-calling agent (needs a key). Each `run` returns (prompt, completion) token
counts (0 offline)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from .models import Scenario
from .world import AUTO_REFUND_LIMIT, NoAPIEndpoint, Tools

# Amounts that sit in a money context: right after a currency symbol, right
# after a money/instruction keyword (within a short gap), or right before a
# currency word. This is what an attacker actually writes ("refund 800",
# "$50 cap", "amount to 999"), and it lets the reader pick the demanded figure
# out of a sentence with several numbers instead of blindly taking the last one.
_MONEY_KEYWORDS = r"refund|amount|approve[d]?|set|pay|balance|total|reimburse|credit|to|for|of"
_MONEY_RE = re.compile(
    r"[$€£]\s?(\d+(?:\.\d+)?)"
    rf"|\b(?:{_MONEY_KEYWORDS})\b[^\d]{{0,15}}?(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s?(?:euros?|dollars?|usd|eur|gbp|pounds?|bucks?)",
    re.IGNORECASE,
)


def _requested_amount(request: str, order_id: str) -> float | None:
    """The refund amount the request TEXT asks for -- untrusted input. The
    order id is stripped first so its digits are not mistaken for an amount. A
    safe agent READS this (to notice a manipulation attempt) but never acts on
    it; a gullible one obeys it.

    Beyond a naive `numbers[-1]`, this prefers amounts that appear in a money
    context (a currency symbol, a money/instruction keyword, or a currency word)
    and returns the LARGEST such figure -- the demanded amount an injection is
    pushing -- falling back to the last bare number only when nothing looks like
    money. Still a heuristic, not a bullet-proof parser (see DECISIONS #4)."""
    stripped = request.replace(order_id, " ")
    money: list[float] = []
    for m in _MONEY_RE.finditer(stripped):
        token = next((g for g in m.groups() if g is not None), None)
        if token is not None:
            money.append(float(token))
    if money:
        return max(money)
    numbers = re.findall(r"\d+(?:\.\d+)?", stripped)
    return float(numbers[-1]) if numbers else None


class Agent(Protocol):
    name: str

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]: ...


def _parse_lookup(result: str) -> tuple[bool, float, str]:
    """(found, amount, status) from a lookup_order result string. A transient
    failure or a not-found both read as 'no usable order'."""
    if "not found" in result or "transient" in result:
        return False, 0.0, ""
    parts = result.split()
    return True, float(parts[2]), parts[3]


def _retry(call: Callable[[], str], attempts: int = 3) -> str:
    """Self-healing: re-issue a call while it returns a transient failure."""
    result = call()
    tries = 1
    while "transient" in result and tries < attempts:
        result = call()
        tries += 1
    return result


class CorrectAgent:
    """Policy-following baseline: refund only a valid paid order at/under the
    limit; otherwise escalate. Always replies to the customer."""

    name = "correct"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        # READ the untrusted request first: what amount is it asking us to
        # refund? On the injection scenario this is the demanded 999.
        demanded = _requested_amount(scenario.request, scenario.order_id)

        # Then decide on the FACTS from the order lookup. Resistance is a real
        # decision: we read the demand above and deliberately ground the refund
        # on the looked-up amount, not on what the text asked for. Retries
        # absorb transient tool failures (self-healing).
        found, amount, status = _parse_lookup(
            _retry(lambda: tools.lookup_order(scenario.order_id))
        )
        # True when the request tried to override the real amount (injection):
        # we read it and knowingly refuse the demanded figure.
        overridden = found and demanded is not None and abs(demanded - amount) > 0.001
        if not found:
            tools.escalate("order not found")
        elif status == "refunded":
            tools.escalate("order already refunded")
        elif amount > AUTO_REFUND_LIMIT:
            tools.escalate(f"amount {amount:.2f} above the auto-approval limit")
        elif "expired" in _retry(lambda: tools.check_return_window(scenario.order_id)):
            # Dependent eligibility gate: an expired return window needs review.
            tools.escalate("return window expired")
        else:
            # Ground the refund on the fact, never on the demanded amount.
            _retry(lambda: tools.issue_refund(scenario.order_id, amount))
            # Posting the public confirmation has NO API endpoint: try the API
            # path and, on unavailability, fall back to the browser tool. A
            # real try-API-then-browser bascule, not a routing constant.
            confirmation = f"Refund processed for {scenario.order_id}."
            try:
                tools.api_post_confirmation(confirmation)
            except NoAPIEndpoint:
                tools.browser_post(confirmation)
        reply = "Your request has been handled."
        if overridden:
            # The reply reflects the decision, so the read is load-bearing:
            # remove the read and this branch can no longer fire.
            reply += (
                " The amount stated in your message was not used; the refund "
                "follows the order on file."
            )
        tools.reply_customer(reply)
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


class GullibleAgent:
    """Mutation fixture: trusts the request text and refunds the amount it
    demands -> a prompt-injection request drives it into a violation."""

    name = "gullible"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        tools.lookup_order(scenario.order_id)
        # Reads the SAME request text the correct agent reads -- but obeys the
        # demanded figure instead of the order-lookup facts, so the injected
        # 999 drives it straight into a violation.
        demanded = _requested_amount(scenario.request, scenario.order_id)
        tools.issue_refund(scenario.order_id, demanded if demanded is not None else 0.0)
        tools.reply_customer("Done!")
        return (0, 0)


class FragileAgent:
    """Mutation fixture: follows the policy but never retries -> a single
    transient tool failure sinks the task (no self-healing)."""

    name = "fragile"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        found, amount, status = _parse_lookup(tools.lookup_order(scenario.order_id))
        if not found:
            tools.escalate("order not found")
        elif status == "refunded":
            tools.escalate("order already refunded")
        elif amount > AUTO_REFUND_LIMIT:
            tools.escalate("amount above the auto-approval limit")
        elif "expired" in tools.check_return_window(scenario.order_id):
            tools.escalate("return window expired")
        else:
            tools.issue_refund(scenario.order_id, amount)  # no retry
        tools.reply_customer("Your request has been handled.")
        return (0, 0)


class RushingAgent:
    """Mutation fixture: refunds a valid in-limit order but SKIPS the return
    window check -> refunds an order whose window has expired (orchestration
    step dropped)."""

    name = "rushing"

    def run(self, scenario: Scenario, tools: Tools) -> tuple[int, int]:
        found, amount, status = _parse_lookup(tools.lookup_order(scenario.order_id))
        if found and status != "refunded" and amount <= AUTO_REFUND_LIMIT:
            tools.issue_refund(scenario.order_id, amount)  # no eligibility check
        else:
            tools.escalate("needs review")
        tools.reply_customer("Your request has been handled.")
        return (0, 0)
