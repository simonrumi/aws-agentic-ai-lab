"""Unit tests for the approval hook (approval.py).

No model here. Each test builds a real Strands BeforeToolCallEvent, as the
agent would just before a tool call, around a stand-in agent that holds
only Strands' interrupt bookkeeping. That way the tests use Strands' own
`event.interrupt`, not a copy of it:

  - safe tools (reads, open_ticket) run without a pause
  - risky tools pause, and the pause shows the tool, inputs and run ID
  - "y" lets the call run; "n", blank or anything else cancels it
  - a tool not on the safe list (e.g. one added later) pauses by default
  - the decision is printed with the run ID
"""

import pytest
from strands.hooks import BeforeToolCallEvent, HookRegistry
from strands.interrupt import InterruptException, _InterruptState

from approval import (
    DENIED_MESSAGE,
    INTERRUPT_NAME,
    NO_APPROVAL_NEEDED,
    is_approved,
    make_approval_check,
)

RUN_ID = "run123"


class StandInAgent:
    """Just enough of an Agent for event.interrupt(): its interrupt state."""

    def __init__(self):
        self._interrupt_state = _InterruptState()


def make_event(agent, name: str, inputs: dict) -> BeforeToolCallEvent:
    """The event Strands fires before running tool `name` with `inputs`."""
    return BeforeToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"toolUseId": "tool-1", "name": name, "input": inputs},
        invocation_state={},
    )


def run_with_answer(name: str, inputs: dict, answer: str) -> BeforeToolCallEvent:
    """Fire the hook twice, as Strands does: once to pause, once with the answer."""
    agent = StandInAgent()
    check = make_approval_check(RUN_ID)
    with pytest.raises(InterruptException) as paused:
        check(make_event(agent, name, inputs))
    # What the terminal loop does: record the person's answer, then resume.
    paused.value.interrupt.response = answer
    event = make_event(agent, name, inputs)
    check(event)
    return event


def test_hook_registers_for_before_tool_call():
    """Strands reads the type hint and runs the check before each tool call."""
    registry = HookRegistry()
    check = make_approval_check(RUN_ID)
    registry.add_callback(None, check)  # None: work out the event from the hint
    event = make_event(StandInAgent(), "get_ticket", {})
    assert list(registry.get_callbacks_for(event)) == [check]


@pytest.mark.parametrize("name", sorted(NO_APPROVAL_NEEDED))
def test_safe_tool_runs_without_pause(name):
    """Reads and open_ticket: no interrupt, nothing cancelled."""
    event = make_event(StandInAgent(), name, {})
    make_approval_check(RUN_ID)(event)
    assert event.cancel_tool is False


@pytest.mark.parametrize(
    "name, inputs",
    [
        ("reset_account", {"username": "alee"}),
        ("grant_folder_access", {"username": "mallory", "folder": "domain-admins"}),
        ("delete_account", {"username": "alee"}),  # not ours: paused by default
    ],
)
def test_risky_tool_pauses_with_details(name, inputs):
    """The pause carries what the person needs to decide: tool, inputs, run ID."""
    with pytest.raises(InterruptException) as paused:
        make_approval_check(RUN_ID)(make_event(StandInAgent(), name, inputs))
    interrupt = paused.value.interrupt
    assert interrupt.name == INTERRUPT_NAME
    assert interrupt.reason == {"tool": name, "inputs": inputs, "run_id": RUN_ID}


def test_yes_lets_tool_run(capsys):
    """Answer "y": the call is not cancelled, and the approval is printed."""
    event = run_with_answer("reset_account", {"username": "alee"}, "y")
    assert event.cancel_tool is False
    assert f"[run {RUN_ID}] approved: reset_account" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["n", "", "yes please", "no", "ok"])
def test_anything_but_y_cancels(answer, capsys):
    """Any other answer cancels the call; the model gets DENIED_MESSAGE."""
    event = run_with_answer(
        "grant_folder_access", {"username": "mallory", "folder": "domain-admins"}, answer
    )
    assert event.cancel_tool == DENIED_MESSAGE
    assert f"[run {RUN_ID}] denied: grant_folder_access" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["y", "Y", " y ", "y\n"])
def test_y_any_case_or_spacing(answer):
    assert is_approved(answer)


@pytest.mark.parametrize("answer", ["n", "", "yes", "yy", None, True, 1])
def test_not_y(answer):
    """Only the letter y: not "yes", not True, not a missing answer."""
    assert not is_approved(answer)
