# Working agreement for Claude in this repo

## Explain, then wait for my OK — before building anything

Before you create or edit files, install packages, create a virtual
environment, or run any command that changes state (code, config,
infrastructure, git add/commit/push), do two things:

1. **Explain**, in plain English, what you are about to do and why.
2. **Stop and wait** for my explicit "yes" / "go ahead".

This holds **even in auto-accept or bypass-permissions mode.** Auto mode
removes the tool permission prompts; it does **not** remove this rule. Treat
every build-or-change step as needing my sign-off, one step at a time. When in
doubt, ask.

What does **not** need sign-off: reading files, searching the codebase,
explaining how things work, and proposing a plan. Do those freely.

The reason: This is for training. Walk me through it step by
step — don't race ahead and hand me finished work.

## Code style: functional and written out in full

**Prefer functional code to object-oriented code** wherever you can: plain
functions, and functions that build functions (closures, like
`make_approval_check` in `step3-it-helpdesk/approval.py`), rather than
classes. Use a class only when a library requires one, and say why.

**Write code out the long way, not the compact way.** I should be able to read
it without knowing Python's shortcuts. For example:

- A plain loop, not a list comprehension. Not this:

  ```python
  missing = [key for key in ("GUARDRAIL_ID", "GUARDRAIL_VERSION") if not settings.get(key)]
  ```

  but this:

  ```python
  missing = []
  for key in ("GUARDRAIL_ID", "GUARDRAIL_VERSION"):
      if not settings.get(key):
          missing.append(key)
  ```

- Inputs spelled out by name, not unpacked from a dictionary with `**`. Not
  this:

  ```python
  model = BedrockModel(boto_session=session, model_id=settings["MODEL_ID"], **guardrail_settings(settings))
  ```

  but this:

  ```python
  model = BedrockModel(
      boto_session=session,
      model_id=settings["MODEL_ID"],
      guardrail_id=settings["GUARDRAIL_ID"],
      guardrail_version=settings["GUARDRAIL_VERSION"],
      guardrail_trace="enabled",
  )
  ```

The same goes for other shortcuts (`{**a, **b}`, `lambda`, chained one-liners).
If a shortcut really is clearer, explain it the first time you use it.
