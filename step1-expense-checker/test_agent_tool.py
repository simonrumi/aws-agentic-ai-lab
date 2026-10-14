"""Unit tests for the agent's Lambda-backed tool.

No AWS here: the tool gets a fake Lambda client that records what it was
asked and hands back a canned answer, shaped like boto3's real response
(the payload is a byte stream, so we wrap the JSON in io.BytesIO).

Covers:
  - the tool sends the right function name and {category, city, run_id} input
  - the Lambda's answer comes back to the agent as a dict
  - a crashed Lambda (FunctionError) gives the model only a generic message;
    the crash detail is printed locally (tagged with the run ID), not
    passed to the model
  - a refused call (botocore ClientError) is handled the same way
"""

import io
import json

from botocore.exceptions import ClientError

from agent import LOOKUP_FAILED, make_lookup_tool


class FakeLambdaClient:
    """Stands in for boto3's Lambda client; remembers the last invoke call.

    Pass `raises` to make invoke throw instead of answering, as boto3 does
    when AWS refuses the call.
    """

    def __init__(
        self,
        answer: dict,
        function_error: str | None = None,
        raises: Exception | None = None,
    ):
        self.answer = answer
        self.function_error = function_error
        self.raises = raises
        self.last_call = None

    def invoke(self, **kwargs):
        self.last_call = kwargs
        if self.raises:
            raise self.raises
        response = {"Payload": io.BytesIO(json.dumps(self.answer).encode())}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


CHICAGO_MEALS = {
    "category": "meals",
    "city": "Chicago",
    "limit": 75,
    "currency": "USD",
    "rule": "Meals in Chicago is capped at 75 USD.",
    "found": True,
}


def test_tool_sends_right_request():
    """The tool invokes the named function with category and city as JSON."""
    client = FakeLambdaClient(CHICAGO_MEALS)
    lookup = make_lookup_tool(client, "expense-policy-lookup", "run123")
    lookup(category="meals", city="Chicago")
    assert client.last_call["FunctionName"] == "expense-policy-lookup"
    assert json.loads(client.last_call["Payload"]) == {
        "category": "meals",
        "city": "Chicago",
        "run_id": "run123",
    }


def test_tool_returns_lambda_answer():
    """Whatever the Lambda returns comes back unchanged."""
    lookup = make_lookup_tool(FakeLambdaClient(CHICAGO_MEALS), "fn", "run123")
    assert lookup(category="meals", city="Chicago") == CHICAGO_MEALS


def test_tool_hides_lambda_crash_from_model(capsys):
    """A FunctionError gives the model a generic message; the detail is printed locally."""
    crash = {"errorMessage": "boom", "errorType": "KeyError"}
    lookup = make_lookup_tool(FakeLambdaClient(crash, "Unhandled"), "fn", "run123")
    result = lookup(category="meals", city="Chicago")
    assert result == {"error": LOOKUP_FAILED}
    assert "boom" not in json.dumps(result)
    err = capsys.readouterr().err
    assert "boom" in err
    assert "run123" in err


def test_tool_hides_refused_call_from_model(capsys):
    """A ClientError (e.g. AccessDenied) never reaches the model; the detail is printed locally."""
    refusal = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "role-xyz denied"}},
        "Invoke",
    )
    lookup = make_lookup_tool(FakeLambdaClient({}, raises=refusal), "fn", "run123")
    result = lookup(category="meals", city="Chicago")
    assert result == {"error": LOOKUP_FAILED}
    assert "role-xyz" not in json.dumps(result)
    err = capsys.readouterr().err
    assert "role-xyz" in err
    assert "run123" in err
