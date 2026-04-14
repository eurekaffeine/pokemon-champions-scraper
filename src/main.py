# src/main.py
"""CLI entry point for Pokémon Champions scraper."""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from src.models.schema import BattleMeta, Season, SourceInfo
from src.scrapers.pikalytics import PikalyticsScraper
from src.output import write_battle_meta, write_pokemon_files, validate_output

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file."""
    if not config_path.exists():
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return {}
    
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False, path_type=Path),
    default=Path("config.yaml"),
    help="Path to config file",
)
@click.pass_context
def cli(ctx, config: Path):
    """Pokémon Champions competitive data scraper."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)


@cli.command()
@click.option("--limit", "-l", default=50, help="Number of Pokémon to scrape")
@click.option("--details/--no-details", default=True, help="Scrape per-Pokémon details")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("output"), help="Output directory")
@click.option("--per-pokemon/--no-per-pokemon", default=True, help="Write per-Pokémon JSON files")
@click.pass_context
def scrape(ctx, limit: int, details: bool, output: Path, per_pokemon: bool):
    """Run the scraper to fetch competitive data."""
    config = ctx.obj["config"]
    scraper_config = config.get("scraper", {})
    
    logger.info("Starting scrape...")
    logger.info(f"  Limit: {limit}")
    logger.info(f"  Details: {details}")
    logger.info(f"  Output: {output}")
    
    async def run_scrape():
        # Initialize scraper with config
        scraper = PikalyticsScraper(
            user_agent=scraper_config.get("user_agent", "PocketGallery-Scraper/1.0"),
            request_delay_ms=scraper_config.get("request_delay_ms", 1000),
            max_retries=scraper_config.get("max_retries", 3),
            timeout_seconds=scraper_config.get("timeout_seconds", 30),
        )
        
        # Run scrape
        try:
            pokemon_list = await scraper.scrape(limit=limit, include_details=details)
        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return None
        
        if not pokemon_list:
            logger.warning("No data scraped")
            return None
        
        # Build BattleMeta
        now = datetime.now(timezone.utc)
        battle_meta = BattleMeta(
            schema_version="1.0.0",
            updated_at=now,
            season=Season(
                id="s1",
                name="Season 1",
                start_date=datetime(2026, 4, 8).date(),
                end_date=None,
            ),
            pokemon_usage=pokemon_list,
            sources=[
                SourceInfo(
                    name=scraper.name,
                    url=scraper.base_url,
                    scraped_at=now,
                ),
            ],
        )
        
        return battle_meta
    
    # Run async scrape
    battle_meta = asyncio.run(run_scrape())
    
    if not battle_meta:
        logger.error("Scrape failed, no output written")
        sys.exit(1)
    
    # Write output
    try:
        output_path = write_battle_meta(battle_meta, output)
        click.echo(f"✓ Wrote {output_path}")
        
        if per_pokemon:
            pokemon_paths = write_pokemon_files(battle_meta.pokemon_usage, output)
            click.echo(f"✓ Wrote {len(pokemon_paths)} Pokémon files")
        
        # Validate output
        validate_output(output_path)
        click.echo("✓ Validation passed")
        
    except Exception as e:
        logger.error(f"Failed to write output: {e}")
        sys.exit(1)
    
    click.echo(f"\n✓ Scrape complete! {len(battle_meta.pokemon_usage)} Pokémon scraped.")


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def validate(file: Path):
    """Validate a battle_meta.json file against the schema."""
    try:
        validate_output(file)
        click.echo(f"✓ {file} is valid")
    except ValueError as e:
        click.echo(f"✗ Validation failed: {e}", err=True)
        sys.exit(1)


@cli.command()
def version():
    """Show version information."""
    click.echo("pokemon-champions-scraper v0.1.0")


if __name__ == "__main__":
    cli()
