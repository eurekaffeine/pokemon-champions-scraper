# src/scrapers/__init__.py
"""Scraper implementations for various data sources."""

from .base import BaseScraper, ScraperError, ParseError, RateLimitError, CircuitBreakerOpenError, ScrapeStats
from .pikalytics import PikalyticsScraper
from .opgg import OPGGScraper

__all__ = [
    "BaseScraper",
    "ScraperError",
    "ParseError",
    "RateLimitError",
    "CircuitBreakerOpenError",
    "ScrapeStats",
    "PikalyticsScraper",
    "OPGGScraper",
]
