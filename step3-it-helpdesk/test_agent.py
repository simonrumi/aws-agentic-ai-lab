"""Unit tests for agent.py's approval loop.

No model and no AWS here: a stand-in agent hands back canned results, and a
stand-in person gives canned answers.

  - the y/N line names the tool, its inputs and the run ID
  - each of our pauses is put to the person, and the answer goes back in
    Strands' interruptResponse format, matched by interrupt ID
  - [SEC] a pause that isn't ours is answered "n" without asking
  - run_question keeps resuming while the agent is paused, then returns the
    final result; with no pause, the person is never asked
  - the agent runs as lab-helpdesk, not the profile in the shared .env
  - an AWS error (e.g. Bedrock unavailable, login expired) skips that one
    question with a one-line message; a bug in our code still stops the run
  - [SEC] a missing guardrail ID or version stops the agent with a clear error
  - the guardrail recorder keeps only guardrail reports; the summary line
    names each finding with its model call, direction (input / output) and
    confidence; a reply the guardrail caught is shown as the model wrote it
"""

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from strands.interrupt import Interrupt

import agent as agent_module
from agent import (
    answer_interrupts,
    approval_question,
    ask,
    blocked_replies,
    check_guardrail_settings,
    guardrail_summary,
    make_guardrail_recorder,
    run_question,
)
from approval import INTERRUPT_NAME

RESET_REASON = {"tool": "reset_account", "inputs": {"username": "alee"}, "run_id": "run123"}


class StandInPerson:
    """Gives canned answers in order and remembers what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0)


class StandInAgent:
    """Hands back canned results in order and remembers what it was sent."""

    def __init__(self, *results):
        self.results = list(results)
        self.sent = []

    def __call__(self, prompt):
        self.sent.append(prompt)
        return self.results.pop(0)


def paused(*interrupts):
    return SimpleNamespace(stop_reason="interrupt", interrupts=list(interrupts))


def finished(text: str):
    return SimpleNamespace(stop_reason="end_turn", interrupts=None, text=text)


def test_approval_question_shows_tool_inputs_and_run_id():
    assert approval_question(RESET_REASON) == (
        "[run run123] Approve reset_account(username='alee')? (y/N): "
    )


def test_approval_question_several_inputs():
    reason = {
        "tool": "grant_folder_access",
        "inputs": {"username": "mallory", "folder": "domain-admins"},
        "run_id": "run123",
    }
    assert "grant_folder_access(username='mallory', folder='domain-admins')" in (
        approval_question(reason)
    )


def test_answer_interrupts_asks_and_formats():
    """Each answer goes back under its own interrupt's ID."""
    person = StandInPerson("y", "n")
    interrupts = [
        Interrupt("id-1", INTERRUPT_NAME, RESET_REASON),
        Interrupt("id-2", INTERRUPT_NAME, {**RESET_REASON, "tool": "grant_folder_access"}),
    ]
    assert answer_interrupts(interrupts, person) == [
        {"interruptResponse": {"interruptId": "id-1", "response": "y"}},
        {"interruptResponse": {"interruptId": "id-2", "response": "n"}},
    ]
    assert len(person.asked) == 2


def test_unknown_interrupt_denied_without_asking():
    """[SEC] A pause we didn't raise gets "n", and the person isn't asked."""
    person = StandInPerson()
    responses = answer_interrupts([Interrupt("id-9", "something-else", {})], person)
    assert responses == [{"interruptResponse": {"interruptId": "id-9", "response": "n"}}]
    assert person.asked == []


def test_run_question_without_pause_never_asks():
    done = finished("alee's account is locked.")
    agent = StandInAgent(done)
    person = StandInPerson()
    assert run_question(agent, "Is alee locked?", person) is done
    assert agent.sent == ["Is alee locked?"]
    assert person.asked == []


def test_run_question_resumes_until_finished():
    """Two pauses in a row: each answer is sent back, then the final result returns."""
    done = finished("Done.")
    agent = StandInAgent(
        paused(Interrupt("id-1", INTERRUPT_NAME, RESET_REASON)),
        paused(Interrupt("id-2", INTERRUPT_NAME, RESET_REASON)),
        done,
    )
    person = StandInPerson("y", "n")
    assert run_question(agent, "Unlock alee.", person) is done
    assert agent.sent == [
        "Unlock alee.",
        [{"interruptResponse": {"interruptId": "id-1", "response": "y"}}],
        [{"interruptResponse": {"interruptId": "id-2", "response": "n"}}],
    ]


def test_agent_runs_as_its_own_profile():
    """[SEC] Never the shared .env's AWS_PROFILE (Step 2's lab-agent) or `lab`."""
    assert agent_module.AGENT_PROFILE == "lab-helpdesk"


# ---------------------------------------------------------------------------
# ask: an AWS error skips one question with one line, not a traceback
# ---------------------------------------------------------------------------


class FailingAgent:
    """A stand-in agent whose model call fails the way AWS's did."""

    def __init__(self, error: Exception):
        self.error = error

    def __call__(self, prompt):
        raise self.error


BEDROCK_DOWN = ClientError(
    {
        "Error": {
            "Code": "ServiceUnavailableException",
            "Message": "Bedrock is unable to process your request.\n└ Model id: x",
        }
    },
    "ConverseStream",
)


def test_ask_skips_question_on_aws_error(capsys):
    """Returns None and prints one short line with the run ID; no traceback."""
    usage = ask({}, "Give priya marketing.", build_agent=lambda s, r, g: FailingAgent(BEDROCK_DOWN))
    assert usage is None
    out = capsys.readouterr().out
    assert "Question skipped: AWS error:" in out
    assert "ServiceUnavailableException" in out
    assert "Model id" not in out  # only the first line of the error
    assert "Traceback" not in out


def test_ask_skips_question_on_expired_login(capsys):
    """No answer from AWS at all (BotoCoreError, e.g. SSO expired) is skipped too."""
    usage = ask({}, "Q", build_agent=lambda s, r, g: FailingAgent(NoCredentialsError()))
    assert usage is None
    assert "Question skipped" in capsys.readouterr().out


def test_ask_lets_our_own_bugs_through():
    """[SEC] A bug in our code is not an AWS error: it still stops the run."""
    with pytest.raises(KeyError):
        ask({}, "Q", build_agent=lambda s, r, g: FailingAgent(KeyError("oops")))


# ---------------------------------------------------------------------------
# guardrail_settings: the agent never runs without its guardrail
# ---------------------------------------------------------------------------


def test_guardrail_settings_present_passes():
    """Both values in .env: no error."""
    check_guardrail_settings({"GUARDRAIL_ID": "gr-123", "GUARDRAIL_VERSION": "2"})


def test_guardrail_settings_missing_id_stops():
    """[SEC] No GUARDRAIL_ID: a clear error, not an unguarded agent."""
    with pytest.raises(ValueError, match="GUARDRAIL_ID missing from .env"):
        check_guardrail_settings({"GUARDRAIL_VERSION": "2"})


def test_guardrail_settings_blank_version_stops():
    """[SEC] A blank value counts as missing."""
    with pytest.raises(ValueError, match="GUARDRAIL_VERSION missing"):
        check_guardrail_settings({"GUARDRAIL_ID": "gr-123", "GUARDRAIL_VERSION": ""})


# ---------------------------------------------------------------------------
# The guardrail recorder and its one-line summary
# ---------------------------------------------------------------------------
# Reports are shaped like Bedrock's guardrail trace (GuardrailTraceAssessment
# in boto3's bedrock-runtime model): inputAssessment maps the guardrail ID to
# one check; outputAssessments maps it to a list of checks.

PASSWORD_TOPIC = {
    "topicPolicy": {
        "topics": [{"name": "Password sharing", "type": "DENY", "action": "BLOCKED", "detected": True}]
    }
}
PROMPT_ATTACK = {
    "contentPolicy": {
        "filters": [
            {"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "BLOCKED", "detected": True}
        ]
    }
}
INSULT = {
    "contentPolicy": {
        "filters": [{"type": "INSULTS", "confidence": "HIGH", "action": "BLOCKED", "detected": True}]
    }
}
NOTHING_FOUND = {
    "contentPolicy": {
        "filters": [{"type": "HATE", "confidence": "NONE", "action": "NONE", "detected": False}]
    }
}


def metadata_chunk(report: dict) -> dict:
    """A stream chunk carrying a guardrail report, as Strands passes it on."""
    return {"metadata": {"usage": {}, "trace": {"guardrail": report}}}


def test_recorder_keeps_guardrail_reports_only():
    record, reports = make_guardrail_recorder()
    report = {"inputAssessment": {"gr-123": NOTHING_FOUND}}
    record(event={"contentBlockDelta": {"delta": {"text": "Hi"}}})  # streamed text
    record(event={"metadata": {"usage": {}}})  # metadata, but no trace
    record(data="Hi", delta={"text": "Hi"})  # a Strands event with no `event`
    record(event=metadata_chunk(report))
    assert reports == [report]


def test_summary_no_report():
    assert guardrail_summary([]) == "[guardrail: no report received]"


def test_summary_nothing_detected():
    reports = [{"inputAssessment": {"gr-123": NOTHING_FOUND}}, {"inputAssessment": {"gr-123": {}}}]
    assert guardrail_summary(reports) == "[guardrail: 2 model calls checked; nothing detected]"


def test_summary_denied_topic_on_input():
    reports = [{"inputAssessment": {"gr-123": PASSWORD_TOPIC}}]
    assert guardrail_summary(reports) == (
        '[guardrail: 1 model call checked; call 1 input: denied topic "Password sharing" (BLOCKED)]'
    )


def test_summary_content_filter_on_output():
    reports = [{"outputAssessments": {"gr-123": [INSULT]}}]
    assert guardrail_summary(reports) == (
        "[guardrail: 1 model call checked; call 1 output: content filter INSULTS, confidence HIGH (BLOCKED)]"
    )


def test_summary_names_the_call_a_finding_came_from():
    """[SEC] The ticket 1042 experiment: a finding first seen on call 2's input
    came from a tool result, not from the question."""
    reports = [
        {"inputAssessment": {"gr-123": NOTHING_FOUND}},
        {"inputAssessment": {"gr-123": PROMPT_ATTACK}},
    ]
    assert guardrail_summary(reports) == (
        "[guardrail: 2 model calls checked; call 2 input: prompt attack, confidence HIGH (BLOCKED)]"
    )


def test_summary_lists_several_findings():
    reports = [
        {
            "inputAssessment": {
                "gr-123": {
                    "topicPolicy": PASSWORD_TOPIC["topicPolicy"],
                    "contentPolicy": INSULT["contentPolicy"],
                }
            },
            "outputAssessments": {"gr-123": [PROMPT_ATTACK]},
        }
    ]
    assert guardrail_summary(reports) == (
        "[guardrail: 1 model call checked; "
        'call 1 input: denied topic "Password sharing" (BLOCKED); '
        "call 1 input: content filter INSULTS, confidence HIGH (BLOCKED); "
        "call 1 output: prompt attack, confidence HIGH (BLOCKED)]"
    )


def test_summary_shows_low_confidence():
    """A filter that blocks on a LOW-confidence match says so: the clue for
    an over-sensitive filter (Misconduct on a plain unlock request)."""
    misconduct_low = {
        "contentPolicy": {
            "filters": [
                {"type": "MISCONDUCT", "confidence": "LOW", "action": "BLOCKED", "detected": True}
            ]
        }
    }
    reports = [{"inputAssessment": {"gr-123": misconduct_low}}]
    assert guardrail_summary(reports) == (
        "[guardrail: 1 model call checked; "
        "call 1 input: content filter MISCONDUCT, confidence LOW (BLOCKED)]"
    )


def test_blocked_replies_shows_the_hidden_reply():
    """[SEC] When the guardrail caught a reply, show what the model wrote."""
    reports = [
        {"inputAssessment": {"gr-123": NOTHING_FOUND}},
        {
            "inputAssessment": {"gr-123": NOTHING_FOUND},
            "outputAssessments": {"gr-123": [PASSWORD_TOPIC]},
            "modelOutput": ["Ticket 1042 looks suspicious."],
        },
    ]
    assert blocked_replies(reports) == [
        '[guardrail: call 2 reply before the guardrail: "Ticket 1042 looks suspicious."]'
    ]


def test_blocked_replies_skips_replies_that_passed():
    """A reply the guardrail let through is already on screen: not repeated."""
    reports = [{"inputAssessment": {"gr-123": NOTHING_FOUND}, "modelOutput": ["Hello."]}]
    assert blocked_replies(reports) == []


def test_blocked_replies_without_model_output():
    """Bedrock may leave modelOutput out; then there's nothing to show."""
    reports = [{"outputAssessments": {"gr-123": [PASSWORD_TOPIC]}}]
    assert blocked_replies(reports) == []


class FinishedResult:
    """A stand-in for Strands' AgentResult: a finished answer with stats.

    A class because ask() prints `str(result)`, and only a class can say what
    str() gives back (its __str__ method).
    """

    stop_reason = "end_turn"
    interrupts = None

    def __init__(self, text: str):
        self.text = text
        usage = {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}
        self.metrics = SimpleNamespace(tool_metrics={}, accumulated_usage=usage)

    def __str__(self):
        return self.text


def make_guarded_stand_in_agent(record_guardrail, report: dict):
    """A stand-in agent that, like the real one, feeds the recorder a
    guardrail report, then finishes with a canned answer."""

    def stand_in_agent(prompt):
        record_guardrail(event=metadata_chunk(report))
        return FinishedResult("Sorry, I can't help with that request.")

    return stand_in_agent


def test_ask_prints_the_guardrail_line(capsys):
    """ask() gives each question a fresh recorder and prints its summary."""
    report = {"inputAssessment": {"gr-123": PASSWORD_TOPIC}}

    def build_guarded_agent(settings, run_id, record_guardrail):
        return make_guarded_stand_in_agent(record_guardrail, report)

    ask({}, "What is tchen's password?", build_agent=build_guarded_agent)
    out = capsys.readouterr().out
    assert "A: Sorry, I can't help with that request." in out
    assert 'call 1 input: denied topic "Password sharing" (BLOCKED)' in out
