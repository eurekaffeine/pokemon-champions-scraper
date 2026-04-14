# Pokémon Champions Scraper

Scrapes competitive battle metadata (usage stats, tier lists, rankings) from public sources and outputs structured JSON for [Pocket-Gallery](https://github.com/user/pocket-gallery) mobile apps.

## Features

- 📊 Scrapes Pikalytics, OP.GG, and Game8 for competitive data
- 🔄 Daily automated updates via GitHub Actions
- 📱 JSON output optimized for mobile app consumption
- 🏆 Pokémon usage rates, moves, items, teammates, tier lists

## Quick Start

```bash
# Clone
git clone https://github.com/user/pokemon-champions-scraper.git
cd pokemon-champions-scraper

# Install dependencies
pip install -r requirements.txt

# Run scraper
python -m src.main

# Output in ./output/battle_meta.json
```

## Output

See [PLAN.md](./PLAN.md) for full schema documentation.

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-14T02:00:00Z",
  "pokemon_usage": [
    {
      "rank": 1,
      "dex_id": 445,
      "name": "Garchomp",
      "usage_rate": 0.342,
      "top_moves": [...]
    }
  ]
}
```

## Configuration

Edit `config.yaml` to customize sources, rate limits, and output options.

## License

MIT
