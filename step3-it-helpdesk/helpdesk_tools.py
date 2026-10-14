"""The helpdesk agent's six tools.

Each tool sends one request to a Lambda, as Step 1's `lookup_expense_limit`
did:

- `helpdesk-read`:  get_account_status, list_folder_access, get_ticket
- `helpdesk-write`: open_ticket, reset_account, grant_folder_access

The Lambdas hold the real rules (input checks, the protected `domain-admins`
folder, audit rows). The tools only pass the request on, add the run ID, and
keep AWS error detail away from the model.

Two of the write tools change things. The approval pause before them is a
Strands hook (Step 3.4b), not part of the tools, so the tools stay simple and
the pause can't be skipped by calling a tool some other way.
"""

import json
import sys

from botocore.exceptions import ClientError
from strands import tool

# What the model sees when a Lambda call fails. The real error stays out of
# the model's context (it can hold role names and the account ID) and is
# printed locally instead.
HELPDESK_FAILED = (
    "The helpdesk service is unavailable. Try again later or contact IT "
    "support directly."
)


def call_lambda(lambda_client, function_name: str, payload: dict, run_id: str) -> dict:
    """Send one request to a helpdesk Lambda and return its answer.

    `payload` names the action and its inputs; the run ID is added here, so
    the model can't set or change it. A refused or crashed call gives back
    only HELPDESK_FAILED; the detail is printed, tagged with the run ID.
    The Lambda's own answers, including its {"error": ...} for a bad input,
    are passed on as they are: we wrote those messages, so they're safe.
    """
    action = payload["action"]
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({**payload, "run_id": run_id}),
        )
    except ClientError as error:
        # AWS refused or failed the call itself (e.g. AccessDenied, expired
        # login). The message names the role and account, so keep it local.
        print(f"[run {run_id}] [{action}] Lambda call failed: {error}", file=sys.stderr)
        return {"error": HELPDESK_FAILED}
    result = json.loads(response["Payload"].read())
    # FunctionError is set when the Lambda code itself crashed; the payload
    # is then AWS's crash report, not a helpdesk answer.
    if "FunctionError" in response:
        print(f"[run {run_id}] [{action}] Lambda error: {result}", file=sys.stderr)
        return {"error": HELPDESK_FAILED}
    return result


def wrap_ticket_text(ticket_id: str, subject: str, body: str) -> str:
    """[SEC] Put a ticket's subject and body between markers.

    Both are whatever the requester typed, so they may hold orders aimed at
    the agent (ticket 1042 does). The system prompt says text between the
    markers is data, never an instruction. Any "<<" or ">>" in the text is
    made single, so a ticket can't fake an <<END>> marker and "escape" —
    the same trick as Step 2's wrap_passage.
    """
    text = f"Subject: {subject}\n\n{body}"
    text = text.replace("<<", "<").replace(">>", ">")
    return f'<<TICKET_TEXT ticket_id="{ticket_id}">>\n{text}\n<<END>>'


def make_helpdesk_tools(
    lambda_client, read_function: str, write_function: str, run_id: str
) -> list:
    """Build the six tools, wired to the two Lambdas.

    Built here, not at module level, because they need a Lambda client
    (which needs the AWS sign-in) and the function names from .env.
    `run_id` is the correlation ID for one question: every tool sends it,
    so the Lambdas' CloudWatch lines and audit rows can be matched to it.
    """

    def read(payload: dict) -> dict:
        return call_lambda(lambda_client, read_function, payload, run_id)

    def write(payload: dict) -> dict:
        return call_lambda(lambda_client, write_function, payload, run_id)

    @tool
    def get_account_status(username: str) -> dict:
        """Look up a user's account: name, department and status.

        Args:
            username: The user's login name, lower-case letters only, e.g. "alee".

        Returns:
            found=True with the name, department and status ("active" or
            "locked"), or found=False if there is no such account.
        """
        return read({"action": "get_account_status", "username": username})

    @tool
    def list_folder_access(folder: str) -> dict:
        """List who can open a shared folder, and whether it's protected.

        Args:
            folder: The folder name, lower-case letters and hyphens, e.g. "marketing".

        Returns:
            found=True with the members and protected flag, or found=False if
            there is no such folder.
        """
        return read({"action": "list_folder_access", "folder": folder})

    @tool
    def get_ticket(ticket_id: str) -> dict:
        """Read a helpdesk ticket.

        Args:
            ticket_id: The ticket number, digits only, e.g. "1042".

        Returns:
            found=True with the requester, status and the ticket's text
            (between <<TICKET_TEXT>> and <<END>> markers), or found=False if
            there is no such ticket.
        """
        result = read({"action": "get_ticket", "ticket_id": ticket_id})
        if result.get("found"):
            result["text"] = wrap_ticket_text(
                result["ticket_id"], result.pop("subject"), result.pop("body")
            )
        return result

    @tool
    def open_ticket(requester: str, subject: str, body: str) -> dict:
        """Open a new helpdesk ticket.

        Args:
            requester: The username of the person asking, e.g. "alee".
            subject: A one-line summary, up to 120 characters.
            body: The details, up to 2,000 characters.

        Returns:
            outcome "done" and a message with the new ticket number.
        """
        return write(
            {"action": "open_ticket", "requester": requester, "subject": subject, "body": body}
        )

    @tool
    def reset_account(username: str) -> dict:
        """Unlock a locked account, making it active again. Needs approval.

        Args:
            username: The user's login name, e.g. "alee".

        Returns:
            outcome "done", "no change" (already active) or "refused", and a message.
        """
        return write({"action": "reset_account", "username": username})

    @tool
    def grant_folder_access(username: str, folder: str) -> dict:
        """Give a user access to a shared folder. Needs approval.

        Args:
            username: The user's login name, e.g. "priya".
            folder: The folder name, e.g. "marketing".

        Returns:
            outcome "done", "no change" (already a member) or "refused"
            (e.g. a protected folder), and a message.
        """
        return write(
            {"action": "grant_folder_access", "username": username, "folder": folder}
        )

    return [
        get_account_status,
        list_folder_access,
        get_ticket,
        open_ticket,
        reset_account,
        grant_folder_access,
    ]
