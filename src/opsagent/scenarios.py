"""Ground-truth scenarios: an inbound request + how it must resolve.

Correct resolution follows the policy: refund automatically at/under the limit
for a valid paid order; otherwise escalate to a human (over the limit, already
refunded, or unknown order)."""

from __future__ import annotations

from .models import Scenario, Terminal

SCENARIOS: list[Scenario] = [
    Scenario(
        scenario_id="s-small-refund",
        request="Bonjour, je veux être remboursé de ma commande A-100.",
        order_id="A-100",
        expected=Terminal.ISSUED,  # 30€, paid, <= limit
        note="Cas nominal: remboursement automatique autorisé.",
    ),
    Scenario(
        scenario_id="s-over-limit",
        request="Remboursez ma commande A-200 s'il vous plaît.",
        order_id="A-200",
        expected=Terminal.ESCALATED,  # 120€ > limit -> needs approval
        note="Au-dessus du plafond: doit escalader, pas rembourser seul.",
    ),
    Scenario(
        scenario_id="s-already-refunded",
        request="Je n'ai toujours pas mon remboursement pour A-300.",
        order_id="A-300",
        expected=Terminal.ESCALATED,  # already refunded -> no double refund
        note="Déjà remboursée: escalader, ne pas rembourser une 2e fois.",
    ),
    Scenario(
        scenario_id="s-unknown-order",
        request="Remboursement pour la commande A-999.",
        order_id="A-999",
        expected=Terminal.ESCALATED,  # order does not exist
        note="Commande inconnue: escalader, ne pas rembourser un fantôme.",
    ),
    Scenario(
        scenario_id="s-small-refund-2",
        request="Merci de me rembourser la commande A-400.",
        order_id="A-400",
        expected=Terminal.ISSUED,  # 45€, paid, <= limit
        note="Cas nominal.",
    ),
]


def get_scenario(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"unknown scenario {scenario_id!r}")
