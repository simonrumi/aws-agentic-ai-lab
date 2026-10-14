"""The expense-policy agent.

This is the "AI" half of Step 1. A Strands agent runs Claude Haiku on Bedrock
and gets one tool: `lookup_expense_limit`. Since Step 1.2 the tool doesn't run
the lookup itself — it asks AWS Lambda to run it (lambda_function.py +
policy.py, uploaded as the `expense-policy-lookup` function). The model reads
the user's question, decides to call the tool, and turns the tool's answer
into a plain reply.

Run from this folder (needs a live `lab` SSO login — personal laptop only):

    .venv\\Scripts\\python agent.py
"""

import json
import sys
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from strands import Agent, tool
from strands.models import BedrockModel

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# What the model sees when the lookup fails. The real error stays out of the
# model's context (it can hold stack traces, role names, the account ID) and
# is printed locally instead.
LOOKUP_FAILED = (
    "The policy service is unavailable. Try again later or ask the finance team."
)

SYSTEM_PROMPT = """You are an expense-policy assistant for a company's staff.

Rules:
- Only answer questions about company expense limits. If asked anything else,
  say politely that you can only help with expense policy.
- For any question about whether something can be expensed, call the
  lookup_expense_limit tool first, even if the category seems unusual. Only
  the tool decides whether a rule exists. Never guess or use outside
  knowledge for a number.
- Report only what the tool returns. Don't add details such as "per night"
  or "per day".
- If the tool says no rule exists, tell the user that plainly and suggest they
  ask their manager or finance team.
- Keep answers short: the limit, the rule behind it, and whether the user's
  amount (if they gave one) is within it."""

SAMPLE_QUESTIONS = [
    "Can I spend $70 on dinner in Chicago?",
    "What's the hotel limit in New York?",
    "I took a $55 taxi in Denver. Is that OK?",
    "What's the limit for meals in Boston?",
    "Can I expense a yacht rental in Monaco?",
    "What's the capital of France?",
]


def read_env(path: Path) -> dict:
    """Read KEY=value lines from a .env file, skipping blanks and comments."""
    settings = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
    return settings


def new_run_id() -> str:
    """A short random correlation ID for one agent run (one question)."""
    return uuid.uuid4().hex[:8]


def make_lookup_tool(lambda_client, function_name: str, run_id: str):
    """Build the agent's tool, wired to one Lambda function.

    The tool is built here, not at module level, because it needs a Lambda
    client (which needs the AWS sign-in) and the function name from .env.

    `run_id` is the correlation ID. The tool sends it to the Lambda, which
    logs it in CloudWatch, and uses it in our own error lines, so one run's
    records can be found in both places. Our code sets it, not the model.
    """

    @tool
    def lookup_expense_limit(category: str, city: str) -> dict:
        """Look up the company spending limit for an expense category in a city.

        Args:
            category: The kind of expense, e.g. "meals", "hotel" or "taxi".
            city: The city where the expense happened, e.g. "Chicago".

        Returns:
            A dict with the limit (or None if no rule exists), the currency,
            a plain-English rule, and found=True/False.
        """
        try:
            response = lambda_client.invoke(
                FunctionName=function_name,
                Payload=json.dumps(
                    {"category": category, "city": city, "run_id": run_id}
                ),
            )
        except ClientError as error:
            # AWS refused or failed the call itself (e.g. AccessDenied, expired
            # login). The message names the role and account, so keep it local.
            print(
                f"[run {run_id}] [lookup_expense_limit] Lambda call failed: {error}",
                file=sys.stderr,
            )
            return {"error": LOOKUP_FAILED}
        result = json.loads(response["Payload"].read())
        # FunctionError is set when the Lambda code itself crashed; the
        # payload is then AWS's crash report, not a policy answer.
        if "FunctionError" in response:
            print(
                f"[run {run_id}] [lookup_expense_limit] Lambda error: {result}",
                file=sys.stderr,
            )
            return {"error": LOOKUP_FAILED}
        return result

    return lookup_expense_limit


def make_agent(settings: dict, run_id: str) -> Agent:
    """Build a fresh agent: Haiku on Bedrock, the Lambda-backed tool, our rules."""
    session = boto3.Session(
        profile_name=settings["AWS_PROFILE"],
        region_name=settings["AWS_REGION"],
    )
    model = BedrockModel(
        boto_session=session,
        model_id=settings["MODEL_ID"],
    )
    lookup_tool = make_lookup_tool(
        session.client("lambda"), settings["LAMBDA_NAME"], run_id
    )
    return Agent(
        model=model,
        tools=[lookup_tool],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,  # don't stream text to the screen; we print it below
    )


def ask(settings: dict, question: str) -> dict:
    """Ask one question with a fresh agent, print the answer and stats.

    Returns the token usage, so main() can add up the whole run. Input and
    output tokens are counted separately because Bedrock prices them
    differently (output costs more per token).
    """
    run_id = new_run_id()
    agent = make_agent(settings, run_id)
    result = agent(question)
    tool_calls = sum(m.call_count for m in result.metrics.tool_metrics.values())
    usage = result.metrics.accumulated_usage
    print(f"Q: {question}  [run {run_id}]")
    print(f"A: {str(result).strip()}")
    print(
        f"   [tool calls: {tool_calls}, tokens in: {usage['inputTokens']}, "
        f"out: {usage['outputTokens']}, total: {usage['totalTokens']}]\n"
    )
    return usage


def main() -> None:
    settings = read_env(ENV_FILE)
    usages = [ask(settings, question) for question in SAMPLE_QUESTIONS]
    total_in = sum(u["inputTokens"] for u in usages)
    total_out = sum(u["outputTokens"] for u in usages)
    print(
        f"Run total for {len(usages)} questions: tokens in: {total_in}, "
        f"out: {total_out}, total: {total_in + total_out}"
    )


if __name__ == "__main__":
    main()
