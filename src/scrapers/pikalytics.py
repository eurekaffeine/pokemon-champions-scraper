# src/scrapers/pikalytics.py
"""Pikalytics scraper for Pokémon Champions competitive data using their AI API."""

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

# Complete dex ID mapping (extend as needed)
POKEMON_DEX_IDS = {
    "bulbasaur": 1, "ivysaur": 2, "venusaur": 3, "charmander": 4, "charmeleon": 5,
    "charizard": 6, "squirtle": 7, "wartortle": 8, "blastoise": 9, "caterpie": 10,
    "pikachu": 25, "raichu": 26, "clefable": 35, "ninetales": 38, "ninetales-alola": 38,
    "gengar": 94, "starmie": 121, "gyarados": 130, "aerodactyl": 142,
    "dragonite": 149, "mewtwo": 150, "mew": 151,
    "meganium": 154, "typhlosion": 157, "typhlosion-hisui": 157,
    "politoed": 186, "kingambit": 983, "sneasler": 903,
    "tyranitar": 248, "pelipper": 279, "gardevoir": 282, "maushold": 925,
    "torkoal": 324, "milotic": 350, "salamence": 373, "metagross": 376,
    "garchomp": 445, "lucario": 448, "rotom-wash": 479, "rotom-heat": 479,
    "excadrill": 530, "whimsicott": 547, "basculegion": 902, "amoonguss": 591,
    "volcarona": 637, "hydreigon": 635, "kangaskhan": 115,
    "greninja": 658, "talonflame": 663, "aegislash": 681, "sylveon": 700,
    "dragapult": 887, "incineroar": 727, "primarina": 730, "mimikyu": 778,
    "kommo-o": 784, "palafin": 964, "farigiraf": 981, "corviknight": 823,
    "sinistcha": 1013, "archaludon": 1018, "froslass": 478, "scizor": 212,
    "floette": 670, "delphox": 655, "glimmora": 970, "arcanine-hisui": 59,
    "orthworm": 968, "scovillain": 952, "golurk": 623,
    "rillaboom": 812, "cinderace": 815, "inteleon": 818,
    "urshifu": 892, "calyrex": 898,
}


class PikalyticsScraper(BaseScraper):
    """Scraper for Pikalytics Pokémon Champions data using the AI markdown API."""

    @property
    def name(self) -> str:
        return "Pikalytics"

    @property
    def base_url(self) -> str:
        return "https://www.pikalytics.com"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name."""
        normalized = self._normalize_pokemon_name(name)
        return POKEMON_DEX_IDS.get(normalized, 0)

    async def scrape_rankings(self, limit: int = 50) -> list[PokemonUsage]:
        """Scrape main Champions rankings page using AI markdown API."""
        url = f"{self.base_url}/ai/pokedex/championstournaments"
        logger.info(f"Scraping rankings from {url}")

        try:
            markdown = await self._fetch(url)
            rankings = []
            
            # Parse the markdown table
            # Format: | Rank | Pokemon | Usage % | Web Page | AI Data |
            # Example: | 1 | **Incineroar** | 55.57% | [View](...) | [AI](...) |
            
            table_pattern = r'\|\s*(\d+)\s*\|\s*\*\*([^*]+)\*\*\s*\|\s*([\d.]+)%'
            matches = re.findall(table_pattern, markdown)
            
            for rank_str, name, usage_str in matches[:limit]:
                rank = int(rank_str)
                usage_rate = float(usage_str) / 100
                
                rankings.append(PokemonUsage(
                    rank=rank,
                    dex_id=self._get_dex_id(name),
                    name=name.strip(),
                    usage_rate=usage_rate,
                ))
            
            logger.info(f"Scraped {len(rankings)} Pokémon from rankings")
            return rankings

        except Exception as e:
            logger.error(f"Failed to scrape rankings: {e}")
            raise ParseError(f"Failed to parse rankings page: {e}") from e

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon using AI markdown API."""
        # Handle special name formats
        url_name = name.replace(" ", "-")
        url = f"{self.base_url}/ai/pokedex/championstournaments/{url_name}"
        logger.info(f"Scraping details for {name} from {url}")

        try:
            markdown = await self._fetch(url)

            moves = []
            items = []
            abilities = []
            teammates = []

            # Parse Common Moves section
            # Format: - **Move Name**: 98.915%
            moves_section = self._extract_section(markdown, "Common Moves")
            if moves_section:
                move_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(move_pattern, moves_section)[:10]:
                    moves.append(MoveUsage(
                        name=match[0].strip(),
                        usage=float(match[1]) / 100,
                    ))

            # Parse Common Items section
            items_section = self._extract_section(markdown, "Common Items")
            if items_section:
                item_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(item_pattern, items_section)[:10]:
                    items.append(ItemUsage(
                        name=match[0].strip(),
                        usage=float(match[1]) / 100,
                    ))

            # Parse Common Abilities section
            abilities_section = self._extract_section(markdown, "Common Abilities")
            if abilities_section:
                ability_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(ability_pattern, abilities_section)[:5]:
                    abilities.append(AbilityUsage(
                        name=match[0].strip(),
                        usage=float(match[1]) / 100,
                    ))

            # Parse Common Teammates section
            teammates_section = self._extract_section(markdown, "Common Teammates")
            if teammates_section:
                teammate_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(teammate_pattern, teammates_section)[:6]:
                    teammate_name = match[0].strip()
                    teammates.append(TeammateUsage(
                        dex_id=self._get_dex_id(teammate_name),
                        name=teammate_name,
                        usage=float(match[1]) / 100,
                    ))

            return PokemonUsage(
                rank=0,  # Will be set from rankings
                dex_id=self._get_dex_id(name),
                name=name,
                usage_rate=0.0,  # Will be set from rankings
                top_moves=moves,
                top_items=items,
                top_abilities=abilities,
                top_teammates=teammates,
            )

        except Exception as e:
            logger.warning(f"Failed to scrape details for {name}: {e}")
            return None

    def _extract_section(self, markdown: str, section_name: str) -> Optional[str]:
        """Extract a section from markdown by header name."""
        # Match ## Section Name followed by content until next ## or end
        pattern = rf'## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)'
        match = re.search(pattern, markdown, re.DOTALL)
        return match.group(1) if match else None
