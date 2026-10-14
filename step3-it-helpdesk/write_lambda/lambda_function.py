"""The Lambda entry point for `helpdesk-write`.

AWS calls `lambda_handler` with the request as a dict (`event`), e.g.

    {"action": "reset_account", "username": "alee", "run_id": "a1b2c3d4"}

Same pattern as read_lambda/lambda_function.py: look up `action` in ACTIONS,
check that action's inputs, call the matching function in write_actions.py.
[SEC] Only the three write actions exist here, and the role allows GetItem
and PutItem on the one table — no DeleteItem, so even buggy code can't
remove rows.

New here: after each action runs, the handler saves an AUDIT# row recording
what was asked, the outcome (done / no change / refused), the run ID and
the time. Refusals are audited too: a refused attempt on domain-admins is
just what a security team wants to see. (Requests refused at the input
check never reach the table; they're in the CloudWatch log only.)

Upload this file and write_actions.py together in one zip. In the Lambda
console, the handler setting is `lambda_function.lambda_handler`, and the
environment variable TABLE_NAME holds the table name.
"""

import os
import re
import uuid
from datetime import datetime, timezone

import boto3

import write_actions

# [SEC] What each input must look like. Anything else is refused before the
# table is touched. fullmatch = the whole value must fit, not just part.
USERNAME = re.compile(r"[a-z]{1,32}")
FOLDER = re.compile(r"[a-z][a-z-]{0,62}")
SUBJECT = re.compile(r"[^\r\n]{1,120}")  # one line
BODY = re.compile(r".{1,2000}", re.DOTALL)  # may span lines

# action name -> (function, {input field: pattern it must match})
ACTIONS = {
    "open_ticket": (
        write_actions.open_ticket,
        {"requester": USERNAME, "subject": SUBJECT, "body": BODY},
    ),
    "reset_account": (write_actions.reset_account, {"username": USERNAME}),
    "grant_folder_access": (
        write_actions.grant_folder_access,
        {"username": USERNAME, "folder": FOLDER},
    ),
}

_table = None


def get_table():
    """The real table, made on first use and reused while the Lambda is warm."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def write_audit(table, action: str, inputs: dict, result: dict, run_id: str) -> None:
    """Save one AUDIT# row for an action that ran.

    The key starts with the time, so rows sort in time order; the run ID
    ties it to the agent's question; a short random tail keeps two writes
    in the same second apart.
    """
    time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    table.put_item(
        Item={
            "pk": f"AUDIT#{time}#{run_id}#{uuid.uuid4().hex[:6]}",
            "kind": "audit",
            "time": time,
            "run_id": run_id,
            "action": action,
            "inputs": inputs,
            "outcome": result["outcome"],
            "message": result["message"],
        }
    )


def handle(event: dict, table) -> dict:
    """Check the request, run the action against `table`, audit it.

    Returns the action's result, or {"error": ...} if the action is unknown
    or an input is missing or badly formed.

    `run_id` (optional) is the agent's correlation ID. We print it with the
    request (CloudWatch Logs) and store it in the audit row.
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
    result = function(table, **inputs)
    print(f"run_id={run_id} outcome={result['outcome']}")
    write_audit(table, action, inputs, result, run_id)
    return result


def lambda_handler(event: dict, context) -> dict:
    """What AWS calls. `context` is AWS's info about this run; not needed."""
    return handle(event, get_table())
