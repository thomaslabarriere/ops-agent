"""ops-agent CLI.

  ops-agent run [--agent correct|reckless|lazy|llm] [--model M] [--json OUT]

Offline by default (the scripted `correct` agent). `--agent llm` runs the real
tool-calling agent and needs OPENAI_API_KEY (or OPENROUTER_API_KEY +
--provider openrouter) -- the only thing required to run it for real.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import Agent, CorrectAgent, LazyAgent, RecklessAgent
from .browser import confirmation_session
from .evaluate import run_scenario
from .models import MultiRunReport
from .report import build_scorecard, render_multi_run, render_scorecard
from .scenarios import SCENARIOS

_SCRIPTED: dict[str, type[Agent]] = {
    "correct": CorrectAgent,
    "reckless": RecklessAgent,
    "lazy": LazyAgent,
}


def _build_agent(args: argparse.Namespace) -> Agent:
    if args.agent == "llm":
        var = "OPENROUTER_API_KEY" if args.provider == "openrouter" else "OPENAI_API_KEY"
        if not os.environ.get(var):
            raise SystemExit(f"{var} is not set. --agent llm needs it (or use the offline agents).")
        from .llm_agent import LLMAgent

        return LLMAgent(model=args.model, provider=args.provider)
    return _SCRIPTED[args.agent]()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ops-agent",
        description="Run an autonomous ops agent and score task success + guardrail safety.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the agent on every scenario and score it.")
    run.add_argument("--agent", choices=["correct", "reckless", "lazy", "llm"], default="correct")
    run.add_argument("--provider", choices=["openai", "openrouter"], default="openai")
    run.add_argument("--model", default="gpt-4o")
    run.add_argument(
        "--browser",
        choices=["mock", "real"],
        default="mock",
        help="'real' drives a headless Chromium confirmation page (needs the [browser] extra "
        "and a Chromium install); 'mock' (default) is fully offline.",
    )
    run.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Run the whole suite N times and report the distribution (worst-case, "
        "mean, variance of the violation rate) -- the tail matters, not the average.",
    )
    run.add_argument("--json", help="Write the scorecard (or multi-run report) as JSON here.")

    args = parser.parse_args(argv)
    if args.command != "run":
        return 0
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")

    agent = _build_agent(args)
    try:
        with confirmation_session(real=args.browser == "real") as portal_for:
            scorecards = [
                build_scorecard(
                    agent.name,
                    [run_scenario(agent, s, portal_for()) for s in SCENARIOS],
                )
                for _ in range(args.runs)
            ]
    except ImportError as exc:  # playwright not installed but --browser real asked
        raise SystemExit(
            "--browser real needs the [browser] extra: pip install -e '.[browser]' "
            f"&& python -m playwright install chromium ({exc})"
        ) from exc

    if args.runs == 1:
        scorecard = scorecards[0]
        print(render_scorecard(scorecard))
        payload = scorecard.model_dump(mode="json")
        safe = scorecard.safe_runs == scorecard.total
    else:
        report = MultiRunReport(agent_name=agent.name, runs=args.runs, scorecards=scorecards)
        print(render_multi_run(report))
        payload = report.model_dump(mode="json")
        # The tail is the signal: fail if ANY run violated a guardrail.
        safe = report.worst_violation_rate == 0.0

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\nReport written to {args.json}")
    return 0 if safe else 1


if __name__ == "__main__":
    sys.exit(main())
