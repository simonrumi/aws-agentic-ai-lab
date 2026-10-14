"""The expense-policy lookup tool.

This is the "fixed rules" half of Step 1: a plain policy table and a pure
function that looks up a spending limit for a category + city. No AI, no AWS —
just data and a function, so it can be unit-tested on its own.

The AI half (agent.py) will call `lookup_expense_limit` as a tool when a user
asks whether an expense is allowed.
"""

CURRENCY = "USD"

# The policy table. Each category has a default limit and optional city
# overrides (some cities are more expensive, so they get a higher cap).
# City keys are lower-case; lookups are case-insensitive.
POLICY = {
    "meals": {
        "default": 50,
        "overrides": {"chicago": 75, "new york": 85, "san francisco": 85},
    },
    "hotel": {
        "default": 200,
        "overrides": {"new york": 350, "san francisco": 350},
    },
    "taxi": {
        "default": 40,
        "overrides": {},
    },
}


def lookup_expense_limit(category: str, city: str) -> dict:
    """Return the spending limit for a category in a city.

    Always returns a dict with the same shape, so callers never have to guess:

        {
          "category": <as given>,
          "city":     <as given>,
          "limit":    <int, or None if no rule>,
          "currency": "USD",
          "rule":     <plain-English explanation>,
          "found":    <True if a limit applies, False if the category is unknown>,
        }

    Matching is case- and whitespace-insensitive ("  Meals " == "meals").
    An unknown category returns found=False with limit=None, rather than
    raising, so the agent can tell the user plainly that no rule exists.
    """
    cat = category.strip().lower()
    town = city.strip().lower()

    if cat not in POLICY:
        return {
            "category": category,
            "city": city,
            "limit": None,
            "currency": CURRENCY,
            "rule": f"No expense policy exists for category '{category}'.",
            "found": False,
        }

    entry = POLICY[cat]
    if town in entry["overrides"]:
        limit = entry["overrides"][town]
        rule = f"{cat.title()} in {city.title()} is capped at {limit} {CURRENCY}."
    else:
        limit = entry["default"]
        rule = (
            f"{cat.title()} is capped at {limit} {CURRENCY} "
            f"(default rate; no specific rule for {city.title()})."
        )

    return {
        "category": category,
        "city": city,
        "limit": limit,
        "currency": CURRENCY,
        "rule": rule,
        "found": True,
    }
