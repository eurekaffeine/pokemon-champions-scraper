# src/scrapers/base.py
"""Base scraper class with retry logic, rate limiting, circuit breaker, and common utilities."""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models.schema import PokemonUsage

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


class CircuitBreakerOpenError(ScraperError):
    """Raised when circuit breaker is open due to repeated failures."""
    pass


@dataclass
class CircuitBreakerState:
    """State for circuit breaker pattern."""
    failures: int = 0
    last_failure_time: float = 0.0
    state: str = "closed"  # "closed", "open", "half-open"
    
    # Configuration
    failure_threshold: int = 5  # Open circuit after this many failures
    reset_timeout_seconds: float = 60.0  # Try again after this time
    half_open_max_requests: int = 1  # Requests allowed in half-open state
    half_open_requests: int = 0


@dataclass
class ScrapeStats:
    """Statistics for a scrape operation."""
    requests_made: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    total_time_ms: float = 0.0
    pokemon_scraped: int = 0
    pokemon_failed: int = 0
    errors: list[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.requests_made == 0:
            return 0.0
        return self.requests_succeeded / self.requests_made
    
    def to_dict(self) -> dict:
        return {
            "requests_made": self.requests_made,
            "requests_succeeded": self.requests_succeeded,
            "requests_failed": self.requests_failed,
            "total_time_ms": round(self.total_time_ms, 2),
            "success_rate": round(self.success_rate * 100, 1),
            "pokemon_scraped": self.pokemon_scraped,
            "pokemon_failed": self.pokemon_failed,
            "errors": self.errors[:10],  # Limit to first 10 errors
        }


class BaseScraper(ABC):
    """Abstract base class for scrapers with common functionality."""

    def __init__(
        self,
        user_agent: str = "PocketGallery-Scraper/1.0",
        request_delay_ms: int = 1000,
        max_retries: int = 3,
        timeout_seconds: int = 30,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
    ):
        self.user_agent = user_agent
        self.request_delay_ms = request_delay_ms
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._last_request_time: float = 0
        
        # Circuit breaker
        self._circuit_breaker = CircuitBreakerState(
            failure_threshold=circuit_breaker_threshold,
            reset_timeout_seconds=circuit_breaker_timeout,
        )
        
        # Statistics
        self._stats = ScrapeStats()

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

    def reset_stats(self):
        """Reset scrape statistics."""
        self._stats = ScrapeStats()

    def get_stats(self) -> ScrapeStats:
        """Get current scrape statistics."""
        return self._stats

    def reset_circuit_breaker(self):
        """Reset circuit breaker to closed state."""
        self._circuit_breaker = CircuitBreakerState(
            failure_threshold=self._circuit_breaker.failure_threshold,
            reset_timeout_seconds=self._circuit_breaker.reset_timeout_seconds,
        )

    async def scrape(self, limit: int = 50, include_details: bool = True) -> list[PokemonUsage]:
        """
        Full scrape: rankings + optional per-Pokémon details.
        
        Args:
            limit: Maximum number of Pokémon to scrape
            include_details: If True, also scrape per-Pokémon detail pages
        
        Returns:
            List of PokemonUsage with full data
        """
        start_time = time.time()
        self.reset_stats()
        
        try:
            # Get initial rankings
            rankings = await self.scrape_rankings(limit=limit)
            self._stats.pokemon_scraped = len(rankings)
            
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
                except CircuitBreakerOpenError:
                    logger.warning(f"Circuit breaker open, skipping details for remaining Pokémon")
                    enriched.extend(rankings[len(enriched):])
                    break
                except Exception as e:
                    logger.warning(f"Failed to scrape details for {pokemon.name}: {e}")
                    self._stats.pokemon_failed += 1
                    self._stats.errors.append(f"{pokemon.name}: {str(e)[:100]}")
                    enriched.append(pokemon)
            
            return enriched
            
        finally:
            self._stats.total_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Scrape completed: {self._stats.pokemon_scraped} scraped, "
                f"{self._stats.pokemon_failed} failed, "
                f"{self._stats.total_time_ms:.0f}ms total"
            )

    @staticmethod
    def _merge_teammates(base_mates, detail_mates):
        """Union teammate lists, preferring the entry with real (non-zero) usage.

        Different feeds populate teammates differently: a list API may give real
        percentages for only the top mon, while the per-Pokemon markdown gives
        the full set but sometimes with usage=0. Union by id, keep the max usage
        seen, and preserve a stable order (base first, then new from detail).
        """
        by_id = {}
        order = []
        for m in list(base_mates or []) + list(detail_mates or []):
            existing = by_id.get(m.id)
            if existing is None:
                by_id[m.id] = m
                order.append(m.id)
            elif m.usage > existing.usage:
                by_id[m.id] = m
        merged = [by_id[i] for i in order]
        # Sort by usage desc when any real usage exists; else keep source order.
        if any(m.usage > 0 for m in merged):
            merged.sort(key=lambda m: m.usage, reverse=True)
        return merged

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
            top_teammates=self._merge_teammates(base.top_teammates, detail.top_teammates),
            top_tera_types=detail.top_tera_types or base.top_tera_types,
            top_spreads=detail.top_spreads or base.top_spreads,
        )

    def _check_circuit_breaker(self):
        """Check if circuit breaker allows requests."""
        cb = self._circuit_breaker
        current_time = time.time()
        
        if cb.state == "open":
            # Check if we should transition to half-open
            time_since_failure = current_time - cb.last_failure_time
            if time_since_failure >= cb.reset_timeout_seconds:
                logger.info(f"Circuit breaker transitioning to half-open for {self.name}")
                cb.state = "half-open"
                cb.half_open_requests = 0
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open for {self.name}, "
                    f"retry in {cb.reset_timeout_seconds - time_since_failure:.0f}s"
                )
        
        if cb.state == "half-open":
            if cb.half_open_requests >= cb.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker half-open limit reached for {self.name}"
                )
            cb.half_open_requests += 1

    def _record_success(self):
        """Record a successful request for circuit breaker."""
        cb = self._circuit_breaker
        if cb.state == "half-open":
            logger.info(f"Circuit breaker closing for {self.name} after successful request")
            cb.state = "closed"
            cb.failures = 0
        elif cb.state == "closed":
            # Decay failures on success
            cb.failures = max(0, cb.failures - 1)

    def _record_failure(self):
        """Record a failed request for circuit breaker."""
        cb = self._circuit_breaker
        cb.failures += 1
        cb.last_failure_time = time.time()
        
        if cb.state == "half-open":
            logger.warning(f"Circuit breaker reopening for {self.name} after failure in half-open")
            cb.state = "open"
        elif cb.state == "closed" and cb.failures >= cb.failure_threshold:
            logger.warning(
                f"Circuit breaker opening for {self.name} after {cb.failures} failures"
            )
            cb.state = "open"

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = (now - self._last_request_time) * 1000  # Convert to ms
        if elapsed < self.request_delay_ms:
            delay = (self.request_delay_ms - elapsed) / 1000
            # Add jitter to avoid thundering herd (10-30% of delay)
            jitter = delay * random.uniform(0.1, 0.3)
            await asyncio.sleep(delay + jitter)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _fetch(self, url: str, retry_count: int = 0) -> str:
        """
        Fetch a URL with retry logic, rate limiting, and circuit breaker.
        
        Args:
            url: URL to fetch
            retry_count: Current retry attempt
        
        Returns:
            Response body as string
        
        Raises:
            ScraperError: If all retries fail
            CircuitBreakerOpenError: If circuit breaker is open
        """
        # Check circuit breaker before making request
        self._check_circuit_breaker()
        
        await self._rate_limit()
        
        request_start = time.time()
        self._stats.requests_made += 1
        
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
                
                request_time_ms = (time.time() - request_start) * 1000
                
                if response.status_code == 429:
                    logger.warning(f"Rate limited by {url} after {request_time_ms:.0f}ms")
                    self._record_failure()
                    raise RateLimitError(f"Rate limited by {url}")
                
                response.raise_for_status()
                
                self._stats.requests_succeeded += 1
                self._record_success()
                
                logger.debug(f"Fetched {url} in {request_time_ms:.0f}ms ({len(response.text)} bytes)")
                return response.text
                
        except httpx.TimeoutException as e:
            request_time_ms = (time.time() - request_start) * 1000
            logger.warning(f"Timeout fetching {url} after {request_time_ms:.0f}ms (attempt {retry_count + 1})")
            
            if retry_count < self.max_retries:
                # Exponential backoff with jitter
                base_backoff = 2 ** retry_count
                jitter = random.uniform(0, base_backoff * 0.5)
                backoff = base_backoff + jitter
                logger.debug(f"Retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            
            self._stats.requests_failed += 1
            self._record_failure()
            raise ScraperError(f"Failed to fetch {url} after {self.max_retries} retries") from e
            
        except httpx.HTTPStatusError as e:
            request_time_ms = (time.time() - request_start) * 1000
            logger.warning(f"HTTP {e.response.status_code} from {url} after {request_time_ms:.0f}ms")
            
            if retry_count < self.max_retries and e.response.status_code >= 500:
                base_backoff = 2 ** retry_count
                jitter = random.uniform(0, base_backoff * 0.5)
                backoff = base_backoff + jitter
                logger.debug(f"Retrying server error in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            
            self._stats.requests_failed += 1
            self._record_failure()
            raise ScraperError(f"HTTP {e.response.status_code} from {url}") from e
            
        except CircuitBreakerOpenError:
            raise
            
        except Exception as e:
            request_time_ms = (time.time() - request_start) * 1000
            logger.error(f"Unexpected error fetching {url} after {request_time_ms:.0f}ms: {e}")
            
            if retry_count < self.max_retries:
                base_backoff = 2 ** retry_count
                jitter = random.uniform(0, base_backoff * 0.5)
                backoff = base_backoff + jitter
                await asyncio.sleep(backoff)
                return await self._fetch(url, retry_count + 1)
            
            self._stats.requests_failed += 1
            self._record_failure()
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
