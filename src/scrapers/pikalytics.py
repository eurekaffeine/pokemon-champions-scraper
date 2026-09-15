# src/scrapers/pikalytics.py
"""Pikalytics scraper for Pokemon Champions competitive data.

Source of truth: Pikalytics' Pokemon Champions Regulation M-C **Showdown**
feed (`gen9championsvgc2026regmc`). It represents broad online battle usage,
rather than the smaller and more selective tournament-only population.

The feed exposes a native Pokemon usage percentage in each row's `percent`
field. That value must be used directly: dividing a Pokemon's `games` by the
sum of every Pokemon's games instead measures its share of all team slots and
understates the source's published usage by roughly a factor of six.
"""

import logging
import re
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.scrapers.base import BaseScraper, ParseError
from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
    Season,
)
from src.name_resolver import (
    resolve_move_id,
    resolve_ability_id,
    resolve_item_id,
    resolve_pokemon_id,
)

logger = logging.getLogger(__name__)

# Pikalytics feed for the Pokemon Champions Showdown data we publish.
FEED_FORMAT_CODE = "gen9championsvgc2026regmc"
# Numeric list-API id suffix. Shared across Champions feeds; surfaced as a
# constant so a Pikalytics-side change is a one-line edit.
FEED_LIST_ID = "1760"


@dataclass(frozen=True)
class SeasonInfo:
    """Parsed season/regulation metadata from the Pikalytics AI endpoint."""

    name: str
    format_code: str
    data_date: str  # Public observation month, "YYYY-MM"
    api_data_date: Optional[str] = None  # Pikalytics' internal API partition

    @property
    def data_key(self) -> str:
        """List-API key; Pikalytics currently keeps M-C in a legacy bucket."""
        return f"{self.api_data_date or self.data_date}/{self.format_code}-{FEED_LIST_ID}"


def _clean_format_name(raw: str) -> str:
    """Strip Pikalytics product branding from the format name.

    Pikalytics labels this feed "Pokemon Champions VGC 2026 Reg M-C". Drop
    the product/year branding and keep the regulation identity.
    """
    name = raw.strip()
    name = re.sub(r"^Pokemon Champions\s+", "", name, flags=re.I)
    name = re.sub(r"^VGC\s*\d{4}\s*", "", name, flags=re.I)
    name = re.sub(r"\s*Ranked Battle Data\s*$", "", name, flags=re.I)
    # Normalize "Reg M-B" -> "Regulation Set M-B" for readability.
    name = re.sub(
        r"\bReg(?:ulation)?(?:\s+Set)?\s+([A-Za-z]-?[A-Za-z]?)\b",
        r"Regulation Set \1",
        name,
        flags=re.I,
    )
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name or "Regulation Set M-C"


def _season_slug(format_code: str) -> str:
    """Derive a stable season id slug from a format code.

    Examples: `battledataregmbs3` -> `regmb-s3` and
    `gen9championsvgc2026regmc` -> `regmc`.
    """
    m = re.match(r"battledatareg([a-z]+?)(s\d+)?$", format_code, re.I)
    if not m:
        m = re.match(
            r"gen\d+championsvgc\d+reg([a-z]+?)(s\d+)?$",
            format_code,
            re.I,
        )
    if not m:
        return format_code
    reg = m.group(1).lower()
    season = (m.group(2) or "").lower()
    return f"reg{reg}" + (f"-{season}" if season else "")


def _pct(raw) -> float:
    """Parse a Pikalytics percent value (string like '89.4' or number) to 0-1."""
    if raw is None:
        return 0.0
    try:
        return min(1.0, float(str(raw).replace("%", "").strip()) / 100)
    except (ValueError, TypeError):
        return 0.0


class PikalyticsScraper(BaseScraper):
    """Scraper for Pokemon Champions Showdown data (list API + AI markdown)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observed_data_date: Optional[str] = None

    @property
    def name(self) -> str:
        return "Pikalytics"

    @property
    def base_url(self) -> str:
        return "https://www.pikalytics.com"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokemon name using the name resolver."""
        return resolve_pokemon_id(name)

    # ------------------------------------------------------------------ season

    async def scrape_season(self) -> Optional[SeasonInfo]:
        """Parse season/regulation + data date from the AI markdown endpoint.

        The endpoint exposes a "## Format Information" block:
            - **Format**: Pokemon Champions VGC 2026 Reg M-C
            - **Format Code**: `gen9championsvgc2026regmc`
            - **Data Date**: 2026-05

        Pikalytics currently stores this continuously updated feed in its old
        2026-05 API partition. Keep that value for the request URL, but expose
        the current observation month publicly instead of mislabelling live
        September M-C data as a May snapshot.
        """
        url = f"{self.base_url}/ai/pokedex/{FEED_FORMAT_CODE}"
        markdown = await self._safe_fetch(url, "season info")
        if markdown is None:
            return None

        fmt = re.search(r"\*\*Format\*\*:\s*(.+)", markdown)
        code = re.search(r"\*\*Format Code\*\*:\s*`?([\w-]+)`?", markdown)
        date_match = re.search(
            r"\*\*Data Date\*\*:\s*(\d{4}-\d{2})", markdown
        )

        if not date_match:
            logger.warning("Could not parse Data Date from AI endpoint")
            return None

        api_data_date = date_match.group(1)
        observation_month = max(
            api_data_date, self._observed_data_date or api_data_date
        )
        return SeasonInfo(
            name=_clean_format_name(fmt.group(1)) if fmt else "Regulation Set M-C",
            format_code=code.group(1) if code else FEED_FORMAT_CODE,
            data_date=observation_month,
            api_data_date=api_data_date,
        )

    def season_info_to_model(self, info: Optional[SeasonInfo]) -> Optional[Season]:
        """Convert parsed SeasonInfo into the output Season model.

        Returns None when season info could not be determined, so callers can
        decide how to handle a missing season rather than emitting a fabricated
        "Season 1".
        """
        if info is None:
            return None

        start = None
        try:
            year, month = (int(x) for x in info.data_date.split("-"))
            start = date(year, month, 1)
        except (ValueError, TypeError):
            start = None

        return Season(
            id=_season_slug(info.format_code),
            name=info.name,
            format_code=info.format_code,
            data_date=info.data_date,
            start_date=start,
            end_date=None,
        )

    async def _get_current_data_key(self, season: Optional[SeasonInfo] = None) -> str:
        """Get the current list-API key for the M-C Showdown feed.

        Prefers already-parsed season info; otherwise re-parses the AI endpoint.
        Crucially, does NOT fall back to the current wall-clock month: Pikalytics
        publishes monthly and the *current* month is frequently empty (returns
        []), which would otherwise wipe the published dataset.
        """
        if season is not None:
            return season.data_key

        parsed = await self.scrape_season()
        if parsed is not None:
            return parsed.data_key

        raise ParseError(
            "Could not determine Pikalytics data date; refusing to guess the "
            "current month (it is frequently empty and would clobber good data)."
        )

    # ---------------------------------------------------------------- rankings

    async def scrape_rankings(self, limit: int = 200) -> list[PokemonUsage]:
        """Scrape rankings using Pikalytics' native usage percentage."""
        season = await self.scrape_season()
        data_key = await self._get_current_data_key(season)
        url = f"{self.base_url}/api/l/{data_key}"
        logger.info(f"Scraping rankings from {url}")

        response = await self._fetch(url)
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ParseError(f"Rankings response was not valid JSON: {e}") from e

        if not isinstance(data, list) or not data:
            raise ParseError(
                f"Rankings feed {data_key} returned no Pokemon "
                f"(len={len(data) if hasattr(data, '__len__') else 'n/a'}). "
                "Aborting rather than publishing an empty dataset."
            )

        # The upstream `Data Date` is a legacy storage partition, not the live
        # M-C observation month. Tournament timestamps embedded in the same
        # rows provide concrete freshness evidence without guessing from the
        # wall clock. The next scrape_season() call exposes the newest month.
        observed_months = [
            str(team.get("tournamentDate", ""))[:7]
            for row in data
            for team in row.get("teams", [])
            if re.match(r"^\d{4}-\d{2}", str(team.get("tournamentDate", "")))
        ]
        if observed_months:
            self._observed_data_date = max(observed_months)

        missing_usage = [
            row.get("name", "<unknown>")
            for row in data
            if row.get("percent") is None
        ]
        if missing_usage:
            raise ParseError(
                "M-C Showdown feed omitted native usage percentage for: "
                + ", ".join(missing_usage[:10])
            )

        grouped: dict[int, list[tuple[dict, PokemonUsage]]] = defaultdict(list)
        unresolved: list[str] = []
        for row in data:
            name = row.get("name", "")
            dex_id = self._get_dex_id(name)
            if dex_id <= 0:
                unresolved.append(name)
                continue
            grouped[dex_id].append(
                (
                    row,
                    PokemonUsage(
                        rank=0,
                        dex_id=dex_id,
                        name=name,
                        form=self._form_slug(name),
                        usage_rate=_pct(row.get("percent")),
                        win_rate=self._to_winrate(row.get("winrate")),
                        top_moves=self._parse_listapi_moves(row.get("moves", [])),
                        top_items=self._parse_listapi_items(row.get("items", [])),
                        top_abilities=self._parse_listapi_abilities(row.get("abilities", [])),
                        top_teammates=self._parse_listapi_teammates(
                            row.get("team", [])
                        ),
                    ),
                )
            )
        if unresolved:
            raise ParseError(
                "Unresolved Pikalytics Pokémon names: " + ", ".join(unresolved)
            )

        # Some cosmetic forms intentionally share one app asset. Aggregate
        # those source rows so overview and per-Pokemon files stay consistent.
        combined = [
            self._aggregate_asset_rows(dex_id, rows)
            for dex_id, rows in grouped.items()
        ]
        combined.sort(key=lambda pokemon: (-pokemon.usage_rate, pokemon.name))
        rankings = [
            pokemon.model_copy(update={"rank": position})
            for position, pokemon in enumerate(combined[:limit], start=1)
        ]

        logger.info(
            "Scraped %d asset-safe Pokemon from %d Pikalytics rows",
            len(rankings),
            len(data),
        )
        return rankings

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokemon using the AI markdown API."""
        url_name = name.replace(" ", "-")
        url = f"{self.base_url}/ai/pokedex/{FEED_FORMAT_CODE}/{url_name}"
        logger.info(f"Scraping details for {name} from {url}")

        markdown = await self._safe_fetch(url, f"details for {name}")
        if markdown is None:
            return None

        moves = self._parse_markdown_usage(
            markdown, "Common Moves", resolve_move_id, MoveUsage
        )
        items = self._parse_markdown_usage(
            markdown, "Common Items", resolve_item_id, ItemUsage
        )
        abilities = self._parse_markdown_usage(
            markdown, "Common Abilities", resolve_ability_id, AbilityUsage
        )

        teammates = self._parse_markdown_teammates(markdown)

        return PokemonUsage(
            rank=0,
            dex_id=self._get_dex_id(name),
            name=name,
            form=self._form_slug(name),
            usage_rate=0.0,
            top_moves=moves,
            top_items=items,
            top_abilities=abilities,
            top_teammates=teammates,
        )

    # ----------------------------------------------------------------- helpers

    async def _safe_fetch(self, url: str, what: str) -> Optional[str]:
        """Fetch a URL, returning None (and logging) on failure."""
        try:
            return await self._fetch(url)
        except Exception as exc:
            logger.warning("Could not fetch %s from %s: %s", what, url, exc)
            return None

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_winrate(value) -> Optional[float]:
        if value is None:
            return None
        try:
            wr = float(value)
        except (ValueError, TypeError):
            return None
        # winrate field is already 0-1 on this feed; clamp defensively.
        return min(1.0, max(0.0, wr))

    @classmethod
    def _row_games(cls, row: dict) -> int:
        """Best-effort game count for a list-API row (usage signal)."""
        for key in ("games", "raw_count", "raw"):
            val = row.get(key)
            if val is not None:
                n = cls._to_int(val, 0)
                if n > 0:
                    return n
        return 0

    @staticmethod
    def _canonical_name(names: list[str]) -> str:
        """Prefer an unsuffixed name for asset-equivalent cosmetic forms."""
        return min(names, key=lambda name: ("-" in name, len(name), name))

    @staticmethod
    def _weighted_entries(rows, field: str, total_weight: float):
        weighted: dict[int, float] = defaultdict(float)
        model_cls = None
        for raw_row, pokemon in rows:
            weight = PikalyticsScraper._row_games(raw_row) or 1
            for entry in getattr(pokemon, field):
                model_cls = type(entry)
                weighted[entry.id] += entry.usage * weight
        if model_cls is None or total_weight <= 0:
            return []
        return [
            model_cls(id=entry_id, usage=min(1.0, value / total_weight))
            for entry_id, value in sorted(
                weighted.items(), key=lambda item: item[1], reverse=True
            )
        ]

    def _aggregate_asset_rows(
        self, dex_id: int, rows: list[tuple[dict, PokemonUsage]]
    ) -> PokemonUsage:
        names = [pokemon.name for _, pokemon in rows]
        canonical_name = self._canonical_name(names)
        total_weight = sum(self._row_games(row) or 1 for row, _ in rows)
        weighted_winrate = sum(
            (pokemon.win_rate or 0.0) * (self._row_games(row) or 1)
            for row, pokemon in rows
            if pokemon.win_rate is not None
        )
        winrate_weight = sum(
            self._row_games(row) or 1
            for row, pokemon in rows
            if pokemon.win_rate is not None
        )
        return PokemonUsage(
            rank=0,
            dex_id=dex_id,
            name=canonical_name,
            form=self._form_slug(canonical_name),
            usage_rate=min(1.0, sum(pokemon.usage_rate for _, pokemon in rows)),
            win_rate=(weighted_winrate / winrate_weight if winrate_weight else None),
            top_moves=self._weighted_entries(rows, "top_moves", total_weight),
            top_items=self._weighted_entries(rows, "top_items", total_weight),
            top_abilities=self._weighted_entries(rows, "top_abilities", total_weight),
            top_teammates=self._weighted_entries(
                rows, "top_teammates", total_weight
            ),
        )

    @staticmethod
    def _form_slug(name: str) -> Optional[str]:
        """Extract a form slug from a Pikalytics name, or None for base forms.

        'Floette-Eternal' -> 'eternal', 'Rotom-Wash' -> 'wash',
        'Calyrex-Shadow-Rider' -> 'shadow-rider', 'Garchomp' -> None.
        """
        if "-" not in name:
            return None
        base, _, rest = name.partition("-")
        rest = rest.strip().lower()
        return rest or None

    def _parse_listapi_teammates(self, team: list) -> list[TeammateUsage]:
        out: list[TeammateUsage] = []
        for t in team:
            tname = t.get("pokemon", "")
            tid = self._to_int(t.get("id"), 0) or self._get_dex_id(tname)
            if tid > 0:
                out.append(TeammateUsage(id=tid, usage=_pct(t.get("percent"))))
        return out

    def _parse_listapi_moves(self, moves: list) -> list[MoveUsage]:
        out: list[MoveUsage] = []
        for m in moves:
            mid = resolve_move_id(m.get("move", ""))
            if mid > 0:
                out.append(MoveUsage(id=mid, usage=_pct(m.get("percent"))))
        return out

    def _parse_listapi_items(self, items: list) -> list[ItemUsage]:
        out: list[ItemUsage] = []
        for it in items:
            iid = resolve_item_id(it.get("item", ""))
            if iid > 0:
                out.append(ItemUsage(id=iid, usage=_pct(it.get("percent"))))
        return out

    def _parse_listapi_abilities(self, abilities: list) -> list[AbilityUsage]:
        out: list[AbilityUsage] = []
        for a in abilities:
            aid = resolve_ability_id(a.get("ability", ""))
            if aid > 0:
                out.append(AbilityUsage(id=aid, usage=_pct(a.get("percent"))))
        return out

    def _parse_markdown_usage(self, markdown, section_name, resolve_fn, model_cls):
        """Parse a '**Name**: NN%' markdown section into usage models."""
        out = []
        section = self._extract_section(markdown, section_name)
        if not section:
            return out
        for raw_name, pct in re.findall(r"\*\*([^*]+)\*\*:\s*([\d.]+)%", section):
            rid = resolve_fn(raw_name.strip())
            if rid > 0:
                out.append(model_cls(id=rid, usage=min(1.0, float(pct) / 100)))
        return out

    def _parse_markdown_teammates(self, markdown: str) -> list[TeammateUsage]:
        """Parse the 'Common Teammates' section.

        Accept both numeric and `undefined` percentages defensively. The M-C
        Showdown feed normally provides real percentages in both APIs.
        """
        out: list[TeammateUsage] = []
        section = self._extract_section(markdown, "Common Teammates")
        if not section:
            return out
        seen: set[int] = set()
        pattern = r"\*\*([^*]+)\*\*:\s*([\d.]+|undefined)%"
        for tname, pct in re.findall(pattern, section):
            tid = self._get_dex_id(tname.strip())
            if tid <= 0 or tid in seen:
                continue
            seen.add(tid)
            usage = 0.0 if pct == "undefined" else min(1.0, float(pct) / 100)
            out.append(TeammateUsage(id=tid, usage=usage))
        return out

    def _extract_section(self, markdown: str, section_name: str) -> Optional[str]:
        """Extract a section from markdown by header name."""
        pattern = rf"## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, markdown, re.DOTALL)
        return match.group(1) if match else None
