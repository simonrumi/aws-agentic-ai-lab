"""Unit tests for the `helpdesk-read` handler.

No AWS here: we call `handle` directly with a fake table, the way
lambda_handler would with the real one.

Covers:
  - each action reaches the right function with the right input
  - [SEC] an unknown action is refused, including the write actions, and the
    table is never touched
  - [SEC] a missing, badly formed or non-text input is refused before the
    table is touched
  - fields the action doesn't use are ignored
  - the run_id is printed (so it lands in CloudWatch Logs); a call without
    one still works
  - lambda_handler passes the request on to handle with the real table
"""

import pytest

from fake_table import FakeTable
from read_lambda import lambda_function
from read_lambda.lambda_function import handle
from seed_data import build_items


@pytest.fixture
def table():
    return FakeTable(build_items())


@pytest.mark.parametrize(
    "event, expected_key, field, value",
    [
        ({"action": "get_account_status", "username": "alee"}, "ACCOUNT#alee", "status", "locked"),
        ({"action": "list_folder_access", "folder": "domain-admins"}, "FOLDER#domain-admins", "protected", True),
        ({"action": "get_ticket", "ticket_id": "1042"}, "TICKET#1042", "requester", "mallory"),
    ],
)
def test_each_action_reaches_its_function(table, event, expected_key, field, value):
    result = handle(event, table)
    assert result[field] == value
    assert table.calls == [("get_item", {"pk": expected_key})]


@pytest.mark.parametrize(
    "action",
    ["grant_folder_access", "reset_account", "delete_everything", None, ""],
)
def test_unknown_action_is_refused(table, action):
    result = handle({"action": action, "username": "mallory"}, table)
    assert result["error"].startswith("Unknown action")
    assert table.calls == []


@pytest.mark.parametrize(
    "event",
    [
        {"action": "get_account_status"},  # missing
        {"action": "get_account_status", "username": ""},
        {"action": "get_account_status", "username": "ALEE"},
        {"action": "get_account_status", "username": "alee; drop"},
        {"action": "list_folder_access", "folder": "../secret"},
        {"action": "list_folder_access", "folder": "-marketing"},
        {"action": "get_ticket", "ticket_id": "1042abc"},
        {"action": "get_ticket", "ticket_id": 1042},  # a number, not text
        {"action": "get_ticket", "ticket_id": "1" * 11},  # too long
    ],
)
def test_bad_input_is_refused_before_the_table(table, event):
    result = handle(event, table)
    assert result["error"].startswith("Missing or badly formed")
    assert table.calls == []


def test_unused_fields_are_ignored(table):
    event = {"action": "get_ticket", "ticket_id": "1040", "folder": "domain-admins"}
    assert handle(event, table)["ticket_id"] == "1040"


def test_run_id_is_printed(table, capsys):
    handle({"action": "get_ticket", "ticket_id": "1040", "run_id": "abc12345"}, table)
    assert "run_id=abc12345" in capsys.readouterr().out


def test_call_without_run_id_works(table, capsys):
    assert handle({"action": "get_ticket", "ticket_id": "1040"}, table)["found"] is True
    assert "run_id=none" in capsys.readouterr().out


def test_lambda_handler_uses_the_real_table(table, monkeypatch):
    monkeypatch.setattr(lambda_function, "get_table", lambda: table)
    result = lambda_function.lambda_handler({"action": "get_ticket", "ticket_id": "1041"}, None)
    assert result["requester"] == "alee"
