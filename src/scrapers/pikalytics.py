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
from src.name_resolver import (
    resolve_move_id,
    resolve_ability_id,
    resolve_item_id,
    resolve_pokemon_id,
)

logger = logging.getLogger(__name__)


class PikalyticsScraper(BaseScraper):
    """Scraper for Pikalytics Pokémon Champions data using the AI markdown API."""

    @property
    def name(self) -> str:
        return "Pikalytics"

    @property
    def base_url(self) -> str:
        return "https://www.pikalytics.com"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name using the name resolver."""
        return resolve_pokemon_id(name)

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
                name_clean = name.strip()
                
                rankings.append(PokemonUsage(
                    rank=rank,
                    dex_id=self._get_dex_id(name_clean),
                    name=name_clean,
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
                for match in re.findall(move_pattern, moves_section):  # No limit - get all
                    move_name = match[0].strip()
                    move_id = resolve_move_id(move_name)
                    if move_id > 0:  # Only include if we can resolve the ID
                        moves.append(MoveUsage(
                            id=move_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Items section
            items_section = self._extract_section(markdown, "Common Items")
            if items_section:
                item_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(item_pattern, items_section):  # No limit - get all
                    item_name = match[0].strip()
                    item_id = resolve_item_id(item_name)
                    if item_id > 0:  # Only include if we can resolve the ID
                        items.append(ItemUsage(
                            id=item_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Abilities section
            abilities_section = self._extract_section(markdown, "Common Abilities")
            if abilities_section:
                ability_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(ability_pattern, abilities_section):  # No limit - get all
                    ability_name = match[0].strip()
                    ability_id = resolve_ability_id(ability_name)
                    if ability_id > 0:  # Only include if we can resolve the ID
                        abilities.append(AbilityUsage(
                            id=ability_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Teammates section
            teammates_section = self._extract_section(markdown, "Common Teammates")
            if teammates_section:
                teammate_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(teammate_pattern, teammates_section):  # No limit - get all
                    teammate_name = match[0].strip()
                    teammate_id = self._get_dex_id(teammate_name)
                    if teammate_id > 0:  # Only include if we can resolve the ID
                        teammates.append(TeammateUsage(
                            id=teammate_id,
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
