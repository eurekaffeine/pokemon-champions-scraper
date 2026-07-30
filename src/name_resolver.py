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
        self._compact_mappings: dict[str, dict[str, int]] = {}
        for section in ("moves", "abilities", "items"):
            compact: dict[str, int] = {}
            ambiguous: set[str] = set()
            for key, value in self._mappings.get(section, {}).items():
                compact_key = re.sub(r'[^a-z0-9]', '', key)
                if compact_key in compact and compact[compact_key] != value:
                    ambiguous.add(compact_key)
                else:
                    compact[compact_key] = value
            for key in ambiguous:
                compact.pop(key, None)
            self._compact_mappings[section] = compact
    
    def _get_compact_id(self, section: str, english_name: str) -> int:
        """Resolve compact Showdown IDs such as ``roughskin`` or ``uturn``."""
        compact = re.sub(r'[^a-z0-9]', '', english_name.strip().lower())
        return self._compact_mappings.get(section, {}).get(compact, 0)

    def get_move_id(self, english_name: str) -> int:
        """Get move ID from an English name or Showdown ID."""
        normalized = normalize_name(english_name)
        return self._mappings.get("moves", {}).get(normalized, 0) or self._get_compact_id(
            "moves", english_name
        )
    
    def get_ability_id(self, english_name: str) -> int:
        """Get ability ID from an English name or Showdown ID."""
        normalized = normalize_name(english_name)
        return self._mappings.get("abilities", {}).get(normalized, 0) or self._get_compact_id(
            "abilities", english_name
        )
    
    def get_item_id(self, english_name: str) -> int:
        """Get item ID from an English name or Showdown ID."""
        normalized = normalize_name(english_name)
        return self._mappings.get("items", {}).get(normalized, 0) or self._get_compact_id(
            "items", english_name
        )
    
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
            "tauros-paldea": "paldean-tauros-combat-breed",
            "tauros-paldea-combat": "paldean-tauros-combat-breed",
            "tauros-paldea-blaze": "paldean-tauros-blaze-breed",
            "tauros-paldea-aqua": "paldean-tauros-aqua-breed",
            # Mr. Rime / Mr. Mime
            "mr-rime": "mr.-rime",
            "mr-rime": "mr.-rime",
            "mr rime": "mr.-rime",
            "mr-mime": "mr.-mime",
            "mr-mime-galar": "mr.-mime-galar",
            # Meowstic
            "meowstic-f": "meowstic-female",
            "meowstic-m": "meowstic-male",
            # Calyrex forms
            "calyrex-ice-rider": "calyrex-ice",
            "calyrex-shadow-rider": "calyrex-shadow",
            # Tatsugiri forms
            # Tatsugiri forms → base form (variants don't have separate asset files)
            "tatsugiri-droopy": "tatsugiri",
            "tatsugiri-stretchy": "tatsugiri",
            "tatsugiri-curly": "tatsugiri",
            # Basculegion
            "basculegion-f": "basculegion-female",
            "basculegion-m": "basculegion-male",
            # Indeedee
            "indeedee-f": "indeedee-female",
            "indeedee-m": "indeedee-male",
            # Floette — "Floette-Eternal" (Pikalytics) refers to the Eternal Flower
            # form (dex_id 10061), NOT MegaFloette (dex_id 10296).
            "floette-eternal": "floette-eternal-flower",
            # Sinistcha
            "sinistcha-masterpiece": "sinistcha",
            # Maushold
            "maushold-four": "maushold",
            "maushold-family-of-three": "maushold-family-of-three",
            # Palafin
            "palafin-hero": "palafin-hero-form",
            # Vivillon forms → base form (variants don't have separate asset files)
            "vivillon-high-plains": "vivillon",
            "vivillon-garden": "vivillon",
            "vivillon-polar": "vivillon",
            "vivillon-tundra": "vivillon",
            "vivillon-continental": "vivillon",
            "vivillon-elegant": "vivillon",
            "vivillon-icy-snow": "vivillon",
            "vivillon-modern": "vivillon",
            "vivillon-marine": "vivillon",
            "vivillon-archipelago": "vivillon",
            "vivillon-sandstorm": "vivillon",
            "vivillon-river": "vivillon",
            "vivillon-monsoon": "vivillon",
            "vivillon-savanna": "vivillon",
            "vivillon-sun": "vivillon",
            "vivillon-ocean": "vivillon",
            "vivillon-jungle": "vivillon",
        }
        
        alias = form_aliases.get(normalized)
        if alias:
            result = self._mappings.get("pokemon", {}).get(alias, 0)
            if result > 0:
                return result

        # Mega / Gmax fallback: these forms share the National Pokédex number
        # of their base form (e.g. Charizard-Mega-X → 6, Gyarados-Mega → 130,
        # Floette-Eternal-Mega → Floette-Eternal). Pikalytics started returning
        # Mega forms in the championstournaments dataset around 2026-05-16,
        # but Pocket-Gallery does not ship separate Mega assets, so we map
        # them back to the base dex_id rather than dropping them.
        for suffix in ("-mega-x", "-mega-y", "-mega", "-gmax", "-gigantamax"):
            if normalized.endswith(suffix):
                base = normalized[: -len(suffix)]
                # Recurse so the base name still benefits from form_aliases
                # (e.g. "floette-eternal-mega" → "floette-eternal" → 10061).
                if base and base != normalized:
                    base_id = self.get_pokemon_id(base)
                    if base_id > 0:
                        return base_id
                break

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
