"""Unit tests for the Lambda handler.

These run locally with no AWS: we call lambda_handler directly, the way
Lambda would, passing a dict as `event` and None as `context`.

Covers:
  - a normal lookup returns the same answer as policy.py
  - an unknown category passes through as found=False
  - a missing field returns an error instead of raising
  - the run_id (correlation ID) is printed, so it lands in CloudWatch Logs,
    and doesn't change the answer; a call without one still works
"""

from lambda_function import lambda_handler
from policy import lookup_expense_limit


def test_handler_matches_policy():
    """The handler returns exactly what policy.py returns."""
    result = lambda_handler({"category": "meals", "city": "Chicago"}, None)
    assert result == lookup_expense_limit("meals", "Chicago")
    assert result["limit"] == 75


def test_handler_unknown_category():
    """An unknown category comes back as found=False, not an error."""
    result = lambda_handler({"category": "yacht", "city": "Monaco"}, None)
    assert result["found"] is False
    assert result["limit"] is None


def test_handler_missing_field():
    """No city given: the handler returns an error dict naming the field."""
    result = lambda_handler({"category": "meals"}, None)
    assert "city" in result["error"]
    assert "category" not in result["error"]


def test_handler_empty_event():
    """An empty event names both missing fields."""
    result = lambda_handler({}, None)
    assert "category" in result["error"]
    assert "city" in result["error"]


def test_handler_logs_run_id(capsys):
    """The run_id is printed with the request and doesn't change the answer."""
    event = {"category": "meals", "city": "Chicago", "run_id": "run123"}
    result = lambda_handler(event, None)
    assert result == lookup_expense_limit("meals", "Chicago")
    assert "run_id=run123" in capsys.readouterr().out


def test_handler_without_run_id(capsys):
    """A call with no run_id still works and logs run_id=none."""
    result = lambda_handler({"category": "meals", "city": "Chicago"}, None)
    assert result["limit"] == 75
    assert "run_id=none" in capsys.readouterr().out
