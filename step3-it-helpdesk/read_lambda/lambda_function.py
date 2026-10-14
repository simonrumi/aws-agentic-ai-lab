"""The Lambda entry point for `helpdesk-read`.

AWS calls `lambda_handler` with the request as a dict (`event`), e.g.

    {"action": "get_ticket", "ticket_id": "1042", "run_id": "a1b2c3d4"}

The handler looks up `action` in ACTIONS, checks that action's inputs, then
calls the matching function in read_actions.py. [SEC] Only the three read
actions exist here, so this Lambda can't be asked to change anything; and its
role allows only GetItem on the one table, so AWS would refuse a write anyway.

Upload this file and read_actions.py together in one zip. In the Lambda
console, the handler setting is `lambda_function.lambda_handler`, and the
environment variable TABLE_NAME holds the table name.
"""

import os
import re

import boto3

import read_actions

# [SEC] What each input must look like. Anything else is refused before the
# table is touched. fullmatch = the whole value must fit, not just part.
USERNAME = re.compile(r"[a-z]{1,32}")
FOLDER = re.compile(r"[a-z][a-z-]{0,62}")
TICKET_ID = re.compile(r"[0-9]{1,10}")

# action name -> (function, {input field: pattern it must match})
ACTIONS = {
    "get_account_status": (read_actions.get_account_status, {"username": USERNAME}),
    "list_folder_access": (read_actions.list_folder_access, {"folder": FOLDER}),
    "get_ticket": (read_actions.get_ticket, {"ticket_id": TICKET_ID}),
}

_table = None


def get_table():
    """The real table, made on first use and reused while the Lambda is warm."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def handle(event: dict, table) -> dict:
    """Check the request and run the action against `table`.

    Returns the action's result, or {"error": ...} if the action is unknown
    or an input is missing or badly formed.

    `run_id` (optional) is the agent's correlation ID. We print it with the
    request; Lambda sends anything printed to CloudWatch Logs, so searching
    there for the ID finds this call. It doesn't affect the answer.
    """
    action = event.get("action")
    run_id = event.get("run_id", "none")
    if action not in ACTIONS:
        print(f"run_id={run_id} action={str(action)[:40]!r} refused: unknown action")
        return {"error": f"Unknown action. Allowed: {', '.join(ACTIONS)}."}
    function, fields = ACTIONS[action]
    inputs = {name: event.get(name) for name in fields}
    print(f"run_id={run_id} action={action} inputs={inputs}")
    bad = [
        name
        for name, pattern in fields.items()
        if not (isinstance(inputs[name], str) and pattern.fullmatch(inputs[name]))
    ]
    if bad:
        return {"error": f"Missing or badly formed field(s): {', '.join(bad)}."}
    return function(table, **inputs)


def lambda_handler(event: dict, context) -> dict:
    """What AWS calls. `context` is AWS's info about this run; not needed."""
    return handle(event, get_table())
