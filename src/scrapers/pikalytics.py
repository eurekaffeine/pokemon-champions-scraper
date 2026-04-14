# src/scrapers/pikalytics.py
"""Pikalytics scraper for Pokémon Champions competitive data."""

import logging
import re
from typing import Optional
from datetime import datetime

from src.scrapers.base import BaseScraper, ParseError
from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
    TeraTypeUsage,
    EVSpread,
)

logger = logging.getLogger(__name__)

# Mapping of Pokémon names to National Dex IDs (partial, expand as needed)
POKEMON_DEX_IDS = {
    "bulbasaur": 1, "ivysaur": 2, "venusaur": 3, "charmander": 4, "charmeleon": 5,
    "charizard": 6, "squirtle": 7, "wartortle": 8, "blastoise": 9, "pikachu": 25,
    "raichu": 26, "mewtwo": 150, "mew": 151, "chikorita": 152, "cyndaquil": 155,
    "totodile": 158, "tyranitar": 248, "lugia": 249, "ho-oh": 250,
    "treecko": 252, "torchic": 255, "mudkip": 258, "gardevoir": 282,
    "salamence": 373, "metagross": 376, "latias": 380, "latios": 381,
    "kyogre": 382, "groudon": 383, "rayquaza": 384,
    "turtwig": 387, "chimchar": 390, "piplup": 393, "garchomp": 445,
    "lucario": 448, "abomasnow": 460, "dialga": 483, "palkia": 484, "giratina": 487,
    "snivy": 495, "tepig": 498, "oshawott": 501, "amoonguss": 591,
    "landorus": 645, "kyurem": 646,
    "chespin": 650, "fennekin": 653, "froakie": 656, "greninja": 658,
    "aegislash": 681,
    "rowlet": 722, "litten": 725, "popplio": 728, "mimikyu": 778,
    "grookey": 810, "scorbunny": 813, "sobble": 816, "rillaboom": 812,
    "cinderace": 815, "inteleon": 818, "urshifu": 892, "calyrex": 898,
    "flutter-mane": 987, "iron-hands": 992, "gholdengo": 1000,
    "miraidon": 1008, "koraidon": 1007,
    # Add more as needed - in production, use a complete dex mapping file
}


class PikalyticsScraper(BaseScraper):
    """Scraper for Pikalytics Pokémon Champions data."""

    @property
    def name(self) -> str:
        return "Pikalytics"

    @property
    def base_url(self) -> str:
        return "https://pikalytics.com"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name."""
        normalized = self._normalize_pokemon_name(name)
        return POKEMON_DEX_IDS.get(normalized, 0)

    async def scrape_rankings(self, limit: int = 50) -> list[PokemonUsage]:
        """Scrape main Champions rankings page."""
        url = f"{self.base_url}/pokedex/champions"
        logger.info(f"Scraping rankings from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)
            
            rankings = []
            rank = 1
            
            # Pikalytics uses a pokemon list with usage percentages
            # Look for common patterns in their HTML structure
            pokemon_entries = soup.select(".pokemon-entry, .pokedex-pokemon, [data-pokemon], .pokemon-row")
            
            if not pokemon_entries:
                # Fallback: try table rows
                pokemon_entries = soup.select("table tr[data-pokemon], .usage-pokemon")
            
            if not pokemon_entries:
                # Another fallback: look for any links to pokemon pages
                pokemon_links = soup.select("a[href*='/pokedex/champions/']")
                for link in pokemon_links[:limit]:
                    href = link.get("href", "")
                    match = re.search(r"/pokedex/champions/([^/]+)", href)
                    if match:
                        name = match.group(1).replace("-", " ").title()
                        # Try to extract usage from nearby text
                        parent = link.find_parent()
                        usage_text = parent.get_text() if parent else ""
                        usage_match = re.search(r"([\d.]+)\s*%", usage_text)
                        usage_rate = float(usage_match.group(1)) / 100 if usage_match else 0.0
                        
                        rankings.append(PokemonUsage(
                            rank=rank,
                            dex_id=self._get_dex_id(name),
                            name=name,
                            usage_rate=usage_rate,
                        ))
                        rank += 1
                        
                        if rank > limit:
                            break
            else:
                for entry in pokemon_entries[:limit]:
                    try:
                        # Extract name
                        name_elem = entry.select_one(".pokemon-name, .name, [data-name]")
                        if name_elem:
                            name = name_elem.get_text(strip=True)
                        else:
                            name = entry.get("data-pokemon", entry.get_text(strip=True).split()[0])
                        
                        # Extract usage rate
                        usage_elem = entry.select_one(".usage, .percentage, [data-usage]")
                        if usage_elem:
                            usage_rate = self._parse_percentage(usage_elem.get_text())
                        else:
                            usage_rate = 0.0
                        
                        if name:
                            rankings.append(PokemonUsage(
                                rank=rank,
                                dex_id=self._get_dex_id(name),
                                name=name.title(),
                                usage_rate=usage_rate,
                            ))
                            rank += 1
                    except Exception as e:
                        logger.warning(f"Failed to parse entry: {e}")
                        continue

            logger.info(f"Scraped {len(rankings)} Pokémon from rankings")
            return rankings

        except Exception as e:
            logger.error(f"Failed to scrape rankings: {e}")
            raise ParseError(f"Failed to parse rankings page: {e}") from e

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon."""
        normalized_name = self._normalize_pokemon_name(name)
        url = f"{self.base_url}/pokedex/champions/{normalized_name}"
        logger.info(f"Scraping details for {name} from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)

            # Initialize data containers
            moves = []
            items = []
            abilities = []
            teammates = []
            tera_types = []
            spreads = []
            win_rate = None

            # Scrape moves section
            moves_section = soup.select_one(".moves-section, [data-section='moves'], #moves")
            if moves_section:
                move_rows = moves_section.select(".move-row, tr, .item")
                for row in move_rows[:4]:  # Top 4 moves
                    move_name = row.select_one(".move-name, .name, td:first-child")
                    move_usage = row.select_one(".usage, .percentage, td:last-child")
                    if move_name:
                        moves.append(MoveUsage(
                            name=move_name.get_text(strip=True),
                            usage=self._parse_percentage(move_usage.get_text() if move_usage else "0%"),
                        ))

            # Scrape items section
            items_section = soup.select_one(".items-section, [data-section='items'], #items")
            if items_section:
                item_rows = items_section.select(".item-row, tr, .item")
                for row in item_rows[:4]:
                    item_name = row.select_one(".item-name, .name, td:first-child")
                    item_usage = row.select_one(".usage, .percentage, td:last-child")
                    if item_name:
                        items.append(ItemUsage(
                            name=item_name.get_text(strip=True),
                            usage=self._parse_percentage(item_usage.get_text() if item_usage else "0%"),
                        ))

            # Scrape abilities section
            abilities_section = soup.select_one(".abilities-section, [data-section='abilities'], #abilities")
            if abilities_section:
                ability_rows = abilities_section.select(".ability-row, tr, .item")
                for row in ability_rows[:3]:
                    ability_name = row.select_one(".ability-name, .name, td:first-child")
                    ability_usage = row.select_one(".usage, .percentage, td:last-child")
                    if ability_name:
                        abilities.append(AbilityUsage(
                            name=ability_name.get_text(strip=True),
                            usage=self._parse_percentage(ability_usage.get_text() if ability_usage else "0%"),
                        ))

            # Scrape teammates section
            teammates_section = soup.select_one(".teammates-section, [data-section='teammates'], #teammates")
            if teammates_section:
                teammate_rows = teammates_section.select(".teammate-row, tr, .pokemon-entry, a[href*='pokedex']")
                for row in teammate_rows[:6]:
                    teammate_name_elem = row.select_one(".pokemon-name, .name") or row
                    teammate_name = teammate_name_elem.get_text(strip=True)
                    teammate_usage_elem = row.select_one(".usage, .percentage")
                    if teammate_name:
                        teammates.append(TeammateUsage(
                            dex_id=self._get_dex_id(teammate_name),
                            name=teammate_name.title(),
                            usage=self._parse_percentage(teammate_usage_elem.get_text() if teammate_usage_elem else "0%"),
                        ))

            # Scrape tera types section
            tera_section = soup.select_one(".tera-section, [data-section='tera'], #tera")
            if tera_section:
                tera_rows = tera_section.select(".tera-row, tr, .item")
                for row in tera_rows[:4]:
                    tera_type_elem = row.select_one(".type-name, .name, td:first-child")
                    tera_usage_elem = row.select_one(".usage, .percentage, td:last-child")
                    if tera_type_elem:
                        tera_types.append(TeraTypeUsage(
                            type=tera_type_elem.get_text(strip=True),
                            usage=self._parse_percentage(tera_usage_elem.get_text() if tera_usage_elem else "0%"),
                        ))

            # Scrape EV spreads section
            spreads_section = soup.select_one(".spreads-section, [data-section='spreads'], #spreads")
            if spreads_section:
                spread_rows = spreads_section.select(".spread-row, tr")
                for row in spread_rows[:4]:
                    nature_elem = row.select_one(".nature")
                    evs_elem = row.select_one(".evs, .spread")
                    usage_elem = row.select_one(".usage, .percentage")
                    if nature_elem and evs_elem:
                        spreads.append(EVSpread(
                            nature=nature_elem.get_text(strip=True),
                            evs=evs_elem.get_text(strip=True),
                            usage=self._parse_percentage(usage_elem.get_text() if usage_elem else "0%"),
                        ))

            # Try to get win rate
            win_rate_elem = soup.select_one(".win-rate, [data-winrate], .winrate")
            if win_rate_elem:
                win_rate = self._parse_percentage(win_rate_elem.get_text())

            return PokemonUsage(
                rank=0,  # Will be set from rankings
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=0.0,  # Will be set from rankings
                win_rate=win_rate,
                top_moves=moves,
                top_items=items,
                top_abilities=abilities,
                top_teammates=teammates,
                top_tera_types=tera_types,
                top_spreads=spreads,
            )

        except Exception as e:
            logger.warning(f"Failed to scrape details for {name}: {e}")
            return None
