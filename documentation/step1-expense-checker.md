# Step 1 — Expense policy checker

**One agent, one tool: ask whether an expense is within policy and get a yes/no with the limit behind it.**

You type something like *"I spent $85 on a client dinner in Chicago — is that OK?"* The agent works out the category (meals) and city (Chicago), calls a lookup tool that holds the policy table, and answers from what the tool returns. Built and tested 1–7 October 2026.

## What was built

The split that runs through the whole lab: **fixed rules hold the facts, the model only recommends.**

- *Fixed rules (plain code, unit-tested):* the policy table and the lookup — category + city → limit.
- *AI judgment:* reading the question, picking the category and city, deciding to call the tool, writing the answer.

| Part | What it is |
|---|---|
| `policy.py` | The policy table (meals, hotel, taxi; some cities get higher caps) and `lookup_expense_limit(category, city)`. No AI, no AWS. |
| `lambda_function.py` | The Lambda handler. Checks the request has `category` and `city`, logs the run ID, calls `policy.py`. |
| Lambda `expense-policy-lookup` | The lookup running as its own AWS service (us-east-1, Python 3.14, arm64). Its role can only write CloudWatch logs. |
| `agent.py` | A Strands Agent on Claude Haiku 4.5 (Bedrock). Asks 6 sample questions, prints each answer with its run ID, tool calls and token counts. |
| `iam/agent-policy.json` | The agent's own permissions: one model, one Lambda (see Security below). |
| Tests | 15 unit tests (offline) and 6 integration tests against the real model and Lambda. |

How it grew:
1. **1.0** — AWS set up: region, budget alert, IAM Identity Center sign-in, Bedrock model access, CLI smoke test.
2. **1.1** — Agent with the lookup as a local Python tool.
3. **1.2** — Lookup moved into Lambda; the agent given its own narrow identity.
4. **1.3** — Token counts and cost measured, then checked against the bill.
5. **1.4** — Security hardening (see Security below).

## How to run it

All commands from `step1-expense-checker/`. Anything that calls AWS runs on the personal laptop only.

```
.venv\Scripts\python -m pip install -r requirements-lock.txt   # once: the 54 pinned packages
aws sso login --profile lab                                    # when the sign-in has expired
.venv\Scripts\python agent.py                                  # the 6 sample questions
.venv\Scripts\python -m pytest -q                              # 15 unit tests, no network
.venv\Scripts\python -m pytest -m integration -s               # 6 real-model tests, ~1.5 cents
```

`.env` (not in git) needs `AWS_REGION`, `AWS_PROFILE=lab-agent`, `MODEL_ID` and `LAMBDA_NAME`. To update the Lambda, zip `lambda_function.py` and `policy.py` (at the top level of the zip) and upload it in the console.

## Results

- **Answers:** 6/6 correct on every run since the 1.1 prompt fix; the tool is called for all 5 expense questions and not for the off-topic one.
- **Access:** the agent's identity was refused (AccessDenied) for a different model, for Haiku called directly rather than through the inference profile, for listing Lambdas, and for S3.
- **Speed:** Lambda cold start billed 130 ms, warm calls 2 ms.

## Costs

**About $0.0025 per question; about $0.013 per 6-question run.** Almost all of it is the model. Lambda stays inside its free allowance.

- Our token counts matched Bedrock's own CloudWatch figures exactly (10,167 in / 664 out over 11 model calls).
- The bill: Cost Explorer showed $0.00 because Free Tier credits cancel the charges; the Credits page showed an estimated $0.11 used over 5–6 October, in line with the estimate.

Full figures, monthly costs at company scale and how to read the bill: `costs.md`.

## Lessons

- **How tool calling works.** The model doesn't run the tool. It asks for a call, the agent library runs it, and the result goes back to the model to write the answer — so one question is two model calls.
- **The model will guess unless told not to.** On the first run it answered the yacht question without the tool, and added "per night" to a hotel limit. The fix was in the system prompt: always call the tool, even for odd categories; report only what it returns.
- **The model adds advice the policy doesn't give.** Even after the fix, answers sometimes end with *"you'll need to cover the difference yourself"* or *"check whether the overage can be approved."* The policy table says nothing about either — the model makes them up because they sound helpful. Harmless here, but it is the model inventing policy. A stricter prompt or a check on the output (Steps 4–5) would catch it.
- **Least privilege takes some care.** Bedrock's US inference profile sends calls to three regions, so the policy has to allow the model in all three — but only through the profile, using a condition on the profile's ARN.
- **AWS quirks:** Strands 1.57.2 refuses both `region_name` and `boto_session` (put the region in the session); PowerShell 5.1 strips inner quotes from JSON passed to `aws`; Cost Explorer's end date is exclusive.
- **Cost is mostly the set-up text.** The system prompt and tool description are resent on every model call, so they dominate input tokens.

## Security [SEC]

Step 1 works four of the security course's seven layers (the README lists all seven).

### Layer 1 — Infrastructure (identity and least privilege)

- **No long-lived keys.** Sign-in is IAM Identity Center (SSO), with sessions that expire.
- **The agent has its own identity.** Permission set `ExpenseAgentRuntime` (profile `lab-agent`), separate from the admin profile used for set-up. It allows only:
  - calling Claude Haiku 4.5, and only through the US inference profile;
  - invoking the one Lambda, `expense-policy-lookup`.
- **The Lambda's own role** can only write logs.
- **Proved by refusal:** another model, direct Haiku, listing Lambdas and S3 were all denied.
- **Secrets stay out of git.** gitleaks runs on every commit; `.env` is git-ignored; IAM files in git use `<ACCOUNT_ID>`, filled in only when pasted into AWS.

### Layer 5 — Inference (the model's output is not authority)

- **Rules vs AI.** The limits live in `policy.py`, behind the Lambda. The model never holds the numbers; it only reads what the tool returns and recommends.
- **The system prompt backs this up:** "Only the tool decides whether a rule exists. Never guess or use outside knowledge for a number."
- **Gap:** the invented advice in Lessons above shows the model still adds its own words around the facts. Bedrock Guardrails arrive in Step 3.

### Layer 6 — Output handling

- **Errors are kept from the model.** If the Lambda crashes or AWS refuses the call, the model gets only a generic message (`LOOKUP_FAILED` in `agent.py`); the real detail is printed locally with the run ID. A unit test checks the raw crash text never reaches the model. This matters because anything in the model's context can shape its answer or leak to the user.
- **Answers stick to the tool.** The prompt says to report only what the tool returns — partly met, given the invented advice.

### Layer 7 — Monitoring

- **Correlation ID.** Each question gets a run ID, printed by `agent.py` and sent to the Lambda, which logs it. Run `08e72018` was found in the Lambda's CloudWatch log, so one question can be traced from agent to Lambda.
- **Cost per run.** Token counts print per question and per run, and match Bedrock's CloudWatch figures.
- Full tracing and a red-team test come in Step 5.

### Also done: supply chain (layer 2)

Not one of Step 1's four layers, but started here: the 54 packages are pinned in `requirements-lock.txt`, and `pip-audit` (run by hand, as it needs the internet) found no known holes on its first run. Using Claude through Bedrock, rather than a downloaded model, avoids the risk of running someone else's model file.
