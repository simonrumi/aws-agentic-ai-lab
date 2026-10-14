"""[SEC] The approval pause before risky tools.

A Strands hook runs before every tool call, whatever the model asked for.
For any tool not on the NO_APPROVAL_NEEDED list it pauses the agent (an
"interrupt") and waits for a person's answer: "y" lets the call go ahead,
anything else cancels it, and the model is told it wasn't approved.

The pause is in code, not the prompt, so no wording in a ticket or a
question can talk the agent past it. The write Lambda's own refusal of
domain-admins still stands behind it, even if someone types "y".

How the pause works in Strands (1.57.2):
1. The hook calls `event.interrupt(...)`. The first time, that raises an
   exception that stops the agent; `agent(...)` returns with
   stop_reason "interrupt" and the interrupt (with our `reason`) in
   `result.interrupts`.
2. Our terminal loop (agent.py) shows the reason, asks y/N, and calls the
   agent again with the answer.
3. Strands runs the hook again; this time `event.interrupt(...)` returns
   the answer, and the hook lets the tool run or cancels it.
"""

from typing import Any

from strands.hooks import BeforeToolCallEvent

# [SEC] Tools that run without asking. Everything else needs approval, so a
# tool added later is paused by default until someone puts it here on
# purpose. open_ticket writes, but only adds a new ticket.
NO_APPROVAL_NEEDED = {
    "get_account_status",
    "list_folder_access",
    "get_ticket",
    "open_ticket",
}

# The interrupt's name; agent.py uses it to pick out our pauses.
INTERRUPT_NAME = "helpdesk-approval"

# What the model sees in place of the tool's answer when the call is denied.
DENIED_MESSAGE = (
    "Not approved: the person at the helpdesk did not approve this action, so "
    "it was not carried out. Tell the user it was not done."
)


def is_approved(answer: Any) -> bool:
    """Only a plain "y" (any case, spaces ignored) counts as yes."""
    return isinstance(answer, str) and answer.strip().lower() == "y"


def make_approval_check(run_id: str):
    """Build the hook for one question: pauses for y/N before risky tools.

    Pass the result to the agent as `Agent(hooks=[...])`. Strands reads the
    `event: BeforeToolCallEvent` type hint on `check` to know when to run it.

    `run_id` is the question's correlation ID: it's shown at the prompt and
    printed with the decision, so a decision can be matched to the Lambda's
    CloudWatch line and audit row.
    """

    def check(event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name in NO_APPROVAL_NEEDED:
            return
        answer = event.interrupt(
            INTERRUPT_NAME,
            reason={"tool": name, "inputs": event.tool_use["input"], "run_id": run_id},
        )
        # Only reached once the person has answered (step 3 above).
        if is_approved(answer):
            print(f"[run {run_id}] approved: {name} {event.tool_use['input']}")
        else:
            print(f"[run {run_id}] denied: {name} {event.tool_use['input']}")
            event.cancel_tool = DENIED_MESSAGE

    return check
