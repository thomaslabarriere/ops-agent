"""Aggregate scenario results into a scorecard and render it.

Two headline numbers, deliberately separate: TASK SUCCESS (did the agent get
the right outcome?) and SAFETY (did it avoid every guardrail violation?). An
agent can be safe but useless, or helpful but dangerous -- you must see both."""

from __future__ import annotations

from .models import ScenarioResult, Scorecard, ViolationKind
from .pricing import estimate_usd, model_from_name

_VIOLATION_ORDER = [
    ViolationKind.UNAUTHORIZED_OVER_LIMIT,
    ViolationKind.GHOST_OR_DOUBLE_REFUND,
    ViolationKind.OVER_AMOUNT,
]


def build_scorecard(agent_name: str, results: list[ScenarioResult]) -> Scorecard:
    counts: dict[ViolationKind, int] = {}
    for r in results:
        for v in r.violations:
            counts[v] = counts.get(v, 0) + 1
    return Scorecard(
        agent_name=agent_name,
        total=len(results),
        task_successes=sum(1 for r in results if r.task_success),
        safe_runs=sum(1 for r in results if r.safe),
        violation_counts=counts,
        results=results,
        prompt_tokens=sum(r.prompt_tokens for r in results),
        completion_tokens=sum(r.completion_tokens for r in results),
        total_latency_ms=sum(r.latency_ms for r in results),
    )


def render_scorecard(sc: Scorecard) -> str:
    bar = "─" * 64
    lines = [bar, f"ops-agent — {sc.agent_name}", bar]
    lines.append(
        f"Réussite tâche: {sc.task_successes}/{sc.total} "
        f"({sc.task_success_rate * 100:.0f}%)   "
        f"Runs sûrs: {sc.safe_runs}/{sc.total} ({sc.safe_rate * 100:.0f}%)"
    )
    lines.append("")

    lines.append("Par scénario")
    for r in sc.results:
        task = "✓" if r.task_success else "✗"
        safety = "sûr" if r.safe else "!! " + ",".join(v.value for v in r.violations)
        lines.append(
            f"  {task} {r.scenario_id:<20} attendu={r.expected.value:<9} "
            f"obtenu={r.terminal.value:<9} [{safety}]"
        )
    lines.append("")

    lines.append("Violations de garde-fou")
    if sc.violation_counts:
        for v in _VIOLATION_ORDER:
            n = sc.violation_counts.get(v, 0)
            if n:
                lines.append(f"  {v.value:<24} {n}")
    else:
        lines.append("  (aucune)")

    tokens = sc.prompt_tokens + sc.completion_tokens
    if tokens > 0:
        lines.append("")
        lines.append("Coût & latence")
        usd = estimate_usd(model_from_name(sc.agent_name), sc.prompt_tokens, sc.completion_tokens)
        cost = f"  Tokens: {tokens}"
        if usd is not None:
            cost += f"   Coût estimé: ${usd:.4f} (prix catalogue indicatif)"
        lines.append(cost)
        if sc.total:
            lines.append(f"  Latence: {sc.total_latency_ms / sc.total:.0f} ms/scénario")

    lines.append(bar)
    return "\n".join(lines)
