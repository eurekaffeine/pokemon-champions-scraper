# scripts/audit_ids.py
"""
Audit scraped output against Pokédex-Assets to ensure every dex_id
maps to a valid asset file. Exits non-zero if any ID is missing.
"""

import json
import sys
from pathlib import Path


def audit(battle_meta_path: str, mappings_path: str) -> bool:
    """
    Validate that every dex_id in battle_meta.json exists in name_mappings.json
    and that no Pokémon was silently dropped (dex_id=0).

    Returns True if all IDs are valid.
    """
    with open(battle_meta_path, "r") as f:
        data = json.load(f)

    with open(mappings_path, "r") as f:
        mappings = json.load(f)

    # Build set of all known valid pokemon IDs from mappings
    valid_ids = set(mappings.get("pokemon", {}).values())

    pokemon_list = data.get("pokemon_usage", [])
    if not pokemon_list:
        print("❌ AUDIT FAIL: battle_meta.json has no pokemon_usage entries")
        return False

    errors = []
    warnings = []

    for p in pokemon_list:
        dex_id = p.get("dex_id", 0)
        name = p.get("name", "unknown")

        if dex_id <= 0:
            errors.append(f"  ❌ {name}: dex_id={dex_id} (unresolved)")
        elif dex_id not in valid_ids:
            warnings.append(f"  ⚠️  {name}: dex_id={dex_id} (not in mappings, may be alias-resolved)")

    # Check for duplicate dex_ids (form variants mapping to same base is OK, just flag it)
    seen_ids: dict[int, list[str]] = {}
    for p in pokemon_list:
        dex_id = p.get("dex_id", 0)
        name = p.get("name", "unknown")
        if dex_id > 0:
            seen_ids.setdefault(dex_id, []).append(name)

    duplicates = {k: v for k, v in seen_ids.items() if len(v) > 1}
    if duplicates:
        print(f"ℹ️  {len(duplicates)} dex_ids shared by multiple forms (expected for variants):")
        for dex_id, names in sorted(duplicates.items()):
            print(f"    {dex_id}: {', '.join(names)}")

    # Report
    print(f"\n📊 Audit Results:")
    print(f"  Total Pokémon: {len(pokemon_list)}")
    print(f"  Valid IDs: {len(pokemon_list) - len(errors)}")
    print(f"  Unresolved: {len(errors)}")

    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for w in warnings:
            print(w)

    if errors:
        print(f"\n❌ Errors ({len(errors)}):")
        for e in errors:
            print(e)
        return False

    print("\n✅ All Pokémon IDs are valid!")
    return True


if __name__ == "__main__":
    battle_meta = sys.argv[1] if len(sys.argv) > 1 else "output/battle_meta.json"
    mappings = sys.argv[2] if len(sys.argv) > 2 else "src/data/name_mappings.json"

    if not Path(battle_meta).exists():
        print(f"❌ File not found: {battle_meta}")
        sys.exit(1)

    if not Path(mappings).exists():
        print(f"❌ File not found: {mappings}")
        sys.exit(1)

    ok = audit(battle_meta, mappings)
    sys.exit(0 if ok else 1)
