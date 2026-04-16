# src/scrapers/pikalytics.py
"""Pikalytics scraper for Pokémon Champions competitive data."""

import logging
import re
import json
from typing import Optional

from src.scrapers.base import BaseScraper, ParseError
from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
)
from src.name_resolver import (
    resolve_move_id,
    resolve_ability_id,
    resolve_item_id,
    resolve_pokemon_id,
)

logger = logging.getLogger(__name__)


class PikalyticsScraper(BaseScraper):
    """Scraper for Pikalytics Pokémon Champions data using list API + AI markdown."""

    @property
    def name(self) -> str:
        return "Pikalytics"

    @property
    def base_url(self) -> str:
        return "https://www.pikalytics.com"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name using the name resolver."""
        return resolve_pokemon_id(name)

    async def _get_current_data_key(self) -> str:
        """
        Get the current data key (e.g., '2026-03/championstournaments-1760').
        Extracts the data date from the AI markdown endpoint.
        """
        try:
            url = f"{self.base_url}/ai/pokedex/championstournaments"
            markdown = await self._fetch(url)
            
            # Look for "Data Date**: YYYY-MM" pattern
            match = re.search(r'Data Date\*\*:\s*(\d{4}-\d{2})', markdown)
            if match:
                data_date = match.group(1)
                return f"{data_date}/championstournaments-1760"
            
            logger.warning("Could not find data date in AI endpoint")
        except Exception as e:
            logger.warning(f"Could not fetch AI endpoint for data date: {e}")
        
        # Fallback: try common dates
        from datetime import datetime
        now = datetime.now()
        return f"{now.year}-{now.month:02d}/championstournaments-1760"

    async def scrape_rankings(self, limit: int = 200) -> list[PokemonUsage]:
        """
        Scrape Pokémon rankings from the list API.
        Returns all Pokémon with basic info (rank, name, usage).
        Details are populated via scrape_pokemon_detail.
        """
        data_key = await self._get_current_data_key()
        url = f"{self.base_url}/api/l/{data_key}"
        logger.info(f"Scraping rankings from {url}")

        try:
            response = await self._fetch(url)
            data = json.loads(response)
            
            rankings = []
            for pokemon_data in data[:limit]:
                name = pokemon_data.get("name", "")
                rank = int(pokemon_data.get("rank", 0))
                usage_rate = float(pokemon_data.get("percent", 0)) / 100
                dex_id = self._get_dex_id(name)
                
                # Parse teammates from list API (always available)
                teammates = []
                for team_data in pokemon_data.get("team", []):
                    teammate_name = team_data.get("pokemon", "")
                    teammate_id = team_data.get("id", 0) or self._get_dex_id(teammate_name)
                    if teammate_id > 0:
                        teammates.append(TeammateUsage(
                            id=teammate_id,
                            usage=float(team_data.get("percent", 0)) / 100,
                        ))
                
                rankings.append(PokemonUsage(
                    rank=rank,
                    dex_id=dex_id,
                    name=name,
                    usage_rate=usage_rate,
                    top_teammates=teammates,
                ))
            
            logger.info(f"Scraped {len(rankings)} Pokémon from rankings")
            return rankings

        except Exception as e:
            logger.error(f"Failed to scrape rankings: {e}")
            raise ParseError(f"Failed to parse rankings from API: {e}") from e

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon using AI markdown API."""
        url_name = name.replace(" ", "-")
        url = f"{self.base_url}/ai/pokedex/championstournaments/{url_name}"
        logger.info(f"Scraping details for {name} from {url}")

        try:
            markdown = await self._fetch(url)

            moves = []
            items = []
            abilities = []
            teammates = []

            # Parse Common Moves section (get all)
            moves_section = self._extract_section(markdown, "Common Moves")
            if moves_section:
                move_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(move_pattern, moves_section):
                    move_name = match[0].strip()
                    move_id = resolve_move_id(move_name)
                    if move_id > 0:
                        moves.append(MoveUsage(
                            id=move_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Items section (get all)
            items_section = self._extract_section(markdown, "Common Items")
            if items_section:
                item_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(item_pattern, items_section):
                    item_name = match[0].strip()
                    item_id = resolve_item_id(item_name)
                    if item_id > 0:
                        items.append(ItemUsage(
                            id=item_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Abilities section (get all)
            abilities_section = self._extract_section(markdown, "Common Abilities")
            if abilities_section:
                ability_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(ability_pattern, abilities_section):
                    ability_name = match[0].strip()
                    ability_id = resolve_ability_id(ability_name)
                    if ability_id > 0:
                        abilities.append(AbilityUsage(
                            id=ability_id,
                            usage=float(match[1]) / 100,
                        ))

            # Parse Common Teammates section (get all)
            teammates_section = self._extract_section(markdown, "Common Teammates")
            if teammates_section:
                teammate_pattern = r'\*\*([^*]+)\*\*:\s*([\d.]+)%'
                for match in re.findall(teammate_pattern, teammates_section):
                    teammate_name = match[0].strip()
                    teammate_id = self._get_dex_id(teammate_name)
                    if teammate_id > 0:
                        teammates.append(TeammateUsage(
                            id=teammate_id,
                            usage=float(match[1]) / 100,
                        ))

            return PokemonUsage(
                rank=0,
                dex_id=self._get_dex_id(name),
                name=name,
                usage_rate=0.0,
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
        pattern = rf'## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)'
        match = re.search(pattern, markdown, re.DOTALL)
        return match.group(1) if match else None
