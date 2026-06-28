"""Tests for the Pokemon Champions ranked-ladder (Reg M-B S3) scraper logic.

Covers:
  * season/regulation parsing + branding cleanup,
  * season id slug derivation,
  * form-slug extraction,
  * usage-rate derivation from game-share (ranked-ladder feed has no percent),
  * the dex_id collision guard in write_pokemon_files.
"""

import pytest

from src.scrapers.pikalytics import (
    PikalyticsScraper,
    SeasonInfo,
    _clean_format_name,
    _season_slug,
    _pct,
)
from src.models.schema import PokemonUsage
from src.output import write_pokemon_files


# --------------------------------------------------------------- name cleanup

@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "Pokemon Champions VGC 2026 Reg M-B S3 Ranked Battle Data",
            "Regulation Set M-B S3",
        ),
        (
            "Pokemon Champions VGC 2026 Regulation Set M-B S3 Ranked Battle Data",
            "Regulation Set M-B S3",
        ),
        ("Reg M-A Ranked Battle Data", "Regulation Set M-A"),
    ],
)
def test_clean_format_name_strips_branding(raw, expected):
    assert _clean_format_name(raw) == expected


def test_clean_format_name_empty_falls_back():
    assert _clean_format_name("   ") == "Regulation Set M-B S3"


# ---------------------------------------------------------------- slug + form

@pytest.mark.parametrize(
    "code,slug",
    [
        ("battledataregmbs3", "regmb-s3"),
        ("battledataregma", "regma"),
        ("championstournaments", "championstournaments"),
    ],
)
def test_season_slug(code, slug):
    assert _season_slug(code) == slug


@pytest.mark.parametrize(
    "name,form",
    [
        ("Garchomp", None),
        ("Floette-Eternal", "eternal"),
        ("Rotom-Wash", "wash"),
        ("Calyrex-Shadow-Rider", "shadow-rider"),
        ("Tauros-Paldea-Blaze", "paldea-blaze"),
    ],
)
def test_form_slug(name, form):
    assert PikalyticsScraper._form_slug(name) == form


# ----------------------------------------------------------------- season map

def test_season_info_to_model_populates_fields():
    scraper = PikalyticsScraper()
    info = SeasonInfo(
        name="Regulation Set M-B S3",
        format_code="battledataregmbs3",
        data_date="2026-05",
    )
    season = scraper.season_info_to_model(info)
    assert season is not None
    assert season.id == "regmb-s3"
    assert season.name == "Regulation Set M-B S3"
    assert season.format_code == "battledataregmbs3"
    assert season.data_date == "2026-05"
    assert season.start_date is not None
    assert season.start_date.isoformat() == "2026-05-01"


def test_season_info_to_model_none_when_missing():
    scraper = PikalyticsScraper()
    assert scraper.season_info_to_model(None) is None


def test_season_info_data_key():
    info = SeasonInfo("x", "battledataregmbs3", "2026-05")
    assert info.data_key == "2026-05/battledataregmbs3-1760"


# ------------------------------------------------------------------ pct parse

@pytest.mark.parametrize(
    "raw,out",
    [
        ("89.4", 0.894),
        ("51.5", 0.515),
        (None, 0.0),
        ("not-a-number", 0.0),
        ("150", 1.0),  # clamped
    ],
)
def test_pct(raw, out):
    assert _pct(raw) == pytest.approx(out)


# ------------------------------------------------------- collision guard (#2)

def _mk(dex_id, name, usage=0.1):
    return PokemonUsage(rank=1, dex_id=dex_id, name=name, usage_rate=usage)


def test_collision_guard_raises_on_distinct_forms_same_id(tmp_path):
    # Simulates the old Floette-Eternal-Mega / Floette-Eternal bug: two distinct
    # source rows resolving to the same dex_id must fail loudly, not overwrite.
    pokemon = [
        _mk(10061, "Floette-Eternal"),
        _mk(10061, "Floette-Eternal-Mega"),
    ]
    with pytest.raises(ValueError, match="dex_id collision"):
        write_pokemon_files(pokemon, tmp_path)


def test_collision_guard_allows_same_name_idempotent(tmp_path):
    # The same Pokemon twice (idempotent rewrite) is fine.
    pokemon = [_mk(727, "Incineroar"), _mk(727, "Incineroar")]
    written = write_pokemon_files(pokemon, tmp_path)
    assert len(written) == 2


def test_writes_distinct_ids(tmp_path):
    pokemon = [_mk(445, "Garchomp"), _mk(727, "Incineroar")]
    written = write_pokemon_files(pokemon, tmp_path)
    assert len(written) == 2
    names = {p.name for p in written}
    assert (tmp_path / "pokemon" / "445.json").exists()
    assert (tmp_path / "pokemon" / "727.json").exists()
