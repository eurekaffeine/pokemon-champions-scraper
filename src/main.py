# src/main.py
"""CLI entry point for Pokémon Champions scraper."""

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml

from src.models.schema import BattleMeta, Season, SourceInfo, TierList
from src.scrapers.pikalytics import PikalyticsScraper
from src.scrapers.opgg import OPGGScraper
from src.scrapers.base import BaseScraper, ScraperError
from src.merge import merge_scraper_results
from src.output import write_battle_meta, write_pokemon_files, validate_output
from src.notify import send_telegram_notification, format_scrape_result

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


def get_scraper(name: str, config: dict) -> BaseScraper:
    """Get a scraper instance by name."""
    scraper_config = config.get("scraper", {})
    
    common_kwargs = {
        "user_agent": scraper_config.get("user_agent", "PocketGallery-Scraper/1.0"),
        "request_delay_ms": scraper_config.get("request_delay_ms", 1000),
        "max_retries": scraper_config.get("max_retries", 3),
        "timeout_seconds": scraper_config.get("timeout_seconds", 30),
    }
    
    if name.lower() == "pikalytics":
        return PikalyticsScraper(**common_kwargs)
    elif name.lower() == "opgg":
        return OPGGScraper(**common_kwargs)
    else:
        raise ValueError(f"Unknown scraper: {name}")


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False, path_type=Path),
    default=Path("config.yaml"),
    help="Path to config file",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable debug logging",
)
@click.pass_context
def cli(ctx, config: Path, verbose: bool):
    """Pokémon Champions competitive data scraper."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.option("--limit", "-l", default=50, help="Number of Pokémon to scrape")
@click.option("--details/--no-details", default=True, help="Scrape per-Pokémon details")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("output"), help="Output directory")
@click.option("--per-pokemon/--no-per-pokemon", default=True, help="Write per-Pokémon JSON files")
@click.option("--source", "-s", multiple=True, type=click.Choice(["pikalytics", "opgg", "all"]), default=["pikalytics"], help="Data sources to scrape")
@click.option("--notify/--no-notify", default=False, help="Send Telegram notification on completion")
@click.pass_context
def scrape(ctx, limit: int, details: bool, output: Path, per_pokemon: bool, source: tuple, notify: bool):
    """Run the scraper to fetch competitive data."""
    config = ctx.obj["config"]
    start_time = time.time()
    
    # Expand "all" to all sources
    sources = set(source)
    if "all" in sources:
        sources = {"pikalytics", "opgg"}
    
    logger.info("Starting scrape...")
    logger.info(f"  Limit: {limit}")
    logger.info(f"  Details: {details}")
    logger.info(f"  Sources: {', '.join(sources)}")
    logger.info(f"  Output: {output}")
    
    # Track results
    scrape_results = {}
    opgg_tier_list = None
    source_infos = []
    errors = []
    
    async def run_scrape():
        nonlocal opgg_tier_list
        
        for source_name in sources:
            try:
                scraper = get_scraper(source_name, config)
                logger.info(f"Running {scraper.name} scraper...")
                
                pokemon_list = await scraper.scrape(limit=limit, include_details=details)
                scrape_results[source_name] = pokemon_list
                
                source_infos.append(SourceInfo(
                    name=scraper.name,
                    url=scraper.base_url,
                    scraped_at=datetime.now(timezone.utc),
                ))
                
                # Get tier list from OP.GG
                if source_name == "opgg" and hasattr(scraper, "scrape_tier_list"):
                    opgg_tier_list = await scraper.scrape_tier_list()
                
                logger.info(f"  {scraper.name}: scraped {len(pokemon_list)} Pokémon")
                
            except ScraperError as e:
                logger.error(f"  {source_name}: scrape failed - {e}")
                errors.append(f"{source_name}: {e}")
            except Exception as e:
                logger.error(f"  {source_name}: unexpected error - {e}")
                errors.append(f"{source_name}: {e}")
    
    # Run async scrape
    asyncio.run(run_scrape())
    
    # Merge results
    if len(scrape_results) == 0:
        logger.error("All scrapers failed, no output written")
        if notify:
            _send_notification(config, False, 0, time.time() - start_time, "All scrapers failed")
        sys.exit(1)
    
    if len(scrape_results) == 1:
        source_name = list(scrape_results.keys())[0]
        merged_pokemon = scrape_results[source_name]
        tier_list = TierList() if opgg_tier_list else None
    else:
        logger.info("Merging data from multiple sources...")
        merged_pokemon, tier_list = merge_scraper_results(
            pikalytics_data=scrape_results.get("pikalytics"),
            opgg_data=scrape_results.get("opgg"),
            opgg_tier_list=opgg_tier_list,
        )
    
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
        pokemon_usage=merged_pokemon,
        tier_list=tier_list,
        sources=source_infos,
    )
    
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
        if notify:
            _send_notification(config, False, 0, time.time() - start_time, str(e))
        sys.exit(1)
    
    duration = time.time() - start_time
    pokemon_count = len(battle_meta.pokemon_usage)
    
    # Print summary
    click.echo(f"\n{'='*50}")
    click.echo(f"✓ Scrape complete!")
    click.echo(f"  Pokémon: {pokemon_count}")
    click.echo(f"  Sources: {', '.join(s.name for s in source_infos)}")
    click.echo(f"  Duration: {duration:.1f}s")
    if errors:
        click.echo(f"  Warnings: {len(errors)}")
        for err in errors:
            click.echo(f"    - {err}")
    click.echo(f"{'='*50}")
    
    # Send notification
    if notify:
        _send_notification(config, True, pokemon_count, duration, None)


def _send_notification(config: dict, success: bool, count: int, duration: float, error: Optional[str]):
    """Send Telegram notification if configured."""
    import os
    
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("notify", {}).get("telegram_bot_token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or config.get("notify", {}).get("telegram_chat_id")
    
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not configured, skipping notification")
        return
    
    message = format_scrape_result(success, count, duration, error)
    send_telegram_notification(message, chat_id, bot_token)


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
@click.option("--source", "-s", type=click.Choice(["pikalytics", "opgg"]), required=True, help="Source to test")
@click.pass_context
def test_scraper(ctx, source: str):
    """Test a single scraper with minimal requests."""
    config = ctx.obj["config"]
    
    async def test():
        scraper = get_scraper(source, config)
        click.echo(f"Testing {scraper.name} scraper...")
        
        try:
            rankings = await scraper.scrape_rankings(limit=5)
            click.echo(f"✓ Rankings: {len(rankings)} Pokémon")
            for p in rankings[:3]:
                click.echo(f"  #{p.rank} {p.name} ({p.usage_rate:.1%})")
            
            if rankings:
                detail = await scraper.scrape_pokemon_detail(rankings[0].name)
                if detail:
                    click.echo(f"✓ Details for {rankings[0].name}:")
                    click.echo(f"  Moves: {len(detail.top_moves)}")
                    click.echo(f"  Items: {len(detail.top_items)}")
                else:
                    click.echo("✗ No details returned")
        except Exception as e:
            click.echo(f"✗ Error: {e}", err=True)
            sys.exit(1)
    
    asyncio.run(test())


@cli.command()
def version():
    """Show version information."""
    click.echo("pokemon-champions-scraper v0.1.0")


if __name__ == "__main__":
    cli()
