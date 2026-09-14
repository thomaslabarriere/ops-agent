"""LLM path, tested with a stubbed client (no network, no API credits).

Proves the code that actually ships and breaks in production: the tool-calling
loop dispatching a valid sequence to the right terminal, malformed/empty
tool-calls handled without crashing, and the fail-safe path (an API error must
never leave an unauthorized refund behind -- the agent escalates).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from opsagent import llm_agent
from opsagent.evaluate import run_scenario
from opsagent.llm_agent import LLMAgent
from opsagent.models import ActionKind, Terminal
from opsagent.scenarios import get_scenario


def _fake_client(create_fn: Any) -> Any:
    """A stand-in for openai.OpenAI exposing chat.completions.create."""
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn))
    )


def _tool_call(name: str, args: dict[str, Any], call_id: str = "c1") -> Any:
    return SimpleNamespace(
        type="function",
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _completion(tool_calls: list[Any]) -> Any:
    # message.model_dump() is called by the loop, so the fake supplies it.
    message = SimpleNamespace(
        tool_calls=tool_calls,
        content=None,
        model_dump=lambda: {"role": "assistant", "tool_calls": []},
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    )


def _sequence_client(completions: list[Any]) -> Any:
    """Return each canned completion in turn on successive create() calls."""
    it = iter(completions)

    def create(**_kw: Any) -> Any:
        return next(it)

    return _fake_client(create)


def _patch(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(llm_agent, "make_client", lambda *a, **k: client)


def test_valid_toolcall_sequence_reaches_the_issued_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # lookup -> refund the real 30 -> browser confirmation -> reply -> stop.
    client = _sequence_client(
        [
            _completion([_tool_call("lookup_order", {"order_id": "A-100"})]),
            _completion([_tool_call("issue_refund", {"order_id": "A-100", "amount": 30})]),
            _completion([_tool_call("browser_post", {"text": "done"})]),
            _completion([_tool_call("reply_customer", {"text": "handled"})]),
            _completion([]),  # no tool-calls -> loop ends
        ]
    )
    _patch(monkeypatch, client)
    agent = LLMAgent(model="gpt-4o")
    r = run_scenario(agent, get_scenario("s-small-refund"))
    assert r.terminal is Terminal.ISSUED
    assert r.task_success is True
    assert r.violations == []
    # Tokens accumulate across the loop; the browser post is recorded as such.
    assert r.prompt_tokens > 0 and r.completion_tokens > 0
    assert any(a.kind is ActionKind.BROWSER_POST and a.via == "browser" for a in r.actions)


def test_malformed_toolcall_is_handled_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = SimpleNamespace(
        type="function",
        id="c1",
        function=SimpleNamespace(name="issue_refund", arguments="not json at all"),
    )
    client = _sequence_client([_completion([bad]), _completion([])])
    _patch(monkeypatch, client)
    r = run_scenario(LLMAgent(model="gpt-4o"), get_scenario("s-small-refund"))
    # No refund went through (arguments never parsed) and nothing crashed.
    assert not any(a.kind is ActionKind.ISSUE_REFUND and a.ok for a in r.actions)
    assert r.terminal is Terminal.NONE


def test_empty_toolcalls_ends_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _sequence_client([_completion([])]))
    r = run_scenario(LLMAgent(model="gpt-4o"), get_scenario("s-small-refund"))
    assert r.terminal is Terminal.NONE
    assert r.violations == []


def test_fail_safe_when_the_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_kw: Any) -> Any:
        raise RuntimeError("API is down")

    _patch(monkeypatch, _fake_client(boom))
    r = run_scenario(LLMAgent(model="gpt-4o"), get_scenario("s-over-limit"))
    # A failed call must escalate, never issue an unauthorized refund.
    assert r.terminal is Terminal.ESCALATED
    assert not any(a.kind is ActionKind.ISSUE_REFUND for a in r.actions)
    assert r.violations == []
