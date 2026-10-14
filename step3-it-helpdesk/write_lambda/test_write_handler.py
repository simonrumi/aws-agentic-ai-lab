"""Unit tests for the `helpdesk-write` handler.

No AWS here: we call `handle` directly with a fake table.

Covers:
  - each action reaches the right function and its change is made
  - every action that runs leaves one AUDIT# row (action, inputs, outcome,
    message, run ID, time) — [SEC] including a refused domain-admins grant
  - [SEC] an unknown action is refused, including the read actions, and the
    table is never touched
  - [SEC] a missing, badly formed, too long or non-text input is refused
    before the table is touched
  - the run_id is printed (so it lands in CloudWatch Logs)
  - lambda_handler passes the request on to handle with the real table
"""

import re

import pytest

from fake_table import FakeTable
from seed_data import build_items
from write_lambda import lambda_function
from write_lambda.lambda_function import handle


@pytest.fixture
def table():
    return FakeTable(build_items())


def test_reset_is_made_and_audited(table):
    event = {"action": "reset_account", "username": "alee", "run_id": "abc12345"}
    result = handle(event, table)
    assert result["outcome"] == "done"
    assert table.rows["ACCOUNT#alee"]["status"] == "active"
    [audit] = table.rows_of_kind("audit")
    assert audit["action"] == "reset_account"
    assert audit["inputs"] == {"username": "alee"}
    assert audit["outcome"] == "done"
    assert audit["message"] == result["message"]
    assert audit["run_id"] == "abc12345"


def test_audit_key_and_time_format(table):
    handle({"action": "reset_account", "username": "alee", "run_id": "abc12345"}, table)
    [audit] = table.rows_of_kind("audit")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", audit["time"])
    assert re.fullmatch(rf"AUDIT#{re.escape(audit['time'])}#abc12345#[0-9a-f]{{6}}", audit["pk"])


def test_grant_is_made_and_audited(table):
    event = {"action": "grant_folder_access", "username": "priya", "folder": "marketing"}
    assert handle(event, table)["outcome"] == "done"
    assert "priya" in table.rows["FOLDER#marketing"]["members"]
    assert len(table.rows_of_kind("audit")) == 1


def test_open_ticket_is_made_and_audited(table):
    event = {"action": "open_ticket", "requester": "priya", "subject": "VPN", "body": "VPN drops.\nTwice today."}
    result = handle(event, table)
    assert table.rows[f"TICKET#{result['ticket_id']}"]["body"] == "VPN drops.\nTwice today."
    [audit] = table.rows_of_kind("audit")
    assert audit["inputs"]["subject"] == "VPN"


def test_refused_protected_grant_is_still_audited(table):
    event = {"action": "grant_folder_access", "username": "mallory", "folder": "domain-admins", "run_id": "evil0001"}
    result = handle(event, table)
    assert result["outcome"] == "refused"
    assert table.rows["FOLDER#domain-admins"]["members"] == ["tchen"]
    [audit] = table.rows_of_kind("audit")
    assert audit["outcome"] == "refused"
    assert audit["inputs"] == {"username": "mallory", "folder": "domain-admins"}
    assert audit["run_id"] == "evil0001"
    assert table.writes() == [audit["pk"]]  # the audit row is the only write


def test_no_change_is_audited(table):
    handle({"action": "reset_account", "username": "jsmith"}, table)
    [audit] = table.rows_of_kind("audit")
    assert audit["outcome"] == "no change"


@pytest.mark.parametrize(
    "action",
    ["get_ticket", "get_account_status", "delete_account", None, ""],
)
def test_unknown_action_is_refused(table, action):
    result = handle({"action": action, "username": "alee", "ticket_id": "1042"}, table)
    assert result["error"].startswith("Unknown action")
    assert table.calls == []


@pytest.mark.parametrize(
    "event",
    [
        {"action": "reset_account"},  # missing
        {"action": "reset_account", "username": "Alee"},
        {"action": "grant_folder_access", "username": "priya"},  # no folder
        {"action": "grant_folder_access", "username": "priya", "folder": "../hr"},
        {"action": "open_ticket", "requester": "priya", "subject": "", "body": "b"},
        {"action": "open_ticket", "requester": "priya", "subject": "two\nlines", "body": "b"},
        {"action": "open_ticket", "requester": "priya", "subject": "s" * 121, "body": "b"},
        {"action": "open_ticket", "requester": "priya", "subject": "s", "body": "b" * 2001},
        {"action": "open_ticket", "requester": "priya", "subject": "s", "body": ["not", "text"]},
    ],
)
def test_bad_input_is_refused_before_the_table(table, event):
    result = handle(event, table)
    assert result["error"].startswith("Missing or badly formed")
    assert table.calls == []


def test_run_id_and_outcome_are_printed(table, capsys):
    handle({"action": "reset_account", "username": "alee", "run_id": "abc12345"}, table)
    out = capsys.readouterr().out
    assert "run_id=abc12345 action=reset_account" in out
    assert "run_id=abc12345 outcome=done" in out


def test_lambda_handler_uses_the_real_table(table, monkeypatch):
    monkeypatch.setattr(lambda_function, "get_table", lambda: table)
    result = lambda_function.lambda_handler({"action": "reset_account", "username": "alee"}, None)
    assert result["outcome"] == "done"
