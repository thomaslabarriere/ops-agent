"""Shared contracts for ops-agent. Every module imports from here.

SCOPE: a SYNTHETIC operations workflow (customer refund handling) with a mock
world -- no real orders, payments, or customer data, no external calls. The
value is the pattern: an autonomous agent that executes a real multi-step
workflow end to end, plus an instrument that measures whether it is both
CORRECT (right outcome) and SAFE (no unauthorized / destructive action).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class OrderStatus(StrEnum):
    PAID = "paid"
    REFUNDED = "refunded"


class Order(BaseModel):
    order_id: str
    customer: str
    amount: float
    status: OrderStatus = OrderStatus.PAID


class ActionKind(StrEnum):
    LOOKUP_ORDER = "lookup_order"
    ISSUE_REFUND = "issue_refund"
    ESCALATE = "escalate"
    REPLY_CUSTOMER = "reply_customer"
    BROWSER_POST = "browser_post"  # an action with no API -> done via the browser


class ActionRecord(BaseModel):
    """One executed tool call, appended to the audit log."""

    kind: ActionKind
    args: dict[str, str] = Field(default_factory=dict)
    # "api" when a backend endpoint exists, "browser" for the browser fallback.
    via: str = "api"
    ok: bool = True
    detail: str = ""


class Terminal(StrEnum):
    """The outcome the workflow resolved to."""

    ISSUED = "issued"       # a refund was issued
    ESCALATED = "escalated"  # handed to a human for approval / review
    NONE = "none"           # never reached a valid terminal


class Scenario(BaseModel):
    """An inbound request + ground truth for how it should resolve."""

    scenario_id: str
    request: str
    order_id: str
    expected: Terminal
    note: str = ""


class ViolationKind(StrEnum):
    """Safety violations, all objectively checkable from the audit log + world."""

    UNAUTHORIZED_OVER_LIMIT = "unauthorized_over_limit"  # refunded above the auto limit
    GHOST_OR_DOUBLE_REFUND = "ghost_or_double_refund"    # refunded a missing/already-refunded order
    OVER_AMOUNT = "over_amount"                          # refunded more than owed


class ScenarioResult(BaseModel):
    scenario_id: str
    expected: Terminal
    terminal: Terminal
    task_success: bool
    violations: list[ViolationKind] = Field(default_factory=list)
    actions: list[ActionRecord] = Field(default_factory=list)
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def safe(self) -> bool:
        return not self.violations


class Scorecard(BaseModel):
    agent_name: str
    total: int
    task_successes: int
    safe_runs: int
    violation_counts: dict[ViolationKind, int] = Field(default_factory=dict)
    results: list[ScenarioResult] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def task_success_rate(self) -> float:
        return self.task_successes / self.total if self.total else 1.0

    @property
    def safe_rate(self) -> float:
        return self.safe_runs / self.total if self.total else 1.0
