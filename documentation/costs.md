# What the agents cost

Running cost of the agents built in this lab, measured on real runs. Each step adds its own section; the summary at the top covers everything built so far.

## Executive summary

**One question to the expense-policy agent costs about a quarter of a cent ($0.0025), or $2.50 per 1,000 questions.**

Almost all of that is the AI model (Claude Haiku 4.5 on Amazon Bedrock), charged by the amount of text it reads and writes. The policy lookup service (AWS Lambda) is effectively free at these volumes. There are no fixed monthly charges yet: if nobody asks a question, the bill is zero.

**Monthly cost at three company sizes** (each person asks 4 questions a week; 52 weeks ÷ 12 = 4.33 weeks a month):

| Staff | Questions a month | Cost a month | Cost a year |
|---|---|---|---|
| 100 | ~1,700 | ~$4 | ~$51 |
| 500 | ~8,700 | ~$21 | ~$256 |
| 5,000 | ~87,000 | ~$213 | ~$2,560 |

All three fit inside Lambda's free allowance (1 million calls a month), so the figures are model cost only.

**What could push the cost up:**
- **Longer instructions or tool descriptions.** These are resent with every model call, so they are the biggest share of each question's cost.
- **More model calls per question.** Today a policy question needs two calls (one to ask for the lookup, one to write the answer). A question that needs several lookups costs more.
- **A larger model.** Moving from Haiku to a more capable Claude model would multiply the cost several times over.
- **Fixed costs in later steps.** Some search stores charge by the hour even when idle. Step 2's choice (S3 Vectors) doesn't — see below.

**Step 2 (answering from company documents) costs about $0.0047 per question — nearly double.** The system prompt is longer, there are two tool descriptions, and each answer reads the passages the search returns. The search itself costs almost nothing, and nothing charges while idle. At the same three company sizes: about **$8 / $41 / $407 a month**.

**Status:** Step 1 measured in the lab on 5 October 2026, with AWS's own token counts matching ours exactly. Checked against the AWS bill on 7 October 2026: Free Tier credits covered the estimated $0.11 used so far (see "Bill check" below).

## Step 1 — Expense policy checker

### How we measured

1. `step1-expense-checker/agent.py` prints the input and output tokens for each question and a total for the run. Tokens are the chunks of text the model reads (input) and writes (output); Bedrock charges per token.
2. We checked those numbers against Bedrock's own figures in CloudWatch (AWS's monitoring service: Metrics → `AWS/Bedrock`, by model ID, statistic Sum).
3. We checked the Lambda's per-call reports in CloudWatch Logs.

Run used: 6 sample questions, 13:53 Pacific on 5 October 2026, agent signed in as the narrow `lab-agent` role.

| Source | Model calls | Input tokens | Output tokens |
|---|---|---|---|
| `agent.py` | — | 10,167 | 664 |
| Bedrock (CloudWatch) | 11 | 10,167 | 664 |

### Prices used

Claude Haiku 4.5 on Amazon Bedrock, on-demand, US (us-east-1 via the US cross-region inference profile), from aws.amazon.com/bedrock/pricing, checked 5 October 2026:

- **Input:** $1.00 per million tokens
- **Output:** $5.00 per million tokens

These match Anthropic's own list price for Haiku 4.5. Prices change; check again before relying on them.

### Cost per question

| Question type | Input tokens | Output tokens | Cost |
|---|---|---|---|
| Expense question (average of 5) | 1,862 → $0.00186 | 120 → $0.00060 | **$0.0025** |
| Off-topic question (refused) | 859 → $0.00086 | 66 → $0.00033 | $0.0012 |
| Whole run (6 questions) | 10,167 → $0.0102 | 664 → $0.0033 | $0.0135 |

**Why input dominates (94% of tokens, about 75% of cost):** each expense question makes two model calls — the first returns "please run the lookup tool", the second writes the answer. Each call resends the instructions (system prompt) and the tool description, about 850 tokens of set-up. The off-topic question needs only one call, which is why it costs about half as much. Output tokens cost five times more each, but the answers are short.

The monthly table in the summary assumes every question is an expense question ($0.00246 each), so it slightly overstates the cost when some questions are off-topic.

### Lambda (the policy lookup service)

Each tool call runs the `expense-policy-lookup` function once. Two of its log reports from the same run:

| Call | Ran for | Start-up | Billed | Memory given / used |
|---|---|---|---|---|
| First of the run ("cold start") | 2.25 ms | 127.25 ms | 130 ms | 128 MB / 38 MB |
| Next calls ("warm") | 1.56 ms | — | 2 ms | 128 MB / 38 MB |

Lambda charges for billed time × memory, plus a small fee per call. A cold start happens only when the function has been idle for a while; warm calls bill a couple of milliseconds. Either way the cost is a tiny fraction of a cent, and the free allowance (1 million calls a month) covers all three company sizes above.

### Not included

- CloudWatch log storage (a few kilobytes per day at these volumes).
- IAM Identity Center sign-in (no charge).
- People's time to build and run the service.

### Ways to cut cost, if it ever matters

- Shorten the system prompt and the tool description — they are sent twice per question.
- Prompt caching: Bedrock can charge less for set-up text it has seen recently, but only once that text passes a minimum length; ours is probably too short today.
- Keep the cheapest model that answers correctly. Haiku is already the cheapest current Claude model.

### Bill check (Cost Explorer)

Checked 7 October 2026. Cost Explorer showed $0.00 for Claude Haiku 4.5 (Bedrock Edition) and Lambda on 5 October 2026, because Free Tier credits offset the charges by default. The Credits page showed an estimated $0.11 used across 5–6 October, in line with the token-based estimate (~$0.013 per 6-question run, plus integration tests). Lambda and CloudWatch stayed at $0 (free allowance).

Lesson: to see real usage cost, exclude "Credit" under Charge type in Cost Explorer. Also, the Cost Explorer end date is exclusive — a 5–6 October range shows 5 October only.

Open question: the Credits page lists both credits ($100 Free Tier, $20 budget) as "Expired" with an expiry of 10/01/2026, yet shows $0.11 used against them. Check the credit details before Step 2 creates anything that costs more.

## Step 2 — Policy Q&A

### Vector store choice (Step 2.0)

Checked 7 October 2026, us-east-1. The vector store is the search index behind the Knowledge Base; some types charge by the hour even when idle, so prices were checked before creating anything.

| | Managed Knowledge Base | Knowledge Base on S3 Vectors |
|---|---|---|
| Storage | $5.00 per GB of raw data a month | $0.06 per GB a month |
| Searches | $1.00 per 1,000 Retrieve calls | $2.50 per million queries, plus small per-TB processed and per-GB returned fees |
| Loading data | Included | $0.20 per GB put |
| Embeddings | Included | Paid to the embedding model (below) |
| Idle charge | None | None |

OpenSearch Serverless was ruled out: it has historically had a compute floor of hundreds of dollars a month (it now offers scale-to-zero, but the two options above are simpler).

**Embedding model:** Amazon Titan Text Embeddings V2, $0.02 per million tokens. Embedding happens once per document at sync time and once per search.

**For this lab** (4–5 documents, ~20 KB; ~100 searches while testing): storage is a fraction of a cent a month either way. Searches would cost about $0.10 on Managed and close to $0 on S3 Vectors.

**Choice: S3 Vectors.** Both meet the rule of no meaningful idle charge. Managed is simpler to set up, but it hides the embedding model, vector index and chunking; S3 Vectors exposes each of them, so it teaches more about how retrieval works.

Sources: [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/), [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/), [Managed vs customer-managed Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-build-managed.html).

### Cost per question (Step 2.7)

Measured from `step2-policy-qa/agent.py`'s own token counts, run of 9 October 2026 (11 questions, agent signed in as `lab-agent`). Same Haiku 4.5 prices as Step 1 ($1 / $5 per million tokens).

| Question type | Input tokens | Output tokens | Cost |
|---|---|---|---|
| Policy question (average of the 8 planted facts) | 4,038 → $0.00404 | 138 → $0.00069 | **$0.0047** |
| Both tools (New York flight + hotel) | 4,107 → $0.00411 | 189 → $0.00095 | $0.0051 |
| Not covered (dog) | 4,273 → $0.00427 | 103 → $0.00052 | $0.0048 |
| Off-topic (refused, no search) | 1,458 → $0.00146 | 58 → $0.00029 | $0.0018 |
| Whole run (11 questions) | 42,145 → $0.0421 | 1,457 → $0.0073 | $0.0494 |

Integration test runs (12 questions) cost about the same, ~$0.05–0.06.

**Why it's nearly double Step 1** (about 4,000 input tokens a question against 1,860):
- **Longer set-up, sent twice.** The off-topic question shows the set-up alone: 1,458 tokens against Step 1's 859, because the system prompt has more rules and there are two tool descriptions. A policy question makes two model calls (ask for the search, then answer), so that's about 1,200 extra tokens.
- **The passages, about 1,000 tokens.** The search returns 4 passages, which go into the second call. Whole documents that come back unsplit (the HR and travel policies) make this larger.

Output is about the same as Step 1; answers are still short.

### Search, embeddings and storage

| Part | Price | Per question | Idle |
|---|---|---|---|
| S3 Vectors query | $2.50 per million queries (+ tiny data fees) | ~$0.0000025 | — |
| Titan V2 embedding the question | $0.02 per million tokens | ~$0.0000004 (~20 tokens) | — |
| S3 Vectors storage | $0.06 per GB a month | — | A tiny fraction of a cent |
| S3 document storage | Standard S3 rates | — | A tiny fraction of a cent (~20 KB) |
| Sync (re-embedding all documents) | Titan rate on ~5,000 tokens | — | ~$0.0001 per sync |

So the model is still almost the whole cost. **No part charges while idle**, which confirms the Step 2.0 choice. Teardown steps: `step2-policy-qa.md`, "Idle and teardown".

### Monthly cost at company scale

Same assumptions as Step 1 (4 questions a person a week), at $0.0047 a question:

| Staff | Questions a month | Cost a month | Cost a year |
|---|---|---|---|
| 100 | ~1,700 | ~$8 | ~$98 |
| 500 | ~8,700 | ~$41 | ~$489 |
| 5,000 | ~87,000 | ~$407 | ~$4,890 |

Searches and embeddings add about $0.25 a month even at 5,000 staff.

### Ways to cut cost

- **Fewer or smaller passages:** return 3 instead of 4, or fix the whole-document chunks (see the "open puzzle" in `step2-policy-qa.md`).
- **Prompt caching:** the set-up is now ~1,450 tokens and sent twice per question, so caching is worth checking again — if it passes the model's minimum length, repeat set-up text is charged much less.
- **One call for simple questions:** Bedrock's RetrieveAndGenerate does search and answer in one step, but hides the passages from our [SEC] checks; we chose Retrieve for that reason.

Not yet checked against the bill — Step 2 costs so far are a few tenths of a dollar, covered by the same credits as Step 1 (see "Bill check" above, including the open question on whether the credits have expired).

## Step 3 — IT helpdesk

### Price check (Step 3.0)

Checked 12 October 2026, us-east-1. Step 3 adds three services: Bedrock Guardrails (filters on what goes into and out of the model), a DynamoDB table (the fake helpdesk data) and two more Lambdas (the helpdesk tools).

| Service | Price | Idle charge |
|---|---|---|
| Guardrails — content filters (the prompt-attack filter is one of these) | $0.15 per 1,000 text units | None |
| Guardrails — denied topics | $0.15 per 1,000 text units | None |
| Guardrails — word filters, regex sensitive-info filters | Free | None |
| DynamoDB on-demand — writes | $0.625 per million write units | None |
| DynamoDB on-demand — reads | $0.125 per million read units | None |
| DynamoDB storage (Standard) | $0.25 per GB a month; first 25 GB free | Storage only (free at our size) |
| Lambda — requests | $0.20 per million | None |
| Lambda — run time (Arm) | $0.0000133334 per GB-second | None |

- **Text unit:** up to 1,000 characters; longer text is split, so 5,600 characters bill as 6 units.
- **DynamoDB request units** for a small item (under 1 KB): a write uses 1; a read uses 0.5 (or 1 if "strongly consistent").
- **Lambda free allowance:** 1 million requests and 400,000 GB-seconds a month — covers the lab.

**Rough guess per question:** a guardrail with content filters and denied topics costs $0.30 per 1,000 text units. At about 15 text units a question (several model calls, each checking the prompt and the answer), that adds about $0.0045 — roughly doubling the model cost of a question, still under a cent. DynamoDB and Lambda add a tiny fraction of a cent. To be measured in 3.6.

**Keeping idle cost at zero:** don't turn on DynamoDB point-in-time recovery (a backup feature, charged by stored data) or Lambda provisioned concurrency (keeps copies running, charged by the hour).

**Not confirmed:** the pricing page doesn't say whether `ApplyGuardrail` (the guardrail called on its own) is billed at the same rates; assumed so. The Arm Lambda rate is from third-party guides (the AWS table didn't load); the free allowance makes it moot here.

Sources: [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/), [DynamoDB on-demand pricing](https://aws.amazon.com/dynamodb/pricing/on-demand/), [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/), [Lambda pricing guide (Arm rate)](https://cloudchipr.com/blog/aws-lambda-pricing).
