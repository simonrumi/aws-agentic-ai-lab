# AWS Agentic AI Lab

Hands-on practice with how enterprises set up agentic AI on AWS. Five small projects, each adding one enterprise "layer" around a working agent.

## The seven lessons

1. **Identity** — whose permissions the agent acts with.
2. **Tool access** — which systems the agent can touch, narrowed to the least it needs.
3. **Guardrails** — content filters and defences against prompt injection.
4. **Human approval** — a person says "yes" before risky actions.
5. **Logging and tracing** — a record of what the agent did and why.
6. **Evals** — repeatable tests that score answer quality over time.
7. **Cost and speed monitoring** — what each run costs and how long it takes.

## After cloning

```
pip install pre-commit
pre-commit install      # turns on the gitleaks secret scan for every commit
cp .env.example .env    # then fill in your own values
```

See `documentation/` for write-ups of each step.
