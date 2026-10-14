"""Unit tests for the policy lookup tool.

Covers the four cases the plan calls for:
  - known category + city override
  - a different city override
  - unknown city falls back to the category default
  - unknown category returns a clear "no rule" result
Plus a check that matching ignores case and surrounding spaces.
"""

from policy import lookup_expense_limit


def test_city_override():
    """A city with its own rule uses the override, not the default."""
    result = lookup_expense_limit("meals", "Chicago")
    assert result["found"] is True
    assert result["limit"] == 75
    assert result["currency"] == "USD"


def test_second_override():
    """Hotels in New York use the New York override."""
    result = lookup_expense_limit("hotel", "New York")
    assert result["found"] is True
    assert result["limit"] == 350


def test_unknown_city_uses_default():
    """A city with no specific rule falls back to the category default."""
    result = lookup_expense_limit("taxi", "Denver")
    assert result["found"] is True
    assert result["limit"] == 40  # taxi default


def test_unknown_category_has_no_rule():
    """An unknown category returns found=False and no limit, not an error."""
    result = lookup_expense_limit("yacht", "Monaco")
    assert result["found"] is False
    assert result["limit"] is None
    assert "yacht" in result["rule"].lower()


def test_matching_ignores_case_and_spaces():
    """'  Meals ' matches 'meals'; '  chicago' matches 'chicago'."""
    result = lookup_expense_limit("  Meals ", "  chicago")
    assert result["found"] is True
    assert result["limit"] == 75
