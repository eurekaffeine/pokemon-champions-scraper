# src/output.py
"""Output writer for battle metadata JSON files."""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.models.schema import BattleMeta, PokemonUsage, PokemonDetail, PokemonCompetitive

logger = logging.getLogger(__name__)


def write_battle_meta(
    data: BattleMeta,
    output_dir: Path,
    filename: str = "battle_meta.json",
    indent: int = 2,
) -> Path:
    """
    Write BattleMeta to JSON file.
    
    Args:
        data: BattleMeta model to write
        output_dir: Directory to write to
        filename: Output filename
        indent: JSON indentation level
    
    Returns:
        Path to written file
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    
    # Convert to dict with ISO format dates
    json_data = data.model_dump(mode="json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=indent, ensure_ascii=False)
    
    logger.info(f"Wrote battle meta to {output_path}")
    return output_path


def write_pokemon_files(
    pokemon_list: list[PokemonUsage],
    output_dir: Path,
    indent: int = 2,
) -> list[Path]:
    """
    Write individual JSON files for each Pokémon.
    
    Args:
        pokemon_list: List of PokemonUsage models
        output_dir: Directory to write to (files go in output_dir/pokemon/)
        indent: JSON indentation level
    
    Returns:
        List of paths to written files
    """
    pokemon_dir = output_dir / "pokemon"
    pokemon_dir.mkdir(parents=True, exist_ok=True)
    
    written_files = []
    # Track which (dex_id) we've already written, to detect collisions where
    # two different source rows would clobber the same {dex_id}.json file.
    written_by_id: dict[int, str] = {}
    
    for pokemon in pokemon_list:
        if pokemon.dex_id <= 0:
            logger.warning(f"Skipping {pokemon.name} - invalid dex_id")
            continue
        
        prior = written_by_id.get(pokemon.dex_id)
        if prior is not None and prior != pokemon.name:
            # Two distinct Pokemon/forms resolved to the same dex_id. Writing
            # the second would silently overwrite the first (this is exactly
            # the Floette-Eternal / Floette-Eternal-Mega bug). Fail loudly so
            # the mapping/feed gets fixed instead of corrupting output.
            raise ValueError(
                f"dex_id collision: {pokemon.dex_id}.json would be written for "
                f"both {prior!r} and {pokemon.name!r}. Fix the name resolver or "
                f"data source so distinct forms get distinct ids."
            )
        written_by_id[pokemon.dex_id] = pokemon.name
        
        # Convert to per-pokemon format
        detail = PokemonDetail(
            dex_id=pokemon.dex_id,
            name=pokemon.name,
            form=pokemon.form,
            competitive=PokemonCompetitive(
                usage_rank=pokemon.rank,
                usage_rate=pokemon.usage_rate,
                win_rate=pokemon.win_rate,
                moves=pokemon.top_moves,
                items=pokemon.top_items,
                abilities=pokemon.top_abilities,
                teammates=pokemon.top_teammates,
                tera_types=pokemon.top_tera_types,
                spreads=pokemon.top_spreads,
            ),
        )
        
        output_path = pokemon_dir / f"{pokemon.dex_id}.json"
        json_data = detail.model_dump(mode="json")
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=indent, ensure_ascii=False)
        
        written_files.append(output_path)
    
    logger.info(f"Wrote {len(written_files)} Pokémon files to {pokemon_dir}")
    return written_files


def validate_output(output_path: Path) -> bool:
    """
    Validate an output JSON file against the schema.
    
    Args:
        output_path: Path to JSON file
    
    Returns:
        True if valid, raises ValueError if invalid
    """
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Validate against schema
        BattleMeta.model_validate(data)
        logger.info(f"Validation passed for {output_path}")
        return True
    
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    except Exception as e:
        raise ValueError(f"Schema validation failed: {e}")
