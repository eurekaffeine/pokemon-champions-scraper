"""Tests for Mega/Gmax form fallback in NameResolver.

Historically Pikalytics' `championstournaments` feed returned Mega forms
(around 2026-05-16), which broke the ID audit (Mega forms were unresolved
→ dex_id=0 → audit exit 1 → GH Pages deploy skipped).

The scraper now reads the `battledataregmbs3` ranked-ladder feed, which does
NOT emit Mega rows — so this fallback is defense-in-depth rather than load-
bearing for the active feed. We keep these tests because the resolver still
guarantees Mega/Gmax names degrade to their base form's National Pokédex
number if such a name ever appears again.
"""

import pytest

from src.name_resolver import NameResolver, resolve_pokemon_id


@pytest.fixture
def resolver():
    return NameResolver()


@pytest.mark.parametrize(
    "pikalytics_name,expected_dex_id",
    [
        # Plain Mega → base
        ("Charizard-Mega-X", 6),
        ("Charizard-Mega-Y", 6),
        ("Venusaur-Mega", 3),
        ("Blastoise-Mega", 9),
        ("Gyarados-Mega", 130),
        ("Mewtwo-Mega-X", 150),
        ("Mewtwo-Mega-Y", 150),
        ("Gengar-Mega", 94),
        ("Lucario-Mega", 448),
        ("Garchomp-Mega", 445),
        ("Tyranitar-Mega", 248),
        ("Scizor-Mega", 212),
        ("Gardevoir-Mega", 282),
        ("Aggron-Mega", 306),
        ("Rayquaza-Mega", 384),
        # Mega on a form that itself has an alias must still resolve.
        ("Floette-Eternal-Mega", 10061),
    ],
)
def test_mega_falls_back_to_base_dex_id(resolver, pikalytics_name, expected_dex_id):
    assert resolver.get_pokemon_id(pikalytics_name) == expected_dex_id


def test_module_level_helper(resolver):
    # Sanity check that the convenience function follows the same path.
    assert resolve_pokemon_id("Charizard-Mega-Y") == 6


def test_unknown_pokemon_still_returns_zero(resolver):
    assert resolver.get_pokemon_id("Definitely-Not-A-Pokemon") == 0


def test_base_form_unaffected(resolver):
    # Existing direct lookups must not regress.
    assert resolver.get_pokemon_id("Charizard") == 6
    assert resolver.get_pokemon_id("Incineroar") == 727
