# src/merge.py
"""Data merge logic for combining results from multiple scrapers."""

import logging
from collections import defaultdict
from typing import Optional

from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
    TeraTypeUsage,
    EVSpread,
    TierList,
    SourceInfo,
)

logger = logging.getLogger(__name__)


class DataMerger:
    """
    Merge Pokémon competitive data from multiple sources.
    
    Priority rules:
    - Usage stats: Pikalytics > OP.GG (Pikalytics has more detailed usage data)
    - Win rates: Average across sources (more data = better accuracy)
    - Tier lists: OP.GG > others (OP.GG is known for tier lists)
    - Moves/Items/Abilities: Prefer source with more entries, merge unique ones
    """

    # Source priority for different data types (higher = preferred)
    SOURCE_PRIORITY = {
        "usage_rate": {"Pikalytics": 10, "OP.GG": 5, "Game8": 3},
        "win_rate": {"Pikalytics": 8, "OP.GG": 8, "Game8": 5},
        "tier_list": {"OP.GG": 10, "Pikalytics": 7, "Game8": 8},
        "moves": {"Pikalytics": 10, "OP.GG": 6, "Game8": 4},
        "items": {"Pikalytics": 10, "OP.GG": 6, "Game8": 4},
        "abilities": {"Pikalytics": 10, "OP.GG": 6, "Game8": 4},
        "teammates": {"Pikalytics": 10, "OP.GG": 5, "Game8": 3},
        "spreads": {"Pikalytics": 10, "OP.GG": 3, "Game8": 2},
    }

    def __init__(self, conflict_strategy: str = "weighted_average"):
        """
        Initialize the merger.
        
        Args:
            conflict_strategy: How to handle numeric conflicts
                - "weighted_average": Weight by source priority
                - "average": Simple average
                - "prefer_primary": Always use highest priority source
        """
        self.conflict_strategy = conflict_strategy

    def merge_pokemon_lists(
        self,
        sources: dict[str, list[PokemonUsage]],
    ) -> list[PokemonUsage]:
        """
        Merge Pokémon lists from multiple sources.
        
        Args:
            sources: Dict mapping source name to list of PokemonUsage
                     e.g., {"Pikalytics": [...], "OP.GG": [...]}
        
        Returns:
            Merged list of PokemonUsage, deduplicated by dex_id
        """
        if not sources:
            return []

        # Group by dex_id across all sources
        pokemon_by_id: dict[int, dict[str, PokemonUsage]] = defaultdict(dict)
        
        for source_name, pokemon_list in sources.items():
            for pokemon in pokemon_list:
                if pokemon.dex_id > 0:
                    pokemon_by_id[pokemon.dex_id][source_name] = pokemon

        # Merge each Pokémon
        merged: list[PokemonUsage] = []
        
        for dex_id, source_data in pokemon_by_id.items():
            merged_pokemon = self._merge_single_pokemon(dex_id, source_data)
            if merged_pokemon:
                merged.append(merged_pokemon)

        # Sort by usage rate (descending) and assign ranks
        merged.sort(key=lambda p: p.usage_rate, reverse=True)
        for i, pokemon in enumerate(merged, start=1):
            # Create new instance with updated rank (PokemonUsage is immutable-ish)
            merged[i-1] = PokemonUsage(
                rank=i,
                dex_id=pokemon.dex_id,
                name=pokemon.name,
                form=pokemon.form,
                usage_rate=pokemon.usage_rate,
                win_rate=pokemon.win_rate,
                top_moves=pokemon.top_moves,
                top_items=pokemon.top_items,
                top_abilities=pokemon.top_abilities,
                top_teammates=pokemon.top_teammates,
                top_tera_types=pokemon.top_tera_types,
                top_spreads=pokemon.top_spreads,
            )

        logger.info(f"Merged {len(merged)} Pokémon from {len(sources)} sources")
        return merged

    def _merge_single_pokemon(
        self,
        dex_id: int,
        source_data: dict[str, PokemonUsage],
    ) -> Optional[PokemonUsage]:
        """Merge data for a single Pokémon from multiple sources."""
        if not source_data:
            return None

        # Get the primary source (first one with data)
        primary_source = next(iter(source_data.keys()))
        primary = source_data[primary_source]

        # Merge name/form (prefer primary)
        name = primary.name
        form = primary.form

        # Merge usage rate
        usage_rate = self._merge_numeric(
            {src: p.usage_rate for src, p in source_data.items()},
            "usage_rate",
        )

        # Merge win rate (average when available from multiple sources)
        win_rates = {
            src: p.win_rate 
            for src, p in source_data.items() 
            if p.win_rate is not None
        }
        win_rate = self._merge_numeric(win_rates, "win_rate") if win_rates else None

        # Merge lists (moves, items, abilities, etc.)
        top_moves = self._merge_usage_lists(
            {src: p.top_moves for src, p in source_data.items()},
            "moves",
            key_attr="name",
        )
        
        top_items = self._merge_usage_lists(
            {src: p.top_items for src, p in source_data.items()},
            "items",
            key_attr="name",
        )
        
        top_abilities = self._merge_usage_lists(
            {src: p.top_abilities for src, p in source_data.items()},
            "abilities",
            key_attr="name",
        )
        
        top_teammates = self._merge_teammate_lists(
            {src: p.top_teammates for src, p in source_data.items()},
        )
        
        top_tera_types = self._merge_tera_lists(
            {src: p.top_tera_types for src, p in source_data.items()},
        )
        
        top_spreads = self._merge_spread_lists(
            {src: p.top_spreads for src, p in source_data.items()},
        )

        return PokemonUsage(
            rank=0,  # Will be set later after sorting
            dex_id=dex_id,
            name=name,
            form=form,
            usage_rate=usage_rate,
            win_rate=win_rate,
            top_moves=top_moves,
            top_items=top_items,
            top_abilities=top_abilities,
            top_teammates=top_teammates,
            top_tera_types=top_tera_types,
            top_spreads=top_spreads,
        )

    def _merge_numeric(
        self,
        values: dict[str, float],
        data_type: str,
    ) -> float:
        """Merge numeric values from multiple sources."""
        if not values:
            return 0.0

        if len(values) == 1:
            return next(iter(values.values()))

        if self.conflict_strategy == "prefer_primary":
            # Return value from highest priority source
            priorities = self.SOURCE_PRIORITY.get(data_type, {})
            best_source = max(values.keys(), key=lambda s: priorities.get(s, 0))
            return values[best_source]

        elif self.conflict_strategy == "weighted_average":
            # Weighted average by source priority
            priorities = self.SOURCE_PRIORITY.get(data_type, {})
            total_weight = sum(priorities.get(src, 1) for src in values.keys())
            if total_weight == 0:
                return sum(values.values()) / len(values)
            
            weighted_sum = sum(
                val * priorities.get(src, 1) 
                for src, val in values.items()
            )
            return weighted_sum / total_weight

        else:  # "average"
            return sum(values.values()) / len(values)

    def _merge_usage_lists(
        self,
        source_lists: dict[str, list],
        data_type: str,
        key_attr: str,
        max_items: int = 4,
    ) -> list:
        """Merge lists of usage items (moves, items, abilities)."""
        if not source_lists:
            return []

        # Find the best source (most items + highest priority)
        priorities = self.SOURCE_PRIORITY.get(data_type, {})
        
        def score_source(src: str, items: list) -> tuple:
            return (len(items), priorities.get(src, 0))

        non_empty = {src: items for src, items in source_lists.items() if items}
        if not non_empty:
            return []

        # Use best source as base
        best_source = max(non_empty.keys(), key=lambda s: score_source(s, non_empty[s]))
        base_list = non_empty[best_source]

        # Merge in unique items from other sources
        seen_keys = {getattr(item, key_attr).lower() for item in base_list}
        merged = list(base_list)

        for src, items in non_empty.items():
            if src == best_source:
                continue
            for item in items:
                key = getattr(item, key_attr).lower()
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged.append(item)

        # Sort by usage and limit
        merged.sort(key=lambda x: x.usage, reverse=True)
        return merged[:max_items]

    def _merge_teammate_lists(
        self,
        source_lists: dict[str, list[TeammateUsage]],
        max_items: int = 6,
    ) -> list[TeammateUsage]:
        """Merge teammate lists, deduplicating by dex_id."""
        if not source_lists:
            return []

        # Group by dex_id
        by_dex_id: dict[int, list[TeammateUsage]] = defaultdict(list)
        
        for items in source_lists.values():
            for item in items:
                if item.dex_id > 0:
                    by_dex_id[item.dex_id].append(item)

        # Average usage for duplicates
        merged = []
        for dex_id, items in by_dex_id.items():
            avg_usage = sum(i.usage for i in items) / len(items)
            merged.append(TeammateUsage(
                dex_id=dex_id,
                name=items[0].name,
                usage=avg_usage,
            ))

        merged.sort(key=lambda x: x.usage, reverse=True)
        return merged[:max_items]

    def _merge_tera_lists(
        self,
        source_lists: dict[str, list[TeraTypeUsage]],
        max_items: int = 4,
    ) -> list[TeraTypeUsage]:
        """Merge tera type lists, deduplicating by type."""
        if not source_lists:
            return []

        # Group by type
        by_type: dict[str, list[TeraTypeUsage]] = defaultdict(list)
        
        for items in source_lists.values():
            for item in items:
                by_type[item.type.lower()].append(item)

        # Average usage for duplicates
        merged = []
        for type_name, items in by_type.items():
            avg_usage = sum(i.usage for i in items) / len(items)
            merged.append(TeraTypeUsage(
                type=items[0].type,
                usage=avg_usage,
            ))

        merged.sort(key=lambda x: x.usage, reverse=True)
        return merged[:max_items]

    def _merge_spread_lists(
        self,
        source_lists: dict[str, list[EVSpread]],
        max_items: int = 4,
    ) -> list[EVSpread]:
        """Merge EV spread lists."""
        if not source_lists:
            return []

        # Use source with most spreads
        non_empty = {src: items for src, items in source_lists.items() if items}
        if not non_empty:
            return []

        priorities = self.SOURCE_PRIORITY.get("spreads", {})
        best_source = max(
            non_empty.keys(), 
            key=lambda s: (len(non_empty[s]), priorities.get(s, 0))
        )
        
        return non_empty[best_source][:max_items]

    def merge_tier_lists(
        self,
        source_lists: dict[str, TierList],
    ) -> TierList:
        """
        Merge tier lists from multiple sources.
        
        Uses highest priority source as base, adds missing Pokémon from others.
        """
        if not source_lists:
            return TierList()

        priorities = self.SOURCE_PRIORITY.get("tier_list", {})
        best_source = max(source_lists.keys(), key=lambda s: priorities.get(s, 0))
        
        return source_lists[best_source]


def merge_scraped_data(
    sources: dict[str, list[PokemonUsage]],
    tier_lists: Optional[dict[str, TierList]] = None,
    conflict_strategy: str = "weighted_average",
) -> tuple[list[PokemonUsage], Optional[TierList]]:
    """
    Convenience function to merge scraped data from multiple sources.
    
    Args:
        sources: Dict mapping source name to PokemonUsage list
        tier_lists: Optional dict mapping source name to TierList
        conflict_strategy: How to handle conflicts ("weighted_average", "average", "prefer_primary")
    
    Returns:
        Tuple of (merged pokemon list, merged tier list)
    """
    merger = DataMerger(conflict_strategy=conflict_strategy)
    
    merged_pokemon = merger.merge_pokemon_lists(sources)
    merged_tiers = merger.merge_tier_lists(tier_lists) if tier_lists else None
    
    return merged_pokemon, merged_tiers
