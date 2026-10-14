"""The helpdesk's read-only actions, run inside the `helpdesk-read` Lambda.

Each function fetches one row from the `helpdesk-lab` table by its exact key
(one GetItem) and returns only the fields the agent needs — never the
internal `pk` / `kind`. A missing row comes back as found=False, not an
error. The table is passed in, so tests can hand in a fake one.

The handler (lambda_function.py) has already checked the inputs.
"""


def get_row(table, key: str) -> dict | None:
    """The row with this `pk`, or None if there isn't one."""
    return table.get_item(Key={"pk": key}).get("Item")


def get_account_status(table, username: str) -> dict:
    """An account's name, department and status ("active" / "locked")."""
    row = get_row(table, f"ACCOUNT#{username}")
    if row is None:
        return {"found": False, "username": username}
    return {
        "found": True,
        "username": row["username"],
        "name": row["name"],
        "department": row["department"],
        "status": row["status"],
    }


def list_folder_access(table, folder: str) -> dict:
    """Who can open a folder, and whether it's protected."""
    row = get_row(table, f"FOLDER#{folder}")
    if row is None:
        return {"found": False, "folder": folder}
    return {
        "found": True,
        "folder": row["folder"],
        "members": row["members"],
        "protected": row["protected"],
    }


def get_ticket(table, ticket_id: str) -> dict:
    """A ticket's requester, subject, body and status.

    [SEC] The body is whatever the requester typed, so it may hold
    instructions aimed at the agent (ticket 1042 does). It is returned as it
    is; the agent's tool (Step 3.4) marks it as data, not orders.
    """
    row = get_row(table, f"TICKET#{ticket_id}")
    if row is None:
        return {"found": False, "ticket_id": ticket_id}
    return {
        "found": True,
        "ticket_id": row["ticket_id"],
        "requester": row["requester"],
        "subject": row["subject"],
        "body": row["body"],
        "status": row["status"],
    }
