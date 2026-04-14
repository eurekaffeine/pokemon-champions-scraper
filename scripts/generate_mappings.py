#!/usr/bin/env python3
"""
Generate name-to-ID mappings from Pokedex-Assets translation files.

This script reads from the PRIVATE Pokedex-Assets repo and generates
a public-safe mapping file (English name → numeric ID only).

Usage:
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


def normalize_name(name: str) -> str:
    """Normalize English name for consistent lookup.
    
    Examples:
        "Fake Out" → "fake-out"
        "Will-O-Wisp" → "will-o-wisp"
        "Sitrus Berry" → "sitrus-berry"
    """
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
    
    # Add mega/gmax/form variants
    for variant_file in ['mega-names-translation.json', 'gmax-names-translation.json', 
                          'form-changing-names-translation.json']:
        variant_data = load_translation_file(translations_path / variant_file)
        variant_mappings = extract_english_to_id(variant_data)
        mappings['pokemon'].update(variant_mappings)
    
    print(f"Loaded {len(mappings['pokemon'])} pokemon mappings")
    
    return mappings


def main():
    parser = argparse.ArgumentParser(description='Generate name-to-ID mappings from Pokedex-Assets')
    parser.add_argument('--assets', type=str, required=True,
                        help='Path to Pokedex-Assets directory')
    parser.add_argument('--output', type=str, default='src/data/name_mappings.json',
                        help='Output path for mappings JSON')
    args = parser.parse_args()
    
    assets_path = Path(args.assets).expanduser()
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
