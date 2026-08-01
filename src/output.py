# src/output.py
"""Output writer for battle metadata JSON files."""

import json
import logging
from pathlib import Path
from typing import Optional

from src.models.schema import BattleMeta, PokemonCompetitive, PokemonDetail, PokemonUsage

logger = logging.getLogger(__name__)

PUBLIC_LIST_LIMIT = 10


def _trim_public_usage(data: dict) -> dict:
    """Remove unused bulk fields and cap lists exposed by current clients."""
    trimmed = data.copy()
    trimmed.pop("top_spreads", None)
    for key in ("top_moves", "top_items", "top_teammates"):
        trimmed[key] = trimmed.get(key, [])[:PUBLIC_LIST_LIMIT]
    return trimmed


def _dump_json(data: dict, path: Path, indent: Optional[int]) -> None:
    """Write compact production JSON unless indentation is explicitly requested."""
    with open(path, "w", encoding="utf-8") as f:
        if indent is None:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=indent)


def write_battle_meta(
    data: BattleMeta,
    output_dir: Path,
    filename: str = "battle_meta.json",
    indent: Optional[int] = None,
) -> Path:
    """Write a compact, client-sized BattleMeta JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    # Keep the overview useful for ranking/detail screens without publishing
    # source-scale EV and teammate tails for every Pokémon.
    json_data = data.model_dump(mode="json")
    json_data["pokemon_usage"] = [
        _trim_public_usage(pokemon) for pokemon in json_data["pokemon_usage"]
    ]
    _dump_json(json_data, output_path, indent)

    logger.info(f"Wrote battle meta to {output_path}")
    return output_path


def write_pokemon_files(
    pokemon_list: list[PokemonUsage],
    output_dir: Path,
    indent: Optional[int] = None,
) -> list[Path]:
    """Write compact per-Pokémon JSON files capped to current client limits."""
    pokemon_dir = output_dir / "pokemon"
    pokemon_dir.mkdir(parents=True, exist_ok=True)

    written_files = []
    # Track which dex_id values we've already written to detect collisions where
    # two different source rows would clobber the same {dex_id}.json file.
    written_by_id: dict[int, str] = {}

    for pokemon in pokemon_list:
        if pokemon.dex_id <= 0:
            logger.warning(f"Skipping {pokemon.name} - invalid dex_id")
            continue

        prior = written_by_id.get(pokemon.dex_id)
        if prior is not None and prior != pokemon.name:
            raise ValueError(
                f"dex_id collision: {pokemon.dex_id}.json would be written for "
                f"both {prior!r} and {pokemon.name!r}. Fix the name resolver or "
                f"data source so distinct forms get distinct ids."
            )
        written_by_id[pokemon.dex_id] = pokemon.name

        detail = PokemonDetail(
            dex_id=pokemon.dex_id,
            name=pokemon.name,
            form=pokemon.form,
            competitive=PokemonCompetitive(
                usage_rank=pokemon.rank,
                usage_rate=pokemon.usage_rate,
                win_rate=pokemon.win_rate,
                moves=pokemon.top_moves[:PUBLIC_LIST_LIMIT],
                items=pokemon.top_items[:PUBLIC_LIST_LIMIT],
                abilities=pokemon.top_abilities,
                teammates=pokemon.top_teammates[:PUBLIC_LIST_LIMIT],
                tera_types=pokemon.top_tera_types,
                spreads=[],
            ),
        )

        output_path = pokemon_dir / f"{pokemon.dex_id}.json"
        json_data = detail.model_dump(mode="json")
        # Existing clients treat a missing spreads collection as empty.
        json_data["competitive"].pop("spreads", None)
        _dump_json(json_data, output_path, indent)
        written_files.append(output_path)

    logger.info(f"Wrote {len(written_files)} Pokémon files to {pokemon_dir}")
    return written_files


def validate_output(output_path: Path) -> bool:
    """Validate an output JSON file against the BattleMeta schema."""
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        BattleMeta.model_validate(data)
        logger.info(f"Validation passed for {output_path}")
        return True
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    except Exception as e:
        raise ValueError(f"Schema validation failed: {e}")
