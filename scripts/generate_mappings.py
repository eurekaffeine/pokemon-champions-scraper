#!/usr/bin/env python3
"""
Generate name-to-ID mappings from Pokedex-Assets translation files.

This script reads from the PRIVATE Pokedex-Assets repo and generates
a public-safe mapping file (English name → numeric ID only).

Usage:
    # Option 1: Use .env file
    echo "POKEDEX_ASSETS_PATH=~/Code/Pokedex-Assets" > .env
    python scripts/generate_mappings.py

    # Option 2: Use CLI argument
    python scripts/generate_mappings.py --assets ~/Code/Pokedex-Assets

Output:
    src/data/name_mappings.json

The output file should be committed to this repo. Run this script locally
whenever Pokedex-Assets is updated (typically once per game release).
"""

import argparse
import json
import os
import re
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use CLI args or env vars directly


def normalize_name(name: str) -> str:
    """Normalize English name for consistent lookup.
    
    Examples:
        "Fake Out" → "fake-out"
        "Will-O-Wisp" → "will-o-wisp"
        "Sitrus Berry" → "sitrus-berry"
        "Rotom(wash)" → "rotom-wash"
        "Ninetales(Alola)" → "ninetales-alola"
    """
    # Replace parentheses with hyphens for form variants
    name = re.sub(r'\(([^)]+)\)', r'-\1', name)
    return re.sub(r'[\s]+', '-', name.strip().lower())


def load_translation_file(path: Path) -> dict:
    """Load a translation JSON file."""
    if not path.exists():
        print(f"Warning: {path} not found, skipping")
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_english_to_id(data: dict) -> dict[str, int]:
    """Extract English name → ID mapping from translation data.
    
    Translation files have structure:
    {
        "252": {"en": "Fake Out", "zh-Hans": "抑先攻击", ...},
        "521": {"en": "Parting Shot", ...}
    }
    """
    mapping = {}
    for id_str, translations in data.items():
        try:
            id_num = int(id_str)
            english_name = translations.get('en', '')
            if english_name:
                normalized = normalize_name(english_name)
                mapping[normalized] = id_num
        except (ValueError, TypeError):
            continue
    return mapping


def generate_mappings(assets_path: Path) -> dict:
    """Generate all name mappings from Pokedex-Assets."""
    translations_path = assets_path / 'translations'
    
    mappings = {
        'moves': {},
        'abilities': {},
        'items': {},
        'natures': {},
        'pokemon': {},
        'pokemon_abilities': {},
    }
    
    # Moves
    moves_data = load_translation_file(translations_path / 'move-names-translation.json')
    mappings['moves'] = extract_english_to_id(moves_data)
    print(f"Loaded {len(mappings['moves'])} move mappings")
    
    # Abilities
    abilities_data = load_translation_file(translations_path / 'ability-names-translation.json')
    mappings['abilities'] = extract_english_to_id(abilities_data)
    print(f"Loaded {len(mappings['abilities'])} ability mappings")
    
    # Items
    items_data = load_translation_file(translations_path / 'item-names.json')
    mappings['items'] = extract_english_to_id(items_data)
    print(f"Loaded {len(mappings['items'])} item mappings")
    
    # Natures
    natures_data = load_translation_file(translations_path / 'nature-names.json')
    mappings['natures'] = extract_english_to_id(natures_data)
    print(f"Loaded {len(mappings['natures'])} nature mappings")
    
    # Pokemon names (from multiple files)
    pokemon_data = load_translation_file(translations_path / 'pokemon-names-translation.json')
    mappings['pokemon'] = extract_english_to_id(pokemon_data)
    # Preserve canonical species IDs when cosmetic translation files reuse the
    # exact same English display name (for example all Furfrou trims are named
    # "Furfrou"). Variant aliases are added below without replacing the base.
    canonical_pokemon_mappings = dict(mappings['pokemon'])
    
    # Add mega/gmax/form variants from translations.
    for variant_file in ['mega-names-translation.json', 'gmax-names-translation.json',
                          'form-changing-names-translation.json']:
        variant_data = load_translation_file(translations_path / variant_file)
        variant_mappings = extract_english_to_id(variant_data)
        mappings['pokemon'].update(variant_mappings)
    mappings['pokemon'].update(canonical_pokemon_mappings)

    # The English Mega translations use display names such as "MegaGarchomp",
    # while Pokémon Showdown uses battle identifiers such as "Garchomp-Mega".
    # Add the canonical battle-form names from the asset manifest so both forms
    # resolve to the same Pocket Gallery asset ID.
    mega_manifest = load_translation_file(assets_path / 'pokedex' / 'pokedex-mega.json')
    if isinstance(mega_manifest, list):
        for entry in mega_manifest:
            try:
                variant_id = int(entry.get('id', 0))
                variant_name = entry.get('name', '')
            except (TypeError, ValueError):
                continue
            if variant_id > 0 and variant_name:
                mappings['pokemon'][normalize_name(variant_name)] = variant_id

    # Showdown aliases that do not have a one-to-one localized asset name.
    # Gourgeist sizes intentionally share the base app asset; the scraper
    # aggregates their usage before writing a single file. Showdown's male
    # Mega Meowstic spelling maps to the one Mega Meowstic asset.
    mappings['pokemon'].update({
        'gourgeist-super': mappings['pokemon'].get('gourgeist', 0),
        'gourgeist-small': mappings['pokemon'].get('gourgeist', 0),
        'gourgeist-large': mappings['pokemon'].get('gourgeist', 0),
        'meowstic-m-mega': mappings['pokemon'].get('meowstic-mega', 0)
            or mappings['pokemon'].get('megameowstic', 0),
    })
    mappings['pokemon'] = {
        name: pokemon_id
        for name, pokemon_id in mappings['pokemon'].items()
        if pokemon_id > 0
    }

    # Ability allow-list keyed by the same app Pokémon/form IDs used in output.
    # Include linked varieties so a base row that represents an in-battle Mega
    # form may legitimately expose either form's ability. This lets the scraper
    # reject impossible upstream ability contamination without hardcoding names.
    details_path = assets_path / 'pokedex' / 'details'
    details: dict[int, dict] = {}
    if details_path.exists():
        for detail_path in details_path.glob('*.json'):
            try:
                details[int(detail_path.stem)] = load_translation_file(detail_path)
            except ValueError:
                continue

    def linked_abilities(pokemon_id: int) -> list[int]:
        seen: set[int] = set()
        pending = [pokemon_id]
        ability_ids: set[int] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            detail = details.get(current, {})
            ability_ids.update(detail.get('abilities', []))
            ability_ids.update(detail.get('hiddenAbilities', []))
            pending.extend(detail.get('varieties', []))
        return sorted(ability_ids)

    mappings['pokemon_abilities'] = {
        str(pokemon_id): linked_abilities(pokemon_id)
        for pokemon_id in sorted(details)
    }
    # Cosmetic Squawkabilly plumages collapse to asset 931. Yellow and white
    # plumage can have Sheer Force, but those cosmetic forms have no standalone
    # detail JSON in the asset bundle. Preserve the legal sibling-form ability.
    squawkabilly_id = mappings['pokemon'].get('squawkabilly', 0)
    sheer_force_id = mappings['abilities'].get('sheer-force', 0)
    if squawkabilly_id > 0 and sheer_force_id > 0:
        allowed = mappings['pokemon_abilities'].setdefault(
            str(squawkabilly_id), []
        )
        mappings['pokemon_abilities'][str(squawkabilly_id)] = sorted(
            set(allowed) | {sheer_force_id}
        )

    print(f"Loaded {len(mappings['pokemon'])} pokemon mappings")
    print(f"Loaded {len(mappings['pokemon_abilities'])} Pokemon ability allow-lists")
    
    return mappings


def main():
    parser = argparse.ArgumentParser(description='Generate name-to-ID mappings from Pokedex-Assets')
    parser.add_argument('--assets', type=str, default=None,
                        help='Path to Pokedex-Assets directory (or set POKEDEX_ASSETS_PATH env var)')
    parser.add_argument('--output', type=str, default='src/data/name_mappings.json',
                        help='Output path for mappings JSON')
    args = parser.parse_args()
    
    # Resolve assets path: CLI arg > env var > error
    assets_path_str = args.assets or os.environ.get('POKEDEX_ASSETS_PATH')
    if not assets_path_str:
        print("Error: Pokedex-Assets path not specified.")
        print("Either:")
        print("  1. Create .env file with: POKEDEX_ASSETS_PATH=~/Code/Pokedex-Assets")
        print("  2. Set environment variable: export POKEDEX_ASSETS_PATH=~/Code/Pokedex-Assets")
        print("  3. Use CLI argument: --assets ~/Code/Pokedex-Assets")
        return 1
    
    assets_path = Path(assets_path_str).expanduser()
    if not assets_path.exists():
        print(f"Error: Pokedex-Assets not found at {assets_path}")
        return 1
    
    print(f"Reading from: {assets_path}")
    
    mappings = generate_mappings(assets_path)
    
    # Add metadata
    output = {
        '_meta': {
            'description': 'English name to ID mappings for localization',
            'source': 'Generated from Pokedex-Assets (private)',
            'note': 'Run scripts/generate_mappings.py to regenerate',
        },
        **mappings
    }
    
    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\nWritten to: {output_path}")
    print(f"Total mappings: {sum(len(v) for k, v in mappings.items() if k != '_meta')}")
    
    return 0


if __name__ == '__main__':
    exit(main())
