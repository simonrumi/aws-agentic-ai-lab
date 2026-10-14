"""Unit tests for the three read actions.

No AWS here: each test gets a fake table loaded with the real seed data from
seed_data.py, so the tests check the rows Step 3 actually uses.

Covers:
  - each action returns the right fields for a known row
  - an unknown key comes back as found=False, not an error
  - the internal `pk` / `kind` fields never leak out
  - [SEC] ticket 1042's body comes back unchanged (marking it as data is the
    agent's job, Step 3.4)
"""

import pytest

from fake_table import FakeTable
from read_actions import get_account_status, get_ticket, list_folder_access
from seed_data import POISONED_TICKET_BODY, build_items


@pytest.fixture
def table():
    return FakeTable(build_items())


def test_account_status_of_locked_account(table):
    assert get_account_status(table, "alee") == {
        "found": True,
        "username": "alee",
        "name": "Alex Lee",
        "department": "Finance",
        "status": "locked",
    }


def test_account_status_unknown_user(table):
    assert get_account_status(table, "nobody") == {"found": False, "username": "nobody"}


def test_folder_access_of_protected_folder(table):
    assert list_folder_access(table, "domain-admins") == {
        "found": True,
        "folder": "domain-admins",
        "members": ["tchen"],
        "protected": True,
    }


def test_folder_access_of_empty_folder(table):
    result = list_folder_access(table, "hr")
    assert result["members"] == []
    assert result["protected"] is False


def test_folder_access_unknown_folder(table):
    assert list_folder_access(table, "secret") == {"found": False, "folder": "secret"}


def test_get_poisoned_ticket_returns_body_unchanged(table):
    result = get_ticket(table, "1042")
    assert result["found"] is True
    assert result["requester"] == "mallory"
    assert result["body"] == POISONED_TICKET_BODY


def test_get_ticket_unknown_id(table):
    assert get_ticket(table, "9999") == {"found": False, "ticket_id": "9999"}


@pytest.mark.parametrize(
    "result",
    [
        lambda t: get_account_status(t, "jsmith"),
        lambda t: list_folder_access(t, "marketing"),
        lambda t: get_ticket(t, "1040"),
    ],
)
def test_internal_fields_never_returned(table, result):
    output = result(table)
    assert "pk" not in output
    assert "kind" not in output
