"""Smogon statistics scraper for Pokémon Champions Battle Stadium Singles.

Smogon publishes monthly Pokémon Showdown usage snapshots. The ranking text
contains the exact weighted usage and rank, while the Chaos JSON contains the
weighted move, item, ability, teammate, and spread distributions.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

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
    resolve_pokemon_id,
)
from src.scrapers.base import BaseScraper, ParseError

logger = logging.getLogger(__name__)

SINGLES_FORMAT_CODE = "gen9championsbssregmb"
SINGLES_CUTOFF = 1760
_MONTH_LOOKBACK = 12
_RANKING_ROW = re.compile(
    r"^\|\s*(?P<rank>\d+)\s*\|\s*(?P<name>.*?)\s*\|\s*"
    r"(?P<usage>[\d.]+)%\s*\|\s*(?P<raw>\d+)\s*\|",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SmogonSeasonInfo:
    """Resolved monthly snapshot metadata."""

    data_date: str
    battle_count: int = 0
    format_code: str = SINGLES_FORMAT_CODE
    cutoff: int = SINGLES_CUTOFF


@dataclass(frozen=True)
class RankingRow:
    rank: int
    name: str
    usage_rate: float
    raw_count: int


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _month_candidates(today: Optional[date] = None, count: int = _MONTH_LOOKBACK) -> list[str]:
    """Return completed months newest-first.

    Smogon publishes a month's files after the month ends, so the current
    calendar month is intentionally excluded.
    """
    cursor = _previous_month((today or date.today()).replace(day=1))
    result: list[str] = []
    for _ in range(count):
        result.append(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = _previous_month(cursor)
    return result


def parse_rankings(text: str) -> list[RankingRow]:
    rows = [
        RankingRow(
            rank=int(match.group("rank")),
            name=match.group("name").strip(),
            usage_rate=min(1.0, float(match.group("usage")) / 100),
            raw_count=int(match.group("raw")),
        )
        for match in _RANKING_ROW.finditer(text)
    ]
    if not rows:
        raise ParseError("Smogon ranking file contained no Pokémon rows")
    return rows


def _normalized_entries(values: dict, denominator: float, resolver, model_cls) -> list:
    if denominator <= 0 or not isinstance(values, dict):
        return []
    # Several cosmetic source names can intentionally share one Pocket Gallery
    # asset ID. Aggregate them before normalization so the output never contains
    # duplicate IDs.
    by_id: dict[int, float] = defaultdict(float)
    for name, weight in values.items():
        resolved_id = resolver(name)
        if resolved_id <= 0:
            continue
        try:
            by_id[resolved_id] += float(weight)
        except (TypeError, ValueError):
            continue
    result = []
    for resolved_id, weight in sorted(by_id.items(), key=lambda item: item[1], reverse=True):
        usage = min(1.0, max(0.0, weight / denominator))
        if usage > 0:
            result.append(model_cls(id=resolved_id, usage=usage))
    return result


def _form_slug(name: str) -> Optional[str]:
    if "-" not in name:
        return None
    return name.partition("-")[2].strip().lower() or None


class SmogonSinglesScraper(BaseScraper):
    """Scrape Champions Regulation M-B singles from Smogon monthly stats."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._season_info: Optional[SmogonSeasonInfo] = None
        self._ranking_text: Optional[str] = None
        self._chaos_data: Optional[dict] = None
        self._details_by_name: dict[str, PokemonUsage] = {}

    @property
    def name(self) -> str:
        return "Pokémon Showdown / Smogon Stats"

    @property
    def base_url(self) -> str:
        return "https://www.smogon.com/stats"

    def _ranking_url(self, month: str) -> str:
        return f"{self.base_url}/{month}/{SINGLES_FORMAT_CODE}-{SINGLES_CUTOFF}.txt"

    def _chaos_url(self, month: str) -> str:
        return (
            f"{self.base_url}/{month}/chaos/"
            f"{SINGLES_FORMAT_CODE}-{SINGLES_CUTOFF}.json"
        )

    async def _snapshot_exists(self, month: str) -> bool:
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for url in (self._ranking_url(month), self._chaos_url(month)):
                try:
                    response = await client.head(url, headers=headers)
                    if response.status_code != 200:
                        return False
                except httpx.HTTPError:
                    return False
        return True

    async def scrape_season(self) -> Optional[SmogonSeasonInfo]:
        if self._season_info is not None:
            return self._season_info
        for month in _month_candidates():
            if await self._snapshot_exists(month):
                self._season_info = SmogonSeasonInfo(data_date=month)
                return self._season_info
        raise ParseError(
            f"No complete {SINGLES_FORMAT_CODE}-{SINGLES_CUTOFF} snapshot found "
            f"within the last {_MONTH_LOOKBACK} completed months"
        )

    def season_info_to_model(self, info: Optional[SmogonSeasonInfo]) -> Optional[Season]:
        if info is None:
            return None
        year, month = (int(part) for part in info.data_date.split("-"))
        return Season(
            id="champions-bss-regmb",
            name="Battle Stadium Singles Regulation Set M-B",
            format_code=info.format_code,
            data_date=info.data_date,
            start_date=date(year, month, 1),
            end_date=None,
        )

    async def _load_snapshot(self) -> tuple[list[RankingRow], dict]:
        info = await self.scrape_season()
        if info is None:
            raise ParseError("Smogon singles season metadata is unavailable")

        if self._ranking_text is None:
            self._ranking_text = await self._fetch(self._ranking_url(info.data_date))
        if self._chaos_data is None:
            raw = await self._fetch(self._chaos_url(info.data_date))
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ParseError(f"Smogon Chaos response was not valid JSON: {exc}") from exc
            chaos_info = payload.get("info", {})
            if chaos_info.get("metagame") != SINGLES_FORMAT_CODE:
                raise ParseError("Smogon Chaos response has the wrong metagame")
            if int(chaos_info.get("cutoff", 0)) != SINGLES_CUTOFF:
                raise ParseError("Smogon Chaos response has the wrong cutoff")
            data = payload.get("data")
            if not isinstance(data, dict) or not data:
                raise ParseError("Smogon Chaos response contained no Pokémon data")
            self._chaos_data = data
            self._season_info = SmogonSeasonInfo(
                data_date=info.data_date,
                battle_count=int(chaos_info.get("number of battles", 0)),
            )

        return parse_rankings(self._ranking_text), self._chaos_data

    @staticmethod
    def _canonical_name(names: list[str]) -> str:
        # Prefer the unsuffixed asset name when several cosmetic forms share an ID.
        return min(names, key=lambda name: ("-" in name, len(name), name))

    @staticmethod
    def _sum_distributions(records: list[dict], key: str) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for record in records:
            values = record.get(key, {})
            if not isinstance(values, dict):
                continue
            for name, weight in values.items():
                try:
                    result[name] += float(weight)
                except (TypeError, ValueError):
                    continue
        return dict(result)

    def _build_details(self, names: list[str], records: list[dict], dex_id: int) -> PokemonUsage:
        abilities = self._sum_distributions(records, "Abilities")
        denominator = sum(abilities.values())
        if denominator <= 0:
            denominator = sum(float(record.get("Raw count", 0)) for record in records)
        canonical_name = self._canonical_name(names)
        return PokemonUsage(
            rank=0,
            dex_id=dex_id,
            name=canonical_name,
            form=_form_slug(canonical_name),
            usage_rate=0.0,
            top_moves=_normalized_entries(
                self._sum_distributions(records, "Moves"),
                denominator,
                resolve_move_id,
                MoveUsage,
            ),
            top_items=_normalized_entries(
                self._sum_distributions(records, "Items"),
                denominator,
                resolve_item_id,
                ItemUsage,
            ),
            top_abilities=_normalized_entries(
                abilities,
                denominator,
                resolve_ability_id,
                AbilityUsage,
            ),
            top_teammates=_normalized_entries(
                self._sum_distributions(records, "Teammates"),
                denominator,
                resolve_pokemon_id,
                TeammateUsage,
            ),
        )

    async def scrape_rankings(self, limit: int = 400) -> list[PokemonUsage]:
        ranking_rows, chaos = await self._load_snapshot()

        grouped_rows: dict[int, list[RankingRow]] = defaultdict(list)
        unresolved: list[str] = []
        for row in ranking_rows:
            dex_id = resolve_pokemon_id(row.name)
            if dex_id <= 0:
                unresolved.append(row.name)
            else:
                grouped_rows[dex_id].append(row)
        if unresolved:
            raise ParseError(f"Unresolved Smogon Pokémon names: {', '.join(unresolved)}")

        grouped_chaos: dict[int, list[tuple[str, dict]]] = defaultdict(list)
        for name, record in chaos.items():
            dex_id = resolve_pokemon_id(name)
            if dex_id > 0:
                grouped_chaos[dex_id].append((name, record))

        combined: list[PokemonUsage] = []
        self._details_by_name.clear()
        for dex_id, rows in grouped_rows.items():
            names = [row.name for row in rows]
            usage_rate = min(1.0, sum(row.usage_rate for row in rows))
            chaos_records = grouped_chaos.get(dex_id, [])
            detail_names = [name for name, _ in chaos_records] or names
            detail_records = [record for _, record in chaos_records]
            detail = self._build_details(detail_names, detail_records, dex_id)
            pokemon = detail.model_copy(update={"usage_rate": usage_rate})
            combined.append(pokemon)

        combined.sort(key=lambda pokemon: (-pokemon.usage_rate, pokemon.name))
        ranked: list[PokemonUsage] = []
        for rank, pokemon in enumerate(combined[:limit], start=1):
            ranked_pokemon = pokemon.model_copy(update={"rank": rank})
            ranked.append(ranked_pokemon)
            self._details_by_name[ranked_pokemon.name] = ranked_pokemon

        logger.info(
            "Scraped %d asset-safe Pokémon from %d Smogon singles rows",
            len(ranked),
            len(ranking_rows),
        )
        return ranked

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        # All details are loaded in the single Chaos snapshot request.
        return self._details_by_name.get(name)
