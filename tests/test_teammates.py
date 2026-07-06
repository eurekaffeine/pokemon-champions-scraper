"""Regression tests for teammate usage derivation.

Background
---------
The Pikalytics Champions feed ranks teammates by co-occurrence but does NOT
publish the underlying percentage:
  * list-API ``team`` rows carry an ordinal ``rank`` but no ``percent`` key;
  * the AI-markdown feed reports every teammate as ``undefined%``.

The original parsers called ``_pct(row.get("percent"))`` / defaulted
``undefined`` to 0.0, so every teammate collapsed to ``usage=0.0`` -- which
also destroyed the teammate ordering downstream (the merge sorts by usage).

These tests lock in the fix: teammates get a strictly-decreasing, non-zero
usage proxy derived from their ordinal position, preserving source order.
"""

import pytest

from src.scrapers.pikalytics import PikalyticsScraper, _rank_to_usage
from src.models.schema import TeammateUsage


# ------------------------------------------------------------ helper contract

@pytest.mark.parametrize(
    "pos,total,expected",
    [
        (1, 6, 1.0),
        (6, 6, round(1 / 6, 5)),
        (1, 1, 1.0),
        (1, 0, 0.0),   # empty / unknown total -> 0, never a ZeroDivisionError
        (0, 6, 0.0),   # guard invalid position
    ],
)
def test_rank_to_usage_values(pos, total, expected):
    assert _rank_to_usage(pos, total) == expected


def test_rank_to_usage_is_strictly_decreasing_and_in_range():
    n = 10
    vals = [_rank_to_usage(i, n) for i in range(1, n + 1)]
    assert all(0.0 < v <= 1.0 for v in vals)
    assert vals == sorted(vals, reverse=True)
    assert len(set(vals)) == n  # every rank is distinct
    assert vals[0] == 1.0


# ------------------------------------------------------- list-API teammates

def _scraper():
    return PikalyticsScraper()


def test_listapi_teammates_are_nonzero_and_ordered():
    # Rows carry explicit ids (as the live feed does for many teammates) and
    # crucially NO 'percent' key -- the exact shape that produced all-zeros.
    team = [
        {"pokemon": "Whimsicott", "id": 547, "rank": 1},
        {"pokemon": "Charizard", "id": 6, "rank": 2},
        {"pokemon": "Basculegion", "id": 902, "rank": 3},
    ]
    out = _scraper()._parse_listapi_teammates(team)
    assert [t.id for t in out] == [547, 6, 902]
    usages = [t.usage for t in out]
    assert all(u > 0.0 for u in usages), "no teammate should be 0.0"
    assert usages == sorted(usages, reverse=True)
    assert usages[0] == 1.0


def test_listapi_teammates_ignores_missing_percent_field():
    # Regression: the presence/absence of 'percent' must not zero the usage.
    team = [{"pokemon": "Whimsicott", "id": 547}]
    out = _scraper()._parse_listapi_teammates(team)
    assert len(out) == 1
    assert out[0].usage == 1.0


def test_listapi_teammates_dedup_preserves_first_position():
    team = [
        {"pokemon": "Whimsicott", "id": 547},
        {"pokemon": "Charizard", "id": 6},
        {"pokemon": "Whimsicott", "id": 547},  # dup
    ]
    out = _scraper()._parse_listapi_teammates(team)
    assert [t.id for t in out] == [547, 6]
    assert out[0].usage > out[1].usage


def test_listapi_teammates_empty():
    assert _scraper()._parse_listapi_teammates([]) == []


# ------------------------------------------------------- markdown teammates

MARKDOWN_UNDEFINED = """## Common Teammates
- **Whimsicott**: undefined%
- **Charizard**: undefined%
- **Basculegion**: undefined%

## Common Moves
- **Dragon Claw**: 89.4%
"""


def test_markdown_teammates_undefined_become_nonzero_ordered():
    out = _scraper()._parse_markdown_teammates(MARKDOWN_UNDEFINED)
    assert len(out) == 3
    usages = [t.usage for t in out]
    assert all(u > 0.0 for u in usages), "undefined% must not yield 0.0"
    assert usages == sorted(usages, reverse=True)
    assert usages[0] == 1.0


def test_markdown_teammates_prefers_real_percent_when_present():
    # If Pikalytics ever restores real teammate percentages, use them verbatim
    # rather than the rank proxy.
    md = """## Common Teammates
- **Whimsicott**: 42.0%
- **Charizard**: 30.0%
"""
    out = _scraper()._parse_markdown_teammates(md)
    assert [round(t.usage, 3) for t in out] == [0.42, 0.30]


def test_markdown_teammates_absent_section():
    assert _scraper()._parse_markdown_teammates("## Common Moves\n- **Tackle**: 10%") == []


# ------------------------------------------------------------- schema bound

def test_teammate_usage_within_schema_bounds():
    # usage field is constrained to [0, 1]; the proxy must never exceed it.
    for n in (1, 3, 6, 50):
        for i in range(1, n + 1):
            TeammateUsage(id=1, usage=_rank_to_usage(i, n))  # would raise if OOB
