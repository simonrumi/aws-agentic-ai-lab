"""Integration tests: the real agent, the real model, the real Lambda.

No fakes here. Each test asks the agent one question through Bedrock and the
`expense-policy-lookup` Lambda, then checks:
  - the model called the tool, with the right category and city (AI judgment)
  - the tool returned the right limit (fixed rules, via Lambda)
  - the answer states that limit and the right verdict (within / over)

Skipped by a plain `pytest` run (see pytest.ini). Run on the personal laptop
only, with a live `lab` SSO login:

    .venv\\Scripts\\python -m pytest -m integration

Costs about $0.015 a run (6 questions at ~$0.0025).

The verdict check looks for words like "within" or "exceeds" in free text, so
a correct answer worded oddly can fail it. If one fails, read the printed
answer before deciding the agent is wrong. Proper answer scoring comes with
the Step 5 eval set.
"""

import json
import re

import pytest

from agent import ENV_FILE, make_agent, new_run_id, read_env

pytestmark = pytest.mark.integration

WITHIN = re.compile(r"\bwithin\b|\bunder\b|\byes\b|\ballowed\b|\bfine\b|\bok(ay)?\b")
OVER = re.compile(r"\bexceed|\bover\b|\babove\b|\bmore than\b")


@pytest.fixture(scope="module")
def settings():
    return read_env(ENV_FILE)


def run(settings, question):
    """Ask one question with a fresh agent; return (answer, tool calls).

    Each tool call is {"input": {...}, "result": {...}}, read from the agent's
    conversation history: the model's toolUse blocks hold what it asked for,
    and the matching toolResult blocks hold the Lambda's answer as JSON text.
    """
    agent = make_agent(settings, new_run_id())
    answer = str(agent(question)).strip()
    print(f"\nQ: {question}\nA: {answer}")

    inputs, results = {}, {}
    for message in agent.messages:
        for block in message["content"]:
            if "toolUse" in block:
                inputs[block["toolUse"]["toolUseId"]] = block["toolUse"]["input"]
            if "toolResult" in block:
                result = block["toolResult"]
                results[result["toolUseId"]] = json.loads(result["content"][0]["text"])
    calls = [{"input": inputs[i], "result": results.get(i)} for i in inputs]
    return answer, calls


def find_call(calls, category, city):
    """The tool call for this category and city, or None."""
    for call in calls:
        given = call["input"]
        if (
            given.get("category", "").strip().lower() == category
            and given.get("city", "").strip().lower() == city
        ):
            return call
    return None


@pytest.mark.parametrize(
    "question, category, city, limit, verdict",
    [
        ("Can I spend $70 on dinner in Chicago?", "meals", "chicago", 75, "within"),
        ("I took a $55 taxi in Denver. Is that OK?", "taxi", "denver", 40, "over"),
        ("Is a $300 hotel night in New York OK?", "hotel", "new york", 350, "within"),
        ("I spent $60 on lunch in Boston. Is that OK?", "meals", "boston", 50, "over"),
    ],
)
def test_verdict(settings, question, category, city, limit, verdict):
    """The model picks the right lookup, and the answer gives the limit and verdict."""
    answer, calls = run(settings, question)
    call = find_call(calls, category, city)
    assert call, f"no tool call for {category}/{city}; calls were {calls}"
    assert call["result"]["limit"] == limit

    text = answer.lower()
    assert str(limit) in text
    if verdict == "over":
        assert OVER.search(text), "answer doesn't say the amount is over the limit"
    else:
        assert WITHIN.search(text), "answer doesn't say the amount is within the limit"
        assert not OVER.search(text), "answer suggests the amount is over the limit"


def test_unknown_category(settings):
    """No rule for yachts: the tool is asked, finds nothing, and the answer says so."""
    answer, calls = run(settings, "Can I expense a yacht rental in Monaco?")
    assert calls, "the model guessed instead of calling the tool"
    assert all(call["result"]["found"] is False for call in calls)
    text = answer.lower()
    assert re.search(r"\bno\b|\bnot\b", text) and re.search(r"polic|rule", text)


def test_off_topic(settings):
    """An off-topic question: no tool call, and the model declines to answer it."""
    answer, calls = run(settings, "What's the capital of France?")
    assert calls == []
    assert "paris" not in answer.lower()
