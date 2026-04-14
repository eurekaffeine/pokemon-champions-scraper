# src/scrapers/base.py
"""Base scraper class with retry logic, rate limiting, and common utilities."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.models.schema import PokemonUsage, BattleMeta

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Base exception for scraper errors."""
    pass


class RateLimitError(ScraperError):
    """Raised when rate limited by the source."""
    pass


class ParseError(ScraperError):
    """Raised when HTML parsing fails."""
    pass


class BaseScraper(ABC):
    """Abstract base class for scrapers with common functionality."""

    def __init__(
        self,
        user_agent: str = "PocketGallery-Scraper/1.0",
        request_delay_ms: int = 1000,
        max_retries: int = 3,
        timeout_seconds: int = 30,
    ):
        self.user_agent = user_agent
        self.request_delay_ms = request_delay_ms
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._last_request_time: float = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the data source."""
        pass

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Base URL for the data source."""
        pass

    @abstractmethod
    async def scrape_rankings(self, limit: int = 50) -> list[PokemonUsage]:
        """Scrape the main rankings page for top Pokémon."""
        pass

    @abstractmethod
    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon."""
        pass

    async def scrape(self, limit: int = 50, include_details: bool = True) -> list[PokemonUsage]:
        """
        Full scrape: rankings + optional per-Pokémon details.
        
        Args:
            limit: Maximum number of Pokémon to scrape
            include_details: If True, also scrape per-Pokémon detail pages
        
        Returns:
            List of PokemonUsage with full data
        """
        # Get initial rankings
        rankings = await self.scrape_rankings(limit=limit)
        
        if not include_details:
            return rankings
        
        # Enrich with details
        enriched = []
        for pokemon in rankings:
            try:
                detail = await self.scrape_pokemon_detail(pokemon.name)
                if detail:
                    # Merge detail into ranking data
                    enriched.append(self._merge_pokemon_data(pokemon, detail))
                else:
                    enriched.append(pokemon)
            except Exception as e:
                logger.warning(f"Failed to scrape details for {pokemon.name}: {e}")
                enriched.append(pokemon)
        
        return enriched

    def _merge_pokemon_data(self, base: PokemonUsage, detail: PokemonUsage) -> PokemonUsage:
        """Merge detail data into base ranking data."""
        return PokemonUsage(
            rank=base.rank,
            dex_id=base.dex_id or detail.dex_id,
            name=base.name,
            form=base.form or detail.form,
            usage_rate=base.usage_rate,
            win_rate=detail.win_rate or base.win_rate,
            top_moves=detail.top_moves or base.top_moves,
            top_items=detail.top_items or base.top_items,
            top_abilities=detail.top_abilities or base.top_abilities,
            top_teammates=detail.top_teammates or base.top_teammates,
            top_tera_types=detail.top_tera_types or base.top_tera_types,
            top_spreads=detail.top_spreads or base.top_spreads,
        )

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = (now - self._last_request_time) * 1000  # Convert to ms
        if elapsed < self.request_delay_ms:
            delay = (self.request_delay_ms - elapsed) / 1000
            # Add jitter to avoid thundering herd
            jitter = random.uniform(0.1, 0.3)
            await asyncio.sleep(delay + jitter)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _fetch(self, url: str, retry_count: int = 0) -> str:
        """
        Fetch a URL with retry logic and rate limiting.
        
        Args:
            url: URL to fetch
            retry_count: Current retry attempt
        
        Returns:
            Response body as string
        
        Raises:
            ScraperError: If all retries fail
        """
        await self._rate_limit()
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                headers = {
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }
                response = await client.get(url, headers=headers)
                
                if response.status_code == 429:
                    raise RateLimitError(f"Rate limited by {url}")
                
                response.raise_for_status()
                return response.text
                
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching {url} (attempt {retry_count + 1})")
            if retry_count < self.max_retries:
                # Exponential backoff
                backoff = (2 ** retry_count) + random.uniform(0, 1)
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            raise ScraperError(f"Failed to fetch {url} after {self.max_retries} retries") from e
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error {e.response.status_code} fetching {url}")
            if retry_count < self.max_retries and e.response.status_code >= 500:
                backoff = (2 ** retry_count) + random.uniform(0, 1)
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            raise ScraperError(f"HTTP {e.response.status_code} from {url}") from e
            
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            if retry_count < self.max_retries:
                backoff = (2 ** retry_count) + random.uniform(0, 1)
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            raise ScraperError(f"Failed to fetch {url}: {e}") from e

    def _parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML into BeautifulSoup."""
        return BeautifulSoup(html, "html.parser")

    def _parse_percentage(self, text: str) -> float:
        """Parse percentage string to float (0-1)."""
        if not text:
            return 0.0
        # Remove % sign and whitespace
        cleaned = text.replace("%", "").strip()
        try:
            return float(cleaned) / 100
        except ValueError:
            return 0.0

    def _normalize_pokemon_name(self, name: str) -> str:
        """Normalize Pokémon name for URL/lookup (lowercase, no special chars)."""
        return name.lower().replace(" ", "-").replace("'", "").replace(".", "")
