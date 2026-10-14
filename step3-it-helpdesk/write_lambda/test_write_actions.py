"""Unit tests for the three write actions.

No AWS here: each test gets a fake table loaded with the real seed data.

Covers, for each action: the change it makes ("done"), when it changes
nothing ("no change"), and when it refuses — checking the table each time,
not just the message. In particular:
  - [SEC] a grant to the protected domain-admins folder is refused and
    nothing is written
  - open_ticket never overwrites an existing ticket
"""

import pytest

import write_actions
from fake_table import FakeTable
from seed_data import build_items
from write_actions import grant_folder_access, open_ticket, reset_account


@pytest.fixture
def table():
    return FakeTable(build_items())


# --- open_ticket -----------------------------------------------------------

def test_open_ticket_creates_an_open_ticket(table):
    result = open_ticket(table, "jsmith", "Monitor flickers", "Since this morning.")
    assert result["outcome"] == "done"
    ticket = table.rows[f"TICKET#{result['ticket_id']}"]
    assert ticket["requester"] == "jsmith"
    assert ticket["subject"] == "Monitor flickers"
    assert ticket["status"] == "open"
    assert ticket["kind"] == "ticket"


def test_open_ticket_id_is_six_digits(table):
    ticket_id = open_ticket(table, "jsmith", "s", "b")["ticket_id"]
    assert len(ticket_id) == 6 and ticket_id.isdigit()


def test_open_ticket_never_overwrites(table, monkeypatch):
    ids = iter(["1042", "555555"])  # first try clashes with a seed ticket
    monkeypatch.setattr(write_actions, "new_ticket_id", lambda: next(ids))
    result = open_ticket(table, "jsmith", "s", "b")
    assert result["ticket_id"] == "555555"
    assert table.rows["TICKET#1042"]["requester"] == "mallory"  # untouched


def test_open_ticket_gives_up_after_max_tries(table, monkeypatch):
    monkeypatch.setattr(write_actions, "new_ticket_id", lambda: "1042")
    assert open_ticket(table, "jsmith", "s", "b")["outcome"] == "refused"
    assert table.writes() == []


def test_open_ticket_unknown_requester(table):
    assert open_ticket(table, "nobody", "s", "b")["outcome"] == "refused"
    assert table.writes() == []


# --- reset_account ---------------------------------------------------------

def test_reset_unlocks_a_locked_account(table):
    result = reset_account(table, "alee")
    assert result["outcome"] == "done"
    assert table.rows["ACCOUNT#alee"]["status"] == "active"
    assert table.rows["ACCOUNT#alee"]["name"] == "Alex Lee"  # rest of row kept


def test_reset_of_active_account_changes_nothing(table):
    assert reset_account(table, "jsmith")["outcome"] == "no change"
    assert table.writes() == []


def test_reset_unknown_account(table):
    assert reset_account(table, "nobody")["outcome"] == "refused"
    assert table.writes() == []


# --- grant_folder_access ---------------------------------------------------

def test_grant_adds_member(table):
    result = grant_folder_access(table, "priya", "marketing")
    assert result["outcome"] == "done"
    assert table.rows["FOLDER#marketing"]["members"] == ["jsmith", "priya"]


def test_grant_existing_member_changes_nothing(table):
    assert grant_folder_access(table, "jsmith", "marketing")["outcome"] == "no change"
    assert table.writes() == []


def test_grant_to_protected_folder_is_refused(table):
    result = grant_folder_access(table, "mallory", "domain-admins")
    assert result["outcome"] == "refused"
    assert "protected" in result["message"]
    assert table.rows["FOLDER#domain-admins"]["members"] == ["tchen"]
    assert table.writes() == []


@pytest.mark.parametrize(
    "username, folder", [("nobody", "marketing"), ("priya", "secret")]
)
def test_grant_unknown_user_or_folder(table, username, folder):
    assert grant_folder_access(table, username, folder)["outcome"] == "refused"
    assert table.writes() == []
