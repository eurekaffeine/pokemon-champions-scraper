"""Tests for the Pokemon Champions Showdown (Reg M-C) scraper logic.

Covers:
  * season/regulation parsing + branding cleanup,
  * season id slug derivation,
  * form-slug extraction,
  * native usage-rate parsing from the Showdown feed,
  * the dex_id collision guard in write_pokemon_files.
"""

import pytest
import json

from src.scrapers.pikalytics import (
    PikalyticsScraper,
    SeasonInfo,
    _clean_format_name,
    _season_slug,
    _pct,
)
from src.models.schema import PokemonUsage
from src.output import write_pokemon_files
from src.scrapers.base import ParseError


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
        ("Pokemon Champions VGC 2026 Reg M-C", "Regulation Set M-C"),
    ],
)
def test_clean_format_name_strips_branding(raw, expected):
    assert _clean_format_name(raw) == expected


def test_clean_format_name_empty_falls_back():
    assert _clean_format_name("   ") == "Regulation Set M-C"


# ---------------------------------------------------------------- slug + form

@pytest.mark.parametrize(
    "code,slug",
    [
        ("battledataregmbs3", "regmb-s3"),
        ("battledataregma", "regma"),
        ("gen9championsvgc2026regmc", "regmc"),
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
        name="Regulation Set M-C",
        format_code="gen9championsvgc2026regmc",
        data_date="2026-09",
        api_data_date="2026-05",
    )
    season = scraper.season_info_to_model(info)
    assert season is not None
    assert season.id == "regmc"
    assert season.name == "Regulation Set M-C"
    assert season.format_code == "gen9championsvgc2026regmc"
    assert season.data_date == "2026-09"
    assert season.start_date is not None
    assert season.start_date.isoformat() == "2026-09-01"


def test_season_info_to_model_none_when_missing():
    scraper = PikalyticsScraper()
    assert scraper.season_info_to_model(None) is None


def test_season_info_data_key():
    info = SeasonInfo("x", "gen9championsvgc2026regmc", "2026-09", "2026-05")
    assert info.data_key == "2026-05/gen9championsvgc2026regmc-1760"


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


@pytest.mark.asyncio
async def test_rankings_use_native_usage_not_game_share(monkeypatch):
    scraper = PikalyticsScraper(request_delay_ms=0)
    season = SeasonInfo(
        "Regulation Set M-C",
        "gen9championsvgc2026regmc",
        "2026-09",
        "2026-05",
    )
    payload = [
        {
            "name": "Rillaboom",
            "percent": "37.61",
            "games": 5937,
            "winrate": 0.503,
            "moves": [],
            "items": [],
            "abilities": [],
            "team": [],
            "teams": [
                {"tournamentDate": "2026-09-10T23:00:00.000Z"}
            ],
        },
        {
            "name": "Sneasler",
            "percent": "36.64",
            "games": 5783,
            "winrate": 0.498,
            "moves": [],
            "items": [],
            "abilities": [],
            "team": [],
        },
    ]

    async def scrape_season():
        return season

    async def fetch(url: str, retry_count: int = 0):
        assert url.endswith("/api/l/2026-05/gen9championsvgc2026regmc-1760")
        return json.dumps(payload)

    monkeypatch.setattr(scraper, "scrape_season", scrape_season)
    monkeypatch.setattr(scraper, "_fetch", fetch)

    rankings = await scraper.scrape_rankings()
    assert rankings[0].name == "Rillaboom"
    assert rankings[0].usage_rate == pytest.approx(0.3761)
    assert rankings[1].usage_rate == pytest.approx(0.3664)
    refreshed_season = await scraper.scrape_season()
    assert refreshed_season.data_date == "2026-09"


@pytest.mark.asyncio
async def test_rankings_fail_when_native_usage_is_missing(monkeypatch):
    scraper = PikalyticsScraper(request_delay_ms=0)
    season = SeasonInfo(
        "Regulation Set M-C",
        "gen9championsvgc2026regmc",
        "2026-09",
        "2026-05",
    )

    async def scrape_season():
        return season

    async def fetch(url: str, retry_count: int = 0):
        return json.dumps([{"name": "Rillaboom", "games": 5937}])

    monkeypatch.setattr(scraper, "scrape_season", scrape_season)
    monkeypatch.setattr(scraper, "_fetch", fetch)

    with pytest.raises(ParseError, match="omitted native usage percentage"):
        await scraper.scrape_rankings()


@pytest.mark.asyncio
async def test_rankings_aggregate_asset_equivalent_forms(monkeypatch):
    scraper = PikalyticsScraper(request_delay_ms=0)
    season = SeasonInfo(
        "Regulation Set M-C",
        "gen9championsvgc2026regmc",
        "2026-09",
        "2026-05",
    )
    payload = [
        {
            "name": "Sinistcha",
            "percent": "11.04",
            "games": 1743,
            "winrate": 0.50,
            "moves": [],
            "items": [],
            "abilities": [],
            "team": [],
        },
        {
            "name": "Sinistcha-Masterpiece",
            "percent": "2.81",
            "games": 444,
            "winrate": 0.60,
            "moves": [],
            "items": [],
            "abilities": [],
            "team": [],
        },
    ]

    async def scrape_season():
        return season

    async def fetch(url: str, retry_count: int = 0):
        return json.dumps(payload)

    monkeypatch.setattr(scraper, "scrape_season", scrape_season)
    monkeypatch.setattr(scraper, "_fetch", fetch)

    rankings = await scraper.scrape_rankings()
    assert len(rankings) == 1
    assert rankings[0].name == "Sinistcha"
    assert rankings[0].dex_id == 1013
    assert rankings[0].usage_rate == pytest.approx(0.1385)


@pytest.mark.asyncio
async def test_rankings_discard_impossible_species_abilities(monkeypatch):
    scraper = PikalyticsScraper(request_delay_ms=0)
    season = SeasonInfo(
        "Regulation Set M-C",
        "gen9championsvgc2026regmc",
        "2026-09",
        "2026-05",
    )
    payload = [
        {
            "name": "Rillaboom",
            "percent": "37.61",
            "games": 5937,
            "winrate": 0.503,
            "moves": [],
            "items": [],
            "abilities": [
                {"ability": "Grassy Surge", "percent": "99.042"},
                {"ability": "Trace", "percent": "0.733"},
                {"ability": "Hospitality", "percent": "0.113"},
            ],
            "team": [],
        }
    ]

    async def scrape_season():
        return season

    async def fetch(url: str, retry_count: int = 0):
        return json.dumps(payload)

    monkeypatch.setattr(scraper, "scrape_season", scrape_season)
    monkeypatch.setattr(scraper, "_fetch", fetch)

    rankings = await scraper.scrape_rankings()
    assert [(entry.id, entry.usage) for entry in rankings[0].top_abilities] == [
        (229, pytest.approx(0.99042))
    ]


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
