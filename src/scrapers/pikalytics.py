# src/scrapers/pikalytics.py
"""Pikalytics scraper for Pokemon Champions competitive data.

Source of truth: the Pokemon Champions **ranked-ladder** feed that Pikalytics
labels "Regulation Set M-B S3 Ranked Battle Data" (format code
`battledataregmbs3`). We use this feed rather than `championstournaments`
because it:
  * has larger, cleaner sample sizes (ladder-wide game counts),
  * does NOT split Mega forms into separate rows, which previously caused
    dex_id collisions (e.g. Floette-Eternal-Mega and Floette-Eternal both
    collapsing onto one id), and
  * exposes richer detail (EV spreads + natures are available in the feed for a
    future enhancement; not yet parsed here).

The ranked-ladder feed exposes usage as a raw game count (`games`) rather than
a pick-rate percentage, so `usage_rate` is derived as each Pokemon's share of
the total games in the snapshot (see `scrape_rankings`).
"""

import logging
import re
import json
from dataclasses import dataclass
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

# Pikalytics feed for the Pokemon Champions ranked-ladder data we publish.
FEED_FORMAT_CODE = "battledataregmbs3"
# Numeric list-API id suffix. Shared across Champions feeds; surfaced as a
# constant so a Pikalytics-side change is a one-line edit.
FEED_LIST_ID = "1760"


@dataclass(frozen=True)
class SeasonInfo:
    """Parsed season/regulation metadata from the Pikalytics AI endpoint."""

    name: str
    format_code: str
    data_date: str  # "YYYY-MM"

    @property
    def data_key(self) -> str:
        """List-API data key, e.g. '2026-05/battledataregmbs3-1760'."""
        return f"{self.data_date}/{self.format_code}-{FEED_LIST_ID}"


def _clean_format_name(raw: str) -> str:
    """Strip Pikalytics product branding from the format name.

    Pikalytics labels this feed "Pokemon Champions VGC 2026 Reg M-B S3 Ranked
    Battle Data". Per product decision we drop the "Pokemon Champions VGC 2026"
    branding and keep the regulation/season identity, e.g. "Regulation Set M-B
    S3".
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
    return name or "Regulation Set M-B S3"


def _season_slug(format_code: str) -> str:
    """Derive a stable season id slug from a format code.

    'battledataregmbs3' -> 'regmb-s3'. Falls back to the raw code.
    """
    m = re.match(r"battledatareg([a-z]+?)(s\d+)?$", format_code, re.I)
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
    """Scraper for Pokemon Champions ranked-ladder data (list API + AI markdown)."""

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
            - **Format**: Pokemon Champions VGC 2026 Reg M-B S3 Ranked Battle Data
            - **Format Code**: `battledataregmbs3`
            - **Data Date**: 2026-05
        """
        url = f"{self.base_url}/ai/pokedex/{FEED_FORMAT_CODE}"
        markdown = await self._safe_fetch(url, "season info")
        if markdown is None:
            return None

        fmt = re.search(r"\*\*Format\*\*:\s*(.+)", markdown)
        code = re.search(r"\*\*Format Code\*\*:\s*`?([\w-]+)`?", markdown)
        date = re.search(r"\*\*Data Date\*\*:\s*(\d{4}-\d{2})", markdown)

        if not date:
            logger.warning("Could not parse Data Date from AI endpoint")
            return None

        return SeasonInfo(
            name=_clean_format_name(fmt.group(1)) if fmt else "Regulation Set M-B S3",
            format_code=code.group(1) if code else FEED_FORMAT_CODE,
            data_date=date.group(1),
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
            from datetime import date as _date

            year, month = (int(x) for x in info.data_date.split("-"))
            start = _date(year, month, 1)
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
        """Get the current list-API data key, e.g. '2026-05/battledataregmbs3-1760'.

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
        """Scrape Pokemon rankings from the ranked-ladder list API.

        The ranked-ladder feed reports usage as a raw game count, not a percent,
        so we derive `usage_rate` as each Pokemon's share of total games in the
        snapshot. The list response also embeds full detail (moves/items/etc.)
        for top-ranked Pokemon; we parse that inline when present and let the
        per-Pokemon detail pass fill in the long tail.
        """
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

        # Total games across the *full* feed (not just the limited slice) so the
        # derived usage_rate is stable regardless of --limit.
        total_games = sum(self._row_games(row) for row in data) or 1

        # Pikalytics' own `rank` on this feed is an opaque ladder-popularity
        # metric that is NOT monotonic with the per-Pokemon game count we expose
        # as usage_rate. Downstream consumers expect rank == ordinal(usage_rate)
        # (strictly descending), so we sort by games and re-assign rank here to
        # keep that invariant. Ties broken by win rate then name for determinism.
        ranked_rows = sorted(
            data,
            key=lambda r: (
                self._row_games(r),
                self._to_winrate(r.get("winrate")) or 0.0,
                r.get("name", ""),
            ),
            reverse=True,
        )[:limit]

        rankings: list[PokemonUsage] = []
        for position, row in enumerate(ranked_rows, start=1):
            name = row.get("name", "")
            games = self._row_games(row)
            usage_rate = min(1.0, games / total_games)
            dex_id = self._get_dex_id(name)

            teammates = self._parse_listapi_teammates(row.get("team", []))

            rankings.append(
                PokemonUsage(
                    rank=position,
                    dex_id=dex_id,
                    name=name,
                    form=self._form_slug(name),
                    usage_rate=usage_rate,
                    win_rate=self._to_winrate(row.get("winrate")),
                    top_moves=self._parse_listapi_moves(row.get("moves", [])),
                    top_items=self._parse_listapi_items(row.get("items", [])),
                    top_abilities=self._parse_listapi_abilities(row.get("abilities", [])),
                    top_teammates=teammates,
                )
            )

        logger.info(f"Scraped {len(rankings)} Pokemon from rankings")
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

        On the ranked-ladder feed the AI markdown often reports teammate usage
        as 'undefined%' (the real percentages live in the list API). We still
        want the teammate set + ordering, so we accept both numeric and
        'undefined' percentages, defaulting the latter to usage=0.0 while
        preserving the source order (most common first).
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
