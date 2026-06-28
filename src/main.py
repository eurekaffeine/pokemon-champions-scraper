# src/main.py
"""CLI entry point for Pokémon Champions scraper with multi-source support."""

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml

from src.models.schema import BattleMeta, Season, SourceInfo, TierList
from src.scrapers.base import BaseScraper, ScrapeStats
from src.scrapers.pikalytics import PikalyticsScraper
from src.scrapers.opgg import OPGGScraper
from src.merge import merge_scraped_data
from src.output import write_battle_meta, write_pokemon_files, validate_output


# Available scrapers registry
SCRAPERS = {
    "pikalytics": PikalyticsScraper,
    "opgg": OPGGScraper,
}


def setup_logging(level: str = "INFO", json_format: bool = False) -> logging.Logger:
    """
    Configure structured logging.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, output logs as JSON
    
    Returns:
        Root logger
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    if json_format:
        # JSON structured logging
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                if record.exc_info:
                    log_data["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_data)
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
    else:
        # Human-readable format
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    
    # Clear existing handlers and add new one
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file."""
    if not config_path.exists():
        logging.warning(f"Config file not found at {config_path}, using defaults")
        return {}
    
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


def get_enabled_sources(config: dict, source_filter: Optional[str] = None) -> list[str]:
    """Get list of enabled source names from config."""
    sources_config = config.get("sources", {})
    
    if source_filter:
        # Use specific source if requested
        if source_filter in SCRAPERS:
            return [source_filter]
        else:
            raise click.ClickException(f"Unknown source: {source_filter}. Available: {', '.join(SCRAPERS.keys())}")
    
    # Get enabled sources from config
    enabled = []
    for name, settings in sources_config.items():
        if name in SCRAPERS and settings.get("enabled", False):
            enabled.append(name)
    
    # Default to pikalytics if none enabled
    return enabled or ["pikalytics"]


async def send_telegram_notification(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """
    Send notification to Telegram.
    
    This is a placeholder - implement actual Telegram API call when bot is configured.
    
    Args:
        message: Message to send
        bot_token: Telegram bot token
        chat_id: Chat ID to send to
    
    Returns:
        True if sent successfully
    """
    logger = logging.getLogger(__name__)
    
    if not bot_token or not chat_id:
        logger.debug("Telegram notification skipped (not configured)")
        return False
    
    # TODO: Implement actual Telegram API call
    # import httpx
    # url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(url, json={"chat_id": chat_id, "text": message})
    #     return response.status_code == 200
    
    logger.info(f"Telegram notification: {message[:100]}...")
    return True


def format_summary_stats(
    source_stats: dict[str, ScrapeStats],
    merged_count: int,
    duration_ms: float,
) -> str:
    """Format summary statistics for logging/notification."""
    lines = ["📊 Scrape Summary"]
    lines.append(f"  Duration: {duration_ms/1000:.1f}s")
    lines.append(f"  Merged Pokémon: {merged_count}")
    lines.append("")
    
    total_requests = 0
    total_failed = 0
    
    for source_name, stats in source_stats.items():
        total_requests += stats.requests_made
        total_failed += stats.requests_failed
        
        lines.append(f"  {source_name}:")
        lines.append(f"    Requests: {stats.requests_made} ({stats.success_rate*100:.0f}% success)")
        lines.append(f"    Pokémon: {stats.pokemon_scraped} scraped, {stats.pokemon_failed} failed")
        
        if stats.errors:
            lines.append(f"    Errors: {len(stats.errors)}")
            for error in stats.errors[:3]:
                lines.append(f"      - {error[:60]}...")
    
    lines.append("")
    if total_failed > 0:
        lines.append(f"⚠️ Total failures: {total_failed}/{total_requests}")
    else:
        lines.append("✅ All requests successful")
    
    return "\n".join(lines)


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False, path_type=Path),
    default=Path("config.yaml"),
    help="Path to config file",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
@click.option(
    "--json-logs",
    is_flag=True,
    default=False,
    help="Output logs as JSON",
)
@click.pass_context
def cli(ctx, config: Path, log_level: str, json_logs: bool):
    """Pokémon Champions competitive data scraper."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)
    ctx.obj["logger"] = setup_logging(log_level, json_logs)


@cli.command()
@click.option("--limit", "-l", default=50, help="Number of Pokémon to scrape")
@click.option("--details/--no-details", default=True, help="Scrape per-Pokémon details")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("output"), help="Output directory")
@click.option("--per-pokemon/--no-per-pokemon", default=True, help="Write per-Pokémon JSON files")
@click.option(
    "--source", "-s",
    type=click.Choice(list(SCRAPERS.keys())),
    default=None,
    help="Run specific scraper only",
)
@click.option("--merge/--no-merge", default=True, help="Merge data from multiple sources")
@click.option("--notify/--no-notify", default=False, help="Send Telegram notification on completion")
@click.pass_context
def scrape(
    ctx,
    limit: int,
    details: bool,
    output: Path,
    per_pokemon: bool,
    source: Optional[str],
    merge: bool,
    notify: bool,
):
    """Run the scraper to fetch competitive data."""
    config = ctx.obj["config"]
    logger = ctx.obj["logger"]
    scraper_config = config.get("scraper", {})
    
    # Get enabled sources
    sources = get_enabled_sources(config, source)
    logger.info(f"Starting scrape with sources: {', '.join(sources)}")
    logger.info(f"  Limit: {limit}, Details: {details}, Merge: {merge}")
    
    async def run_scrape():
        import time
        start_time = time.time()
        
        all_results: dict[str, list] = {}
        all_stats: dict[str, ScrapeStats] = {}
        tier_lists: dict[str, TierList] = {}
        source_infos: list[SourceInfo] = []
        season_model: Optional[Season] = None
        
        for source_name in sources:
            scraper_class = SCRAPERS[source_name]
            scraper: BaseScraper = scraper_class(
                user_agent=scraper_config.get("user_agent", "PocketGallery-Scraper/1.0"),
                request_delay_ms=scraper_config.get("request_delay_ms", 1000),
                max_retries=scraper_config.get("max_retries", 3),
                timeout_seconds=scraper_config.get("timeout_seconds", 30),
            )
            
            logger.info(f"Scraping from {scraper.name}...")
            
            try:
                pokemon_list = await scraper.scrape(limit=limit, include_details=details)
                all_results[scraper.name] = pokemon_list
                all_stats[scraper.name] = scraper.get_stats()
                
                # Get tier list if scraper supports it
                if hasattr(scraper, "scrape_tier_list"):
                    try:
                        tier_list = await scraper.scrape_tier_list()
                        if any([tier_list.S, tier_list.A, tier_list.B]):
                            tier_lists[scraper.name] = tier_list
                    except Exception as e:
                        logger.warning(f"Failed to scrape tier list from {scraper.name}: {e}")
                
                source_infos.append(SourceInfo(
                    name=scraper.name,
                    url=scraper.base_url,
                    scraped_at=datetime.now(timezone.utc),
                ))

                # Capture season/regulation metadata from the first source
                # that can provide it (avoids a fabricated "Season 1").
                if season_model is None and hasattr(scraper, "scrape_season"):
                    try:
                        season_model = scraper.season_info_to_model(
                            await scraper.scrape_season()
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Could not derive season from {scraper.name}: {exc}"
                        )
                
                logger.info(f"  {scraper.name}: {len(pokemon_list)} Pokémon scraped")
                
            except Exception as e:
                logger.error(f"Failed to scrape from {scraper.name}: {e}")
                all_stats[scraper.name] = ScrapeStats(errors=[str(e)])
        
        if not all_results:
            return None, all_stats, 0
        
        # Merge or use single source
        if merge and len(all_results) > 1:
            logger.info("Merging data from multiple sources...")
            pokemon_list, tier_list = merge_scraped_data(
                all_results,
                tier_lists if tier_lists else None,
            )
        else:
            # Use first (or only) source
            source_name = next(iter(all_results.keys()))
            pokemon_list = all_results[source_name]
            tier_list = tier_lists.get(source_name)
        
        # Build BattleMeta. The apps decode `season` as a non-optional field
        # (iOS would fail to parse the whole document on null), so guarantee a
        # Season object even if live parsing failed.
        now = datetime.now(timezone.utc)
        if season_model is None:
            logger.warning(
                "Season metadata unavailable; emitting fallback season so the "
                "output stays decodable by clients that require a season."
            )
            season_model = Season(
                id="regmb-s3",
                name="Regulation Set M-B S3",
                format_code="battledataregmbs3",
                data_date=f"{now.year}-{now.month:02d}",
                start_date=now.date().replace(day=1),
                end_date=None,
            )
        battle_meta = BattleMeta(
            schema_version="1.0.0",
            updated_at=now,
            season=season_model,
            pokemon_usage=pokemon_list,
            tier_list=tier_list,
            sources=source_infos,
        )
        
        duration_ms = (time.time() - start_time) * 1000
        return battle_meta, all_stats, duration_ms
    
    # Run async scrape
    battle_meta, all_stats, duration_ms = asyncio.run(run_scrape())
    
    # Log summary
    if battle_meta:
        summary = format_summary_stats(
            all_stats,
            len(battle_meta.pokemon_usage),
            duration_ms,
        )
        for line in summary.split("\n"):
            logger.info(line)
    
    if not battle_meta:
        logger.error("Scrape failed, no output written")
        
        if notify:
            asyncio.run(send_telegram_notification(
                f"❌ Pokémon Champions scrape failed\nSources: {', '.join(sources)}",
                config.get("telegram", {}).get("bot_token"),
                config.get("telegram", {}).get("chat_id"),
            ))
        
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
    
    # Send notification
    if notify:
        asyncio.run(send_telegram_notification(
            f"✅ Pokémon Champions scrape complete\n"
            f"Sources: {', '.join(sources)}\n"
            f"Pokémon: {len(battle_meta.pokemon_usage)}\n"
            f"Duration: {duration_ms/1000:.1f}s",
            config.get("telegram", {}).get("bot_token"),
            config.get("telegram", {}).get("chat_id"),
        ))
    
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
def sources():
    """List available data sources."""
    click.echo("Available sources:")
    for name, scraper_class in SCRAPERS.items():
        scraper = scraper_class()
        click.echo(f"  {name}: {scraper.name} ({scraper.base_url})")


@cli.command()
def version():
    """Show version information."""
    click.echo("pokemon-champions-scraper v0.2.0")


if __name__ == "__main__":
    cli()
