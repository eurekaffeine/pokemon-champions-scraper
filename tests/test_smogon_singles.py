import json
from datetime import date
from pathlib import Path

import pytest

from src.output import write_battle_meta, write_pokemon_files
from src.scrapers.base import ParseError
from src.scrapers.smogon import (
    SmogonSinglesScraper,
    _month_candidates,
    parse_rankings,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_month_candidates_exclude_current_month():
    assert _month_candidates(date(2026, 7, 29), count=3) == [
        "2026-06",
        "2026-05",
        "2026-04",
    ]


def test_ranking_parser_keeps_exact_usage_and_raw_count():
    rows = parse_rankings(fixture_text("smogon_singles_rankings.txt"))
    assert rows[0].rank == 1
    assert rows[0].name == "Garchomp"
    assert rows[0].usage_rate == pytest.approx(0.4662038)
    assert rows[0].raw_count == 48973


@pytest.mark.asyncio
async def test_singles_scraper_emits_existing_schema_and_asset_safe_ids(monkeypatch, tmp_path):
    scraper = SmogonSinglesScraper(request_delay_ms=0)
    ranking_text = fixture_text("smogon_singles_rankings.txt")
    chaos_text = fixture_text("smogon_singles_chaos.json")

    async def snapshot_exists(month: str, include_details: bool = True) -> bool:
        return month == "2026-06"

    async def fetch(url: str, retry_count: int = 0) -> str:
        return chaos_text if "/chaos/" in url else ranking_text

    monkeypatch.setattr(scraper, "_snapshot_exists", snapshot_exists)
    monkeypatch.setattr(scraper, "_fetch", fetch)

    pokemon = await scraper.scrape(limit=20, include_details=True)
    by_name = {entry.name: entry for entry in pokemon}

    assert "Garchomp" in by_name
    assert "Garchomp-Mega" in by_name
    assert by_name["Garchomp"].dex_id == 445
    assert by_name["Garchomp-Mega"].dex_id == 10058
    assert by_name["Garchomp"].top_moves[0].usage == pytest.approx(0.99)
    assert sum(entry.usage for entry in by_name["Garchomp"].top_abilities) == pytest.approx(1.0)
    assert by_name["Garchomp"].top_spreads[0].nature_id == 16
    assert by_name["Garchomp"].top_spreads[0].nature == "Jolly"
    assert by_name["Garchomp"].top_spreads[0].evs == "2/32/0/0/0/32"
    assert by_name["Garchomp"].top_spreads[0].usage == pytest.approx(0.7)

    # Cosmetic Gourgeist sizes intentionally share one app asset and are
    # aggregated into one row/file instead of colliding.
    gourgeist = [entry for entry in pokemon if entry.dex_id == 711]
    assert len(gourgeist) == 1
    assert gourgeist[0].usage_rate == pytest.approx(0.007)
    assert gourgeist[0].rank == 3  # rank is re-derived after aggregation

    season = scraper.season_info_to_model(await scraper.scrape_season())
    assert season is not None
    assert season.id == "champions-bss-regmb"
    assert season.data_date == "2026-06"

    from datetime import datetime, timezone
    from src.models.schema import BattleMeta, SourceInfo

    meta = BattleMeta(
        updated_at=datetime.now(timezone.utc),
        season=season,
        pokemon_usage=pokemon,
        sources=[
            SourceInfo(
                name=scraper.name,
                url=scraper.base_url,
                scraped_at=datetime.now(timezone.utc),
            )
        ],
    )
    meta_path = write_battle_meta(meta, tmp_path / "singles")
    detail_paths = write_pokemon_files(pokemon, tmp_path / "singles")

    payload = json.loads(meta_path.read_text())
    assert set(payload["pokemon_usage"][0]) == {
        "rank",
        "dex_id",
        "name",
        "form",
        "usage_rate",
        "win_rate",
        "top_moves",
        "top_items",
        "top_abilities",
        "top_teammates",
        "top_tera_types",
        "top_spreads",
    }
    assert meta_path == tmp_path / "singles" / "battle_meta.json"
    assert all(path.parent == tmp_path / "singles" / "pokemon" for path in detail_paths)
    detail_payload = json.loads(detail_paths[0].read_text())
    assert set(detail_payload) == {"dex_id", "name", "form", "competitive"}
    assert set(detail_payload["competitive"]) == {
        "usage_rank",
        "usage_rate",
        "win_rate",
        "moves",
        "items",
        "abilities",
        "teammates",
        "tera_types",
        "spreads",
    }


@pytest.mark.asyncio
async def test_no_details_downloads_only_rankings(monkeypatch):
    scraper = SmogonSinglesScraper(request_delay_ms=0)
    ranking_text = fixture_text("smogon_singles_rankings.txt")
    requested: list[str] = []

    async def snapshot_exists(month: str, include_details: bool = True) -> bool:
        assert include_details is False
        return month == "2026-06"

    async def fetch(url: str, retry_count: int = 0) -> str:
        requested.append(url)
        assert "/chaos/" not in url
        return ranking_text

    monkeypatch.setattr(scraper, "_snapshot_exists", snapshot_exists)
    monkeypatch.setattr(scraper, "_fetch", fetch)
    pokemon = await scraper.scrape(limit=20, include_details=False)

    assert len(requested) == 1
    assert pokemon
    assert all(not entry.top_moves for entry in pokemon)
    assert all(not entry.top_items for entry in pokemon)
    assert all(not entry.top_abilities for entry in pokemon)
    assert all(not entry.top_teammates for entry in pokemon)
    assert all(not entry.top_spreads for entry in pokemon)


@pytest.mark.asyncio
async def test_transient_discovery_error_aborts_instead_of_falling_back(monkeypatch):
    scraper = SmogonSinglesScraper(request_delay_ms=0)
    checked: list[str] = []

    async def snapshot_exists(month: str, include_details: bool = True) -> bool:
        checked.append(month)
        raise ParseError("transient 503")

    monkeypatch.setattr(scraper, "_snapshot_exists", snapshot_exists)
    with pytest.raises(ParseError, match="transient 503"):
        await scraper.scrape_season()
    assert checked == [_month_candidates()[0]]


@pytest.mark.asyncio
async def test_unresolved_chaos_record_fails_snapshot(monkeypatch):
    scraper = SmogonSinglesScraper(request_delay_ms=0)
    ranking_text = fixture_text("smogon_singles_rankings.txt")
    chaos = json.loads(fixture_text("smogon_singles_chaos.json"))
    chaos["data"]["Definitely-Not-A-Pokemon"] = {
        "Raw count": 1,
        "Abilities": {},
        "Items": {},
        "Spreads": {},
        "Moves": {},
        "Teammates": {},
    }

    async def snapshot_exists(month: str, include_details: bool = True) -> bool:
        return month == "2026-06"

    async def fetch(url: str, retry_count: int = 0) -> str:
        return json.dumps(chaos) if "/chaos/" in url else ranking_text

    monkeypatch.setattr(scraper, "_snapshot_exists", snapshot_exists)
    monkeypatch.setattr(scraper, "_fetch", fetch)
    with pytest.raises(ParseError, match="Definitely-Not-A-Pokemon"):
        await scraper.scrape(limit=20, include_details=True)


def test_public_output_paths_keep_doubles_at_root():
    output = Path("output")
    assert output / "battle_meta.json" == Path("output/battle_meta.json")
    assert output / "pokemon" == Path("output/pokemon")
    assert output / "singles" / "battle_meta.json" == Path(
        "output/singles/battle_meta.json"
    )
    assert output / "singles" / "pokemon" == Path("output/singles/pokemon")
