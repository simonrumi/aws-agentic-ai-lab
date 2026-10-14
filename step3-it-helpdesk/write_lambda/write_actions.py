"""The helpdesk's actions that change things, run inside `helpdesk-write`.

Each function reads the rows it needs, checks them in Python, then writes
the whole changed row back with put_item. (Read, check, write: fine for a
one-person lab, where nothing else changes the row in between.)

Each returns a dict with
    outcome  "done", "no change" or "refused"
    message  a plain-English sentence for the agent to pass on
plus any useful detail. The handler (lambda_function.py) has already checked
the inputs, and writes the audit row afterwards.
"""

import secrets

# How many random ticket numbers open_ticket tries before giving up. A clash
# is already rare (900,000 possible numbers); this just stops the loop
# running forever.
MAX_TICKET_ID_TRIES = 5


def get_row(table, key: str) -> dict | None:
    """The row with this `pk`, or None if there isn't one."""
    return table.get_item(Key={"pk": key}).get("Item")


def new_ticket_id() -> str:
    """A random 6-digit ticket number (the seed tickets use 4 digits)."""
    return str(100000 + secrets.randbelow(900000))


def refused(message: str) -> dict:
    return {"outcome": "refused", "message": message}


def open_ticket(table, requester: str, subject: str, body: str) -> dict:
    """Open a new ticket for an existing account. Never overwrites a ticket."""
    if get_row(table, f"ACCOUNT#{requester}") is None:
        return refused(f"There is no account '{requester}'.")
    # Try up to MAX_TICKET_ID_TRIES random numbers until one isn't in use;
    # the `else` runs only if every try clashed (the loop never hit `break`).
    for _ in range(MAX_TICKET_ID_TRIES):
        ticket_id = new_ticket_id()
        if get_row(table, f"TICKET#{ticket_id}") is None:
            break
    else:
        return refused("Couldn't find a free ticket number; try again.")
    table.put_item(
        Item={
            "pk": f"TICKET#{ticket_id}",
            "kind": "ticket",
            "ticket_id": ticket_id,
            "requester": requester,
            "subject": subject,
            "body": body,
            "status": "open",
        }
    )
    return {
        "outcome": "done",
        "message": f"Opened ticket {ticket_id}.",
        "ticket_id": ticket_id,
    }


def reset_account(table, username: str) -> dict:
    """Unlock an account (set its status to "active")."""
    row = get_row(table, f"ACCOUNT#{username}")
    if row is None:
        return refused(f"There is no account '{username}'.")
    if row["status"] == "active":
        return {"outcome": "no change", "message": f"{username} is already active."}
    row["status"] = "active"
    table.put_item(Item=row)
    return {"outcome": "done", "message": f"Reset {username}: the account is now active."}


def grant_folder_access(table, username: str, folder: str) -> dict:
    """Add a user to a folder's members.

    [SEC] A protected folder (domain-admins) is refused here, whatever the
    agent or the person at the y/N prompt decided. The check is in this
    code, not the prompt, so no wording in a ticket can get round it.
    """
    if get_row(table, f"ACCOUNT#{username}") is None:
        return refused(f"There is no account '{username}'.")
    row = get_row(table, f"FOLDER#{folder}")
    if row is None:
        return refused(f"There is no folder '{folder}'.")
    if row["protected"]:
        return refused(
            f"The folder '{folder}' is protected: the helpdesk can't grant "
            "access to it. Changes need IT security's own process."
        )
    if username in row["members"]:
        return {
            "outcome": "no change",
            "message": f"{username} already has access to {folder}.",
        }
    row["members"] = row["members"] + [username]
    table.put_item(Item=row)
    return {"outcome": "done", "message": f"Gave {username} access to {folder}."}
