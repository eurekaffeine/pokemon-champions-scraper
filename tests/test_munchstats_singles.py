import json

import pytest

from src.models.schema import PokemonUsage
from src.scrapers.base import ParseError
from src.scrapers.munchstats import MunchStatsSinglesScraper, _decode_js_string


def ranking_markup(entries, captured="September 25, 2026 at 23:53 UTC"):
    rows = "\n".join(
        f'{{ name: "{name}", usage: "#{rank}" }},' for rank, name in entries
    )
    return (
        f"Game data last scraped: <span>{captured}</span>"
        f"<script>window.calcPokemonOptions = [{rows}];</script>"
    )


def detail_markup(name="Salamence"):
    return f"<title>{name} | MunchStats | [Champions] In-Game Singles</title>" + """
    <h2>Moves</h2><div><ul>
      <li><span class="left-text">Double-Edge</span><span class="right-text">77.7%</span></li>
      <li><span class="left-text">Earthquake</span><span class="right-text">72.8%</span></li>
    </ul></div>
    <h2>Teammates</h2><div><ul>
      <li><span class="left-text">Primarina</span><span class="right-text">#1</span></li>
    </ul></div>
    <h2>Items</h2><div><ul>
      <li><span class="left-text">Life Orb</span><span class="right-text">12.5%</span></li>
    </ul></div>
    <h2>Abilities</h2><div><ul>
      <li><span class="left-text">Intimidate</span><span class="right-text">99.1%</span></li>
      <li><span class="left-text">Moxie</span><span class="right-text">0.9%</span></li>
    </ul></div>
    """


def test_decode_js_unicode_escape():
    assert _decode_js_string(r"Sirfetch\u2019d") == "Sirfetch’d"


@pytest.mark.asyncio
async def test_munchstats_preserves_rank_and_zero_usage(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    entries = [(index, "Salamence" if index == 1 else f"Pokemon-{index}") for index in range(1, 101)]
    # Use real resolvable names for all rows while retaining 100+ source rows.
    names = ["Salamence", "Garchomp", "Primarina", "Hippowdon"]
    entries = [(index + 1, names[index % len(names)]) for index in range(100)]
    markup = ranking_markup(entries)

    async def fetch(url: str, retry_count: int = 0):
        return markup

    monkeypatch.setattr(scraper, "_fetch", fetch)
    pokemon = await scraper.scrape_rankings(limit=10)
    assert [entry.name for entry in pokemon] == names
    assert [entry.rank for entry in pokemon] == [1, 2, 3, 4]
    assert all(entry.usage_rate == 0.0 for entry in pokemon)
    season = scraper.season_info_to_model(await scraper.scrape_season())
    assert season is not None
    assert season.id == "champions-singles-regmc"
    assert season.data_date == "2026-09"


@pytest.mark.asyncio
async def test_munchstats_detail_keeps_mobile_shapes(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    scraper._source_name_by_output_name["Salamence"] = "Salamence"

    async def fetch(url: str, retry_count: int = 0):
        return detail_markup()

    monkeypatch.setattr(scraper, "_fetch", fetch)
    detail = await scraper.scrape_pokemon_detail("Salamence")
    assert detail is not None
    assert detail.usage_rate == 0.0
    assert [(entry.id, entry.usage) for entry in detail.top_abilities] == [
        (22, pytest.approx(0.991)),
        (153, pytest.approx(0.009)),
    ]
    assert detail.top_teammates[0].usage == 0.0


@pytest.mark.asyncio
async def test_salamence_detail_does_not_reuse_new_number_one_page(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    # Garchomp overtook Salamence on September 29. The landing page's Sand
    # Veil/Rough Skin data must never be parsed as Salamence's build.
    scraper._ranking_html = detail_markup("Garchomp").replace(
        "Intimidate", "Sand Veil"
    ).replace("Moxie", "Rough Skin")
    fetched = []

    async def fetch(url: str, retry_count: int = 0):
        fetched.append(url)
        return detail_markup()

    monkeypatch.setattr(scraper, "_fetch", fetch)
    detail = await scraper.scrape_pokemon_detail("Salamence")
    assert fetched == ["https://munchstats.com/champions/singles/Salamence"]
    assert [entry.id for entry in detail.top_abilities] == [22, 153]


@pytest.mark.asyncio
@pytest.mark.parametrize("page_name", ["Staraptor", ""])
async def test_detail_rejects_wrong_or_missing_page_identity(monkeypatch, page_name):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)

    async def fetch(url: str, retry_count: int = 0):
        # Even a page containing legal Salamence abilities must match identity.
        markup = detail_markup(page_name)
        return markup if page_name else markup.replace(
            "<title> | MunchStats | [Champions] In-Game Singles</title>", ""
        )

    monkeypatch.setattr(scraper, "_fetch", fetch)
    with pytest.raises(ParseError, match="detail identity mismatch"):
        await scraper.scrape_pokemon_detail("Salamence")


@pytest.mark.asyncio
async def test_detail_still_rejects_illegal_abilities_on_correct_page(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)

    async def fetch(url: str, retry_count: int = 0):
        return detail_markup().replace("Moxie", "Rough Skin")

    monkeypatch.setattr(scraper, "_fetch", fetch)
    with pytest.raises(ParseError, match="invalid abilities"):
        await scraper.scrape_pokemon_detail("Salamence")


@pytest.mark.asyncio
async def test_detail_accepts_asset_equivalent_cosmetic_form(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    scraper._source_name_by_output_name["Gourgeist"] = "Gourgeist-Super"
    fetched = []

    async def fetch(url: str, retry_count: int = 0):
        fetched.append(url)
        return detail_markup("Gourgeist-Super").replace(
            "Intimidate", "Frisk"
        ).replace("Moxie", "Insomnia")

    monkeypatch.setattr(scraper, "_fetch", fetch)
    detail = await scraper.scrape_pokemon_detail("Gourgeist")
    assert fetched == ["https://munchstats.com/champions/singles/Gourgeist-Super"]
    assert detail.dex_id == 711


@pytest.mark.asyncio
async def test_munchstats_fails_on_unresolved_top_100(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    entries = [(1, "Definitely-Not-A-Pokemon")] + [
        (index, "Garchomp") for index in range(2, 102)
    ]

    async def fetch(url: str, retry_count: int = 0):
        return ranking_markup(entries)

    monkeypatch.setattr(scraper, "_fetch", fetch)
    with pytest.raises(ParseError, match="unresolved high-impact"):
        await scraper.scrape_rankings()


@pytest.mark.asyncio
async def test_full_scrape_fails_closed_when_detail_is_invalid(monkeypatch):
    scraper = MunchStatsSinglesScraper(request_delay_ms=0)
    rankings = [
        PokemonUsage(
            rank=1, dex_id=445, name="Garchomp", usage_rate=0.0
        )
    ]

    async def scrape_rankings(limit: int = 400):
        return rankings

    async def detail(name: str):
        raise ParseError("invalid ability")

    monkeypatch.setattr(scraper, "scrape_rankings", scrape_rankings)
    monkeypatch.setattr(scraper, "scrape_pokemon_detail", detail)
    with pytest.raises(ParseError, match="detail validation failed"):
        await scraper.scrape(limit=1, include_details=True)


def test_collapsed_squawkabilly_allows_sibling_form_ability():
    from src.name_resolver import resolve_ability_id, resolve_pokemon_ability_ids

    assert resolve_ability_id("Sheer Force") in resolve_pokemon_ability_ids(931)
