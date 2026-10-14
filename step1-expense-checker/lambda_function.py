"""The Lambda entry point for the expense-policy lookup.

In Step 1.2 the policy lookup moves off the laptop and into AWS Lambda. AWS
calls `lambda_handler` with the input as a dict (`event`); we pass it on to
policy.py and return its answer. The policy rules themselves don't change.

Upload this file and policy.py together in one zip. In the Lambda console,
the handler setting is `lambda_function.lambda_handler` (file.function).
"""

import policy


def lambda_handler(event: dict, context) -> dict:
    """Look up an expense limit for the {category, city} in `event`.

    `context` is AWS's info about this run (request id, time left, ...).
    We don't need it, but Lambda always passes it.

    Returns the same dict as policy.lookup_expense_limit. If `category` or
    `city` is missing, returns {"error": ...} instead of raising, so the
    caller gets a clear message rather than an AWS crash report.

    `run_id` (optional) is the agent's correlation ID. We print it with the
    request; Lambda sends anything printed to CloudWatch Logs, so searching
    there for the ID finds this call. It doesn't affect the answer.
    """
    print(
        f"run_id={event.get('run_id', 'none')} "
        f"category={event.get('category')} city={event.get('city')}"
    )
    missing = [key for key in ("category", "city") if not event.get(key)]
    if missing:
        return {"error": f"Missing required field(s): {', '.join(missing)}."}
    return policy.lookup_expense_limit(event["category"], event["city"])
