# src/merge.py
"""Merge data from multiple scraper sources."""

import logging
from typing import Optional
from collections import defaultdict

from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
    TeraTypeUsage,
    EVSpread,
    TierList,
)

logger = logging.getLogger(__name__)


class DataMerger:
    """
    Merges competitive data from multiple sources.
    
    Priority rules:
    - Usage rates: prefer Pikalytics (more accurate)
    - Win rates: average across sources
    - Moves/Items/Abilities: prefer source with more data
    - Tier lists: prefer OP.GG (human-curated)
    """

    def __init__(self, primary_source: str = "Pikalytics"):
        self.primary_source = primary_source

    def merge_pokemon_lists(
        self,
        *sources: tuple[str, list[PokemonUsage]],
    ) -> list[PokemonUsage]:
        """
        Merge Pokémon usage lists from multiple sources.
        
        Args:
            *sources: Tuples of (source_name, pokemon_list)
        
        Returns:
            Merged list of PokemonUsage, deduplicated by dex_id
        """
        # Group by dex_id
        by_dex_id: dict[int, list[tuple[str, PokemonUsage]]] = defaultdict(list)
        
        for source_name, pokemon_list in sources:
            for pokemon in pokemon_list:
                if pokemon.dex_id > 0:
                    by_dex_id[pokemon.dex_id].append((source_name, pokemon))
        
        # Merge each Pokémon
        merged = []
        for dex_id, entries in by_dex_id.items():
            merged_pokemon = self._merge_single_pokemon(entries)
            merged.append(merged_pokemon)
        
        # Sort by usage rate (descending) and assign ranks
        merged.sort(key=lambda p: p.usage_rate, reverse=True)
        for i, pokemon in enumerate(merged, 1):
            pokemon.rank = i
        
        logger.info(f"Merged {len(merged)} Pokémon from {len(sources)} sources")
        return merged

    def _merge_single_pokemon(
        self,
        entries: list[tuple[str, PokemonUsage]],
    ) -> PokemonUsage:
        """Merge multiple entries for a single Pokémon."""
        if len(entries) == 1:
            return entries[0][1].model_copy()
        
        # Find primary source entry
        primary_entry = None
        other_entries = []
        for source_name, pokemon in entries:
            if source_name == self.primary_source:
                primary_entry = pokemon
            else:
                other_entries.append((source_name, pokemon))
        
        # If no primary, use first entry as base
        base = primary_entry or entries[0][1]
        
        # Merge fields
        merged = base.model_copy()
        
        # Average win rates from all sources
        win_rates = [p.win_rate for _, p in entries if p.win_rate is not None]
        if win_rates:
            merged.win_rate = sum(win_rates) / len(win_rates)
        
        # Prefer source with more moves/items/etc
        for source_name, pokemon in entries:
            if len(pokemon.top_moves) > len(merged.top_moves):
                merged.top_moves = pokemon.top_moves
            if len(pokemon.top_items) > len(merged.top_items):
                merged.top_items = pokemon.top_items
            if len(pokemon.top_abilities) > len(merged.top_abilities):
                merged.top_abilities = pokemon.top_abilities
            if len(pokemon.top_teammates) > len(merged.top_teammates):
                merged.top_teammates = pokemon.top_teammates
            if len(pokemon.top_tera_types) > len(merged.top_tera_types):
                merged.top_tera_types = pokemon.top_tera_types
            if len(pokemon.top_spreads) > len(merged.top_spreads):
                merged.top_spreads = pokemon.top_spreads
        
        return merged

    def merge_tier_lists(
        self,
        *tier_lists: dict[str, list[int]],
    ) -> TierList:
        """
        Merge tier lists from multiple sources.
        
        Uses voting: if a Pokémon appears in S tier in most sources, it's S tier.
        Falls back to first source's tier if tied.
        """
        if not tier_lists:
            return TierList()
        
        if len(tier_lists) == 1:
            tl = tier_lists[0]
            return TierList(
                S=tl.get("S", []),
                A=tl.get("A", []),
                B=tl.get("B", []),
                C=tl.get("C", []),
                D=tl.get("D", []),
            )
        
        # Count tier assignments per Pokémon
        tier_votes: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        tier_order = ["S", "A", "B", "C", "D"]
        
        for tier_list in tier_lists:
            for tier, dex_ids in tier_list.items():
                for dex_id in dex_ids:
                    tier_votes[dex_id][tier] += 1
        
        # Assign to tier with most votes
        final_tiers: dict[str, list[int]] = {t: [] for t in tier_order}
        
        for dex_id, votes in tier_votes.items():
            # Find tier with most votes
            best_tier = max(votes.keys(), key=lambda t: (votes[t], -tier_order.index(t)))
            final_tiers[best_tier].append(dex_id)
        
        return TierList(
            S=final_tiers["S"],
            A=final_tiers["A"],
            B=final_tiers["B"],
            C=final_tiers["C"],
            D=final_tiers["D"],
        )

    def deduplicate_list(
        self,
        items: list,
        key_fn,
    ) -> list:
        """Remove duplicates from a list, keeping first occurrence."""
        seen = set()
        result = []
        for item in items:
            key = key_fn(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result


def merge_scraper_results(
    pikalytics_data: Optional[list[PokemonUsage]] = None,
    opgg_data: Optional[list[PokemonUsage]] = None,
    opgg_tier_list: Optional[dict[str, list[int]]] = None,
) -> tuple[list[PokemonUsage], Optional[TierList]]:
    """
    Convenience function to merge results from known scrapers.
    
    Args:
        pikalytics_data: Results from Pikalytics scraper
        opgg_data: Results from OP.GG scraper
        opgg_tier_list: Tier list from OP.GG
    
    Returns:
        Tuple of (merged_pokemon_list, tier_list)
    """
    merger = DataMerger(primary_source="Pikalytics")
    
    # Collect available sources
    sources = []
    if pikalytics_data:
        sources.append(("Pikalytics", pikalytics_data))
    if opgg_data:
        sources.append(("OP.GG", opgg_data))
    
    # Merge Pokémon data
    if sources:
        merged_pokemon = merger.merge_pokemon_lists(*sources)
    else:
        merged_pokemon = []
    
    # Use tier list if provided
    tier_list = None
    if opgg_tier_list:
        tier_list = merger.merge_tier_lists(opgg_tier_list)
    
    return merged_pokemon, tier_list
