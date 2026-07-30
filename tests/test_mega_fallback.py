"""Tests for battle-form resolution in NameResolver.

The doubles feed does not split Mega rows, but Smogon singles does. Canonical
Mega forms must therefore resolve to their dedicated Pocket Gallery asset IDs.
Unknown compound forms still degrade safely through the suffix fallback.
"""

import pytest

from src.name_resolver import NameResolver, resolve_pokemon_id


@pytest.fixture
def resolver():
    return NameResolver()


@pytest.mark.parametrize(
    "pikalytics_name,expected_dex_id",
    [
        # Canonical Mega names → dedicated app form IDs
        ("Charizard-Mega-X", 10034),
        ("Charizard-Mega-Y", 10035),
        ("Venusaur-Mega", 10033),
        ("Blastoise-Mega", 10036),
        ("Gyarados-Mega", 10041),
        ("Mewtwo-Mega-X", 10043),
        ("Mewtwo-Mega-Y", 10044),
        ("Gengar-Mega", 10038),
        ("Lucario-Mega", 10059),
        ("Garchomp-Mega", 10058),
        ("Tyranitar-Mega", 10049),
        ("Scizor-Mega", 10046),
        ("Gardevoir-Mega", 10051),
        ("Aggron-Mega", 10053),
        ("Rayquaza-Mega", 10079),
        # Mega on a form that itself has an alias must still resolve.
        ("Floette-Eternal-Mega", 10061),
    ],
)
def test_mega_resolves_to_asset_id(resolver, pikalytics_name, expected_dex_id):
    assert resolver.get_pokemon_id(pikalytics_name) == expected_dex_id


def test_module_level_helper(resolver):
    # Sanity check that the convenience function follows the same path.
    assert resolve_pokemon_id("Charizard-Mega-Y") == 10035


def test_unknown_pokemon_still_returns_zero(resolver):
    assert resolver.get_pokemon_id("Definitely-Not-A-Pokemon") == 0


def test_base_form_unaffected(resolver):
    # Existing direct lookups must not regress.
    assert resolver.get_pokemon_id("Charizard") == 6
    assert resolver.get_pokemon_id("Incineroar") == 727
