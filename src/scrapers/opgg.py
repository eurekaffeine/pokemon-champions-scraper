# src/scrapers/opgg.py
"""OP.GG scraper for Pokémon Champions competitive data."""

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
)

logger = logging.getLogger(__name__)

# Reuse dex ID mapping (in production, use a shared module)
POKEMON_DEX_IDS = {
    "bulbasaur": 1, "ivysaur": 2, "venusaur": 3, "charmander": 4, "charmeleon": 5,
    "charizard": 6, "squirtle": 7, "wartortle": 8, "blastoise": 9, "pikachu": 25,
    "raichu": 26, "mewtwo": 150, "mew": 151, "tyranitar": 248,
    "gardevoir": 282, "salamence": 373, "metagross": 376,
    "garchomp": 445, "lucario": 448, "amoonguss": 591,
    "greninja": 658, "aegislash": 681, "mimikyu": 778,
    "rillaboom": 812, "cinderace": 815, "inteleon": 818,
    "urshifu": 892, "calyrex": 898,
    "flutter-mane": 987, "iron-hands": 992, "gholdengo": 1000,
    "miraidon": 1008, "koraidon": 1007,
}


class OPGGScraper(BaseScraper):
    """Scraper for OP.GG Pokémon Champions data."""

    @property
    def name(self) -> str:
        return "OP.GG"

    @property
    def base_url(self) -> str:
        return "https://op.gg/pokemon-champions"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name."""
        normalized = self._normalize_pokemon_name(name)
        return POKEMON_DEX_IDS.get(normalized, 0)

    async def scrape_rankings(self, limit: int = 50) -> list[PokemonUsage]:
        """Scrape OP.GG tier list / rankings page."""
        url = f"{self.base_url}/tier-list"
        logger.info(f"Scraping rankings from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)
            
            rankings = []
            rank = 1
            
            # OP.GG typically uses structured tier lists
            # Look for tier sections (S, A, B, C, D)
            tier_sections = soup.select(".tier-section, [data-tier], .tier-list-row")
            
            if tier_sections:
                for section in tier_sections:
                    tier = section.get("data-tier", "").upper()
                    pokemon_entries = section.select(".pokemon-item, .champion-item, [data-pokemon]")
                    
                    for entry in pokemon_entries:
                        if rank > limit:
                            break
                        
                        name_elem = entry.select_one(".name, .pokemon-name, img[alt]")
                        if name_elem:
                            name = name_elem.get_text(strip=True) or name_elem.get("alt", "")
                        else:
                            name = entry.get("data-pokemon", "")
                        
                        # Extract win rate if available
                        win_rate_elem = entry.select_one(".win-rate, .winrate, [data-winrate]")
                        win_rate = self._parse_percentage(win_rate_elem.get_text()) if win_rate_elem else None
                        
                        # Extract usage/pick rate
                        usage_elem = entry.select_one(".pick-rate, .usage-rate, [data-pickrate]")
                        usage_rate = self._parse_percentage(usage_elem.get_text()) if usage_elem else 0.0
                        
                        if name:
                            rankings.append(PokemonUsage(
                                rank=rank,
                                dex_id=self._get_dex_id(name),
                                name=name.title(),
                                usage_rate=usage_rate,
                                win_rate=win_rate,
                            ))
                            rank += 1
                    
                    if rank > limit:
                        break
            else:
                # Fallback: look for any pokemon links or entries
                pokemon_links = soup.select("a[href*='/pokemon-champions/'], .pokemon-card, .pokemon-row")
                
                for entry in pokemon_links[:limit]:
                    href = entry.get("href", "")
                    match = re.search(r"/pokemon-champions/([^/]+)", href)
                    if match:
                        name = match.group(1).replace("-", " ").title()
                    else:
                        name = entry.get_text(strip=True).split()[0] if entry.get_text(strip=True) else ""
                    
                    if name and len(name) > 1:
                        # Try to extract stats from surrounding elements
                        parent = entry.find_parent(class_=re.compile(r"row|item|card"))
                        win_rate = None
                        usage_rate = 0.0
                        
                        if parent:
                            wr_elem = parent.select_one(".win-rate, .winrate")
                            if wr_elem:
                                win_rate = self._parse_percentage(wr_elem.get_text())
                            
                            ur_elem = parent.select_one(".pick-rate, .usage")
                            if ur_elem:
                                usage_rate = self._parse_percentage(ur_elem.get_text())
                        
                        rankings.append(PokemonUsage(
                            rank=rank,
                            dex_id=self._get_dex_id(name),
                            name=name.title(),
                            usage_rate=usage_rate,
                            win_rate=win_rate,
                        ))
                        rank += 1

            logger.info(f"Scraped {len(rankings)} Pokémon from OP.GG")
            return rankings

        except Exception as e:
            logger.error(f"Failed to scrape OP.GG rankings: {e}")
            raise ParseError(f"Failed to parse OP.GG page: {e}") from e

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon from OP.GG."""
        normalized_name = self._normalize_pokemon_name(name)
        url = f"{self.base_url}/pokedex/{normalized_name}"
        logger.info(f"Scraping OP.GG details for {name} from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)

            moves = []
            items = []
            abilities = []
            win_rate = None

            # Scrape recommended builds section
            builds_section = soup.select_one(".builds-section, .recommended-builds, #builds")
            if builds_section:
                # Moves
                move_elems = builds_section.select(".move-slot, .skill-slot")
                for elem in move_elems[:4]:
                    move_name = elem.get_text(strip=True)
                    if move_name:
                        moves.append(MoveUsage(name=move_name, usage=0.0))

                # Items
                item_elems = builds_section.select(".item-slot, .held-item")
                for elem in item_elems[:4]:
                    item_name = elem.get_text(strip=True) or elem.select_one("img").get("alt", "") if elem.select_one("img") else ""
                    if item_name:
                        items.append(ItemUsage(name=item_name, usage=0.0))

            # Win rate
            wr_elem = soup.select_one(".win-rate, .winrate-value, [data-stat='winrate']")
            if wr_elem:
                win_rate = self._parse_percentage(wr_elem.get_text())

            # Abilities
            ability_section = soup.select_one(".abilities-section, .ability-list")
            if ability_section:
                ability_elems = ability_section.select(".ability-item, .ability")
                for elem in ability_elems[:3]:
                    ability_name = elem.get_text(strip=True)
                    usage_elem = elem.select_one(".usage, .percentage")
                    usage = self._parse_percentage(usage_elem.get_text()) if usage_elem else 0.0
                    if ability_name:
                        abilities.append(AbilityUsage(name=ability_name, usage=usage))

            return PokemonUsage(
                rank=0,
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=0.0,
                win_rate=win_rate,
                top_moves=moves,
                top_items=items,
                top_abilities=abilities,
            )

        except Exception as e:
            logger.warning(f"Failed to scrape OP.GG details for {name}: {e}")
            return None

    async def scrape_tier_list(self) -> dict[str, list[int]]:
        """
        Scrape tier list categorization from OP.GG.
        
        Returns:
            Dict mapping tier (S, A, B, C, D) to list of dex IDs
        """
        url = f"{self.base_url}/tier-list"
        logger.info(f"Scraping tier list from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)
            
            tier_list = {"S": [], "A": [], "B": [], "C": [], "D": []}
            
            # Look for tier sections
            for tier in tier_list.keys():
                section = soup.select_one(f"[data-tier='{tier}'], .tier-{tier.lower()}, #{tier.lower()}-tier")
                if section:
                    pokemon_entries = section.select(".pokemon-item, .champion-item, [data-pokemon]")
                    for entry in pokemon_entries:
                        name_elem = entry.select_one(".name, img[alt]")
                        if name_elem:
                            name = name_elem.get_text(strip=True) or name_elem.get("alt", "")
                            dex_id = self._get_dex_id(name)
                            if dex_id > 0:
                                tier_list[tier].append(dex_id)
            
            return tier_list

        except Exception as e:
            logger.warning(f"Failed to scrape tier list: {e}")
            return {"S": [], "A": [], "B": [], "C": [], "D": []}
