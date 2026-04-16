# src/name_resolver.py
"""
Resolve English names to numeric IDs using mappings from Pokedex-Assets.

The mappings file (src/data/name_mappings.json) is generated locally from
the private Pokedex-Assets repo and committed to this public repo.
"""

import json
import re
from pathlib import Path
from functools import lru_cache
from typing import Optional


# Path to the mappings file
MAPPINGS_FILE = Path(__file__).parent / "data" / "name_mappings.json"


def normalize_name(name: str) -> str:
    """Normalize English name for consistent lookup.
    
    Examples:
        "Fake Out" → "fake-out"
        "Will-O-Wisp" → "will-o-wisp"
        "Sitrus Berry" → "sitrus-berry"
        "Rotom-Wash" → "rotom-wash"
        "Ninetales-Alola" → "ninetales-alola"
    """
    return re.sub(r'[\s]+', '-', name.strip().lower())


@lru_cache(maxsize=1)
def _load_mappings() -> dict:
    """Load name mappings from JSON file (cached)."""
    if not MAPPINGS_FILE.exists():
        print(f"Warning: {MAPPINGS_FILE} not found. Run scripts/generate_mappings.py first.")
        return {"moves": {}, "abilities": {}, "items": {}, "natures": {}, "pokemon": {}}
    
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


class NameResolver:
    """Resolve English names to numeric IDs."""
    
    def __init__(self):
        self._mappings = _load_mappings()
    
    def get_move_id(self, english_name: str) -> int:
        """Get move ID from English name. Returns 0 if not found."""
        normalized = normalize_name(english_name)
        return self._mappings.get("moves", {}).get(normalized, 0)
    
    def get_ability_id(self, english_name: str) -> int:
        """Get ability ID from English name. Returns 0 if not found."""
        normalized = normalize_name(english_name)
        return self._mappings.get("abilities", {}).get(normalized, 0)
    
    def get_item_id(self, english_name: str) -> int:
        """Get item ID from English name. Returns 0 if not found."""
        normalized = normalize_name(english_name)
        return self._mappings.get("items", {}).get(normalized, 0)
    
    def get_nature_id(self, english_name: str) -> int:
        """Get nature ID from English name. Returns 0 if not found."""
        normalized = normalize_name(english_name)
        return self._mappings.get("natures", {}).get(normalized, 0)
    
    def get_pokemon_id(self, english_name: str) -> int:
        """Get Pokémon dex ID from English name. Returns 0 if not found."""
        normalized = normalize_name(english_name)
        
        # Direct lookup
        result = self._mappings.get("pokemon", {}).get(normalized, 0)
        if result > 0:
            return result
        
        # Try form variant aliases (Pikalytics uses different naming)
        form_aliases = {
            # Paldean Tauros forms
            "tauros-paldea-combat": "paldean-tauros-combat-breed",
            "tauros-paldea-blaze": "paldean-tauros-blaze-breed",
            "tauros-paldea-aqua": "paldean-tauros-aqua-breed",
            # Mr. Rime
            "mr-rime": "mr.-rime",
            "mr rime": "mr.-rime",
            # Meowstic
            "meowstic-f": "meowstic-female",
            "meowstic-m": "meowstic-male",
            # Calyrex forms
            "calyrex-ice-rider": "calyrex-ice",
            "calyrex-shadow-rider": "calyrex-shadow",
            # Tatsugiri forms
            "tatsugiri-droopy": "tatsugiri",
            "tatsugiri-stretchy": "tatsugiri",
            "tatsugiri-curly": "tatsugiri",
            # Basculegion
            "basculegion-f": "basculegion-female",
            "basculegion-m": "basculegion-male",
            # Indeedee
            "indeedee-f": "indeedee-female",
            "indeedee-m": "indeedee-male",
        }
        
        alias = form_aliases.get(normalized)
        if alias:
            result = self._mappings.get("pokemon", {}).get(alias, 0)
            if result > 0:
                return result
        
        return 0


# Singleton instance
_resolver: Optional[NameResolver] = None


def get_resolver() -> NameResolver:
    """Get the singleton NameResolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = NameResolver()
    return _resolver


# Convenience functions
def resolve_move_id(name: str) -> int:
    return get_resolver().get_move_id(name)


def resolve_ability_id(name: str) -> int:
    return get_resolver().get_ability_id(name)


def resolve_item_id(name: str) -> int:
    return get_resolver().get_item_id(name)


def resolve_nature_id(name: str) -> int:
    return get_resolver().get_nature_id(name)


def resolve_pokemon_id(name: str) -> int:
    return get_resolver().get_pokemon_id(name)
