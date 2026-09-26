"""MunchStats scraper for live Pokemon Champions in-game Singles data.

MunchStats captures the game's Battle Data screens nightly. Pokemon Champions
publishes popularity as an ordinal rank, not a percentage, so public
``usage_rate`` remains 0.0 for mobile-schema compatibility.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

from src.models.schema import (
    AbilityUsage,
    ItemUsage,
    MoveUsage,
    PokemonUsage,
    Season,
    TeammateUsage,
)
from src.name_resolver import (
    resolve_ability_id,
    resolve_item_id,
    resolve_move_id,
    resolve_pokemon_ability_ids,
    resolve_pokemon_id,
)
from src.scrapers.base import BaseScraper, ParseError

logger = logging.getLogger(__name__)

SINGLES_FORMAT_CODE = "championssingles"
_MIN_CRAWL_DELAY_MS = 10_000
_PUBLIC_LIST_LIMIT = 10
_RANKING_BLOCK = re.compile(
    r"window\.calcPokemonOptions\s*=\s*\[(.*?)\];", re.DOTALL
)
_RANKING_ENTRY = re.compile(
    r'name:\s*"([^"]+)",\s*usage:\s*"#(\d+)"'
)
_SCRAPED_AT = re.compile(
    r"Game data last scraped:\s*<span[^>]*>([^<]+)</span>", re.I
)


@dataclass(frozen=True)
class MunchStatsSeasonInfo:
    data_date: str
    format_code: str = SINGLES_FORMAT_CODE


@dataclass(frozen=True)
class RankedPokemon:
    rank: int
    name: str
    dex_id: int
    source_name: str


def _decode_js_string(value: str) -> str:
    """Decode JSON-compatible JavaScript string escapes safely."""
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def _form_slug(name: str) -> Optional[str]:
    if "-" not in name:
        return None
    return name.partition("-")[2].strip().lower() or None


class MunchStatsSinglesScraper(BaseScraper):
    """Scrape live in-game Regulation M-C Singles data from MunchStats."""

    def __init__(self, *args, **kwargs):
        # MunchStats' robots.txt requests a 10-second crawl delay.
        requested_delay = int(kwargs.pop("request_delay_ms", 1000))
        super().__init__(
            *args,
            request_delay_ms=max(requested_delay, _MIN_CRAWL_DELAY_MS),
            **kwargs,
        )
        self._ranking_html: Optional[str] = None
        self._season_info: Optional[MunchStatsSeasonInfo] = None
        self._source_name_by_output_name: dict[str, str] = {}
        self._details_by_name: dict[str, PokemonUsage] = {}

    @property
    def name(self) -> str:
        return "MunchStats in-game Battle Data"

    @property
    def base_url(self) -> str:
        return "https://munchstats.com"

    def _pokemon_url(self, name: str) -> str:
        return f"{self.base_url}/champions/singles/{quote(name, safe='-')}"

    async def _load_ranking_page(self) -> str:
        if self._ranking_html is None:
            self._ranking_html = await self._fetch(
                f"{self.base_url}/champions/singles/"
            )
        return self._ranking_html

    @staticmethod
    def _parse_data_date(markup: str) -> str:
        match = _SCRAPED_AT.search(markup)
        if not match:
            raise ParseError("MunchStats page omitted its capture timestamp")
        raw = re.sub(r"\s+", " ", match.group(1)).strip()
        try:
            return datetime.strptime(raw, "%B %d, %Y at %H:%M UTC").strftime(
                "%Y-%m"
            )
        except ValueError as exc:
            raise ParseError(f"Unrecognized MunchStats capture timestamp: {raw}") from exc

    async def scrape_season(self) -> MunchStatsSeasonInfo:
        if self._season_info is None:
            markup = await self._load_ranking_page()
            self._season_info = MunchStatsSeasonInfo(
                data_date=self._parse_data_date(markup)
            )
        return self._season_info

    def season_info_to_model(
        self, info: Optional[MunchStatsSeasonInfo]
    ) -> Optional[Season]:
        if info is None:
            return None
        year, month = (int(part) for part in info.data_date.split("-"))
        return Season(
            id="champions-singles-regmc",
            name="Battle Stadium Singles Regulation Set M-C",
            format_code=info.format_code,
            data_date=info.data_date,
            start_date=date(year, month, 1),
            end_date=None,
        )

    @staticmethod
    def _canonical_name(names: list[str]) -> str:
        return min(names, key=lambda name: ("-" in name, len(name), name))

    @staticmethod
    def _parse_rankings(markup: str) -> list[tuple[int, str]]:
        block = _RANKING_BLOCK.search(markup)
        if not block:
            raise ParseError("MunchStats page omitted the ranked Pokemon list")
        rows = [
            (int(rank), _decode_js_string(raw_name))
            for raw_name, rank in _RANKING_ENTRY.findall(block.group(1))
        ]
        if len(rows) < 100:
            raise ParseError(
                f"MunchStats ranking list was unexpectedly short ({len(rows)} rows)"
            )
        return rows

    async def scrape_rankings(self, limit: int = 400) -> list[PokemonUsage]:
        markup = await self._load_ranking_page()
        await self.scrape_season()
        grouped: dict[int, list[tuple[int, str]]] = defaultdict(list)
        unresolved: list[tuple[int, str]] = []
        for rank, name in self._parse_rankings(markup):
            dex_id = resolve_pokemon_id(name)
            if dex_id <= 0:
                unresolved.append((rank, name))
            else:
                grouped[dex_id].append((rank, name))

        # A source typo must not fabricate an identity. Skip only isolated
        # unresolved tail rows and fail if the source degrades materially.
        if unresolved:
            logger.warning(
                "Skipping unresolved MunchStats ranking rows: %s", unresolved
            )
        if len(unresolved) > 5 or any(rank <= 100 for rank, _ in unresolved):
            raise ParseError(
                "MunchStats has unresolved high-impact Pokemon names: "
                + ", ".join(f"#{rank} {name}" for rank, name in unresolved)
            )

        combined: list[RankedPokemon] = []
        for dex_id, rows in grouped.items():
            source_rank, source_name = min(rows, key=lambda row: row[0])
            names = [name for _, name in rows]
            combined.append(
                RankedPokemon(
                    rank=source_rank,
                    name=self._canonical_name(names),
                    dex_id=dex_id,
                    source_name=source_name,
                )
            )
        combined.sort(key=lambda pokemon: (pokemon.rank, pokemon.name))

        result: list[PokemonUsage] = []
        self._source_name_by_output_name.clear()
        for pokemon in combined[:limit]:
            result.append(
                PokemonUsage(
                    rank=pokemon.rank,
                    dex_id=pokemon.dex_id,
                    name=pokemon.name,
                    form=_form_slug(pokemon.name),
                    usage_rate=0.0,
                )
            )
            self._source_name_by_output_name[pokemon.name] = pokemon.source_name

        logger.info(
            "Scraped %d asset-safe Pokemon from %d MunchStats Singles rows",
            len(result),
            sum(len(rows) for rows in grouped.values()),
        )
        return result

    @staticmethod
    def _parse_percent(value: str) -> float:
        try:
            return min(1.0, max(0.0, float(value.replace("%", "")) / 100))
        except (TypeError, ValueError):
            return 0.0

    def _parse_usage_section(self, soup, title: str, resolver, model_cls) -> list:
        heading = next(
            (h for h in soup.find_all(["h2", "h3"]) if h.get_text(" ", strip=True) == title),
            None,
        )
        if heading is None:
            return []
        container = heading.find_next_sibling()
        result = []
        seen: set[int] = set()
        for row in container.select("li") if container else []:
            name_element = row.select_one(".left-text")
            usage_element = row.select_one(".right-text")
            if name_element is None or usage_element is None:
                continue
            resolved_id = resolver(name_element.get_text(" ", strip=True))
            usage = self._parse_percent(usage_element.get_text(" ", strip=True))
            if resolved_id > 0 and resolved_id not in seen and usage > 0:
                seen.add(resolved_id)
                result.append(model_cls(id=resolved_id, usage=usage))
        return result[:_PUBLIC_LIST_LIMIT]

    def _parse_teammates(self, soup) -> list[TeammateUsage]:
        heading = next(
            (h for h in soup.find_all(["h2", "h3"]) if h.get_text(" ", strip=True) == "Teammates"),
            None,
        )
        if heading is None:
            return []
        container = heading.find_next_sibling()
        result = []
        seen: set[int] = set()
        for row in container.select("li") if container else []:
            name_element = row.select_one(".left-text")
            if name_element is None:
                continue
            dex_id = resolve_pokemon_id(name_element.get_text(" ", strip=True))
            if dex_id > 0 and dex_id not in seen:
                seen.add(dex_id)
                result.append(TeammateUsage(id=dex_id, usage=0.0))
        return result[:_PUBLIC_LIST_LIMIT]

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        source_name = self._source_name_by_output_name.get(name, name)
        markup = (
            self._ranking_html
            if source_name == "Salamence" and self._ranking_html is not None
            else await self._fetch(self._pokemon_url(source_name))
        )
        soup = self._parse_html(markup)
        dex_id = resolve_pokemon_id(name)
        abilities = self._parse_usage_section(
            soup, "Abilities", resolve_ability_id, AbilityUsage
        )
        allowed = resolve_pokemon_ability_ids(dex_id)
        if not allowed:
            raise ParseError(f"No ability allow-list for {name} (dex_id={dex_id})")
        invalid = [entry.id for entry in abilities if entry.id not in allowed]
        if invalid:
            raise ParseError(f"MunchStats exposed invalid abilities for {name}: {invalid}")

        return PokemonUsage(
            rank=0,
            dex_id=dex_id,
            name=name,
            form=_form_slug(name),
            usage_rate=0.0,
            top_moves=self._parse_usage_section(
                soup, "Moves", resolve_move_id, MoveUsage
            ),
            top_items=self._parse_usage_section(
                soup, "Items", resolve_item_id, ItemUsage
            ),
            top_abilities=abilities,
            top_teammates=self._parse_teammates(soup),
        )

    async def scrape(
        self, limit: int = 400, include_details: bool = True
    ) -> list[PokemonUsage]:
        """Fail closed when any requested in-game detail page is unusable."""
        started = time.time()
        self.reset_stats()
        try:
            rankings = await self.scrape_rankings(limit=limit)
            self._stats.pokemon_scraped = len(rankings)
            if not include_details:
                return rankings

            enriched: list[PokemonUsage] = []
            failures: list[str] = []
            for pokemon in rankings:
                try:
                    detail = await self.scrape_pokemon_detail(pokemon.name)
                    if detail is None:
                        failures.append(f"{pokemon.name}: detail missing")
                    else:
                        enriched.append(self._merge_pokemon_data(pokemon, detail))
                except Exception as exc:
                    failures.append(f"{pokemon.name}: {exc}")

            if failures:
                self._stats.pokemon_failed = len(failures)
                self._stats.errors.extend(failures)
                raise ParseError(
                    f"MunchStats detail validation failed for {len(failures)} Pokemon: "
                    + "; ".join(failures[:10])
                )
            return enriched
        finally:
            self._stats.total_time_ms = (time.time() - started) * 1000
