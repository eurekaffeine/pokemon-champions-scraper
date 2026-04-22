# src/__init__.py
"""Pokémon Champions Scraper - Fetch competitive battle metadata."""

__version__ = "0.2.0"

from .merge import DataMerger, merge_scraped_data

__all__ = ["__version__", "DataMerger", "merge_scraped_data"]
