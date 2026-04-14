# Pokémon Champions Scraper

Scrapes competitive battle metadata (usage stats, tier lists, rankings) from [Pikalytics](https://pikalytics.com) and outputs structured JSON for [Pocket-Gallery](https://github.com/user/pocket-gallery) mobile apps.

## 🎯 Live API

- **Landing Page:** https://eurekaffeine.github.io/pokemon-champions-scraper/
- **Battle Meta:** https://eurekaffeine.github.io/pokemon-champions-scraper/battle_meta.json
- **Per-Pokémon:** https://eurekaffeine.github.io/pokemon-champions-scraper/pokemon/{dex_id}.json

## Features

- 📊 Scrapes Pikalytics AI markdown API for competitive data
- 🔄 Weekly automated updates via GitHub Actions (Mondays 2 AM UTC)
- 📱 JSON output optimized for mobile app consumption
- 🏆 Pokémon usage rates, moves, items, abilities, teammates
- 🔔 Optional Telegram notifications on scrape completion

## Quick Start

```bash
# Clone
git clone https://github.com/eurekaffeine/pokemon-champions-scraper.git
cd pokemon-champions-scraper

# Install dependencies
pip install -r requirements.txt

# Run scraper
python -m src.main scrape --limit 50

# Output in ./output/battle_meta.json
```

## CLI Usage

```bash
# Scrape from Pikalytics (default)
python -m src.main scrape --limit 50

# Scrape from multiple sources
python -m src.main scrape --source all

# Scrape without per-Pokémon detail files
python -m src.main scrape --no-per-pokemon

# Skip fetching per-Pokémon details (rankings only)
python -m src.main scrape --no-details

# Scrape with Telegram notification
python -m src.main scrape --notify

# Test a single scraper
python -m src.main test-scraper --source pikalytics

# Validate output
python -m src.main validate output/battle_meta.json
```

## Data Source

This scraper uses the **Pikalytics AI markdown API** (`/ai/pokedex/championstournaments`), which provides clean structured data for competitive Pokémon Champions tournaments.

**Update Frequency:** Pikalytics updates data **monthly** (check the `Data Date` field). The scraper runs weekly to catch month rollovers.

## Output Schema

### battle_meta.json

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-14T05:23:00Z",
  "season": {
    "id": "s1",
    "name": "Season 1",
    "start_date": "2026-04-08"
  },
  "pokemon_usage": [
    {
      "rank": 1,
      "dex_id": 727,
      "name": "Incineroar",
      "usage_rate": 0.5557,
      "top_moves": [
        { "name": "Fake Out", "usage": 0.989 },
        { "name": "Parting Shot", "usage": 0.965 }
      ],
      "top_items": [
        { "name": "Sitrus Berry", "usage": 0.556 }
      ],
      "top_abilities": [
        { "name": "Intimidate", "usage": 0.983 }
      ],
      "top_teammates": [
        { "name": "Sinistcha", "usage": 0.408 }
      ]
    }
  ],
  "sources": [
    { "name": "Pikalytics", "url": "https://www.pikalytics.com", "scraped_at": "..." }
  ]
}
```

### pokemon/{dex_id}.json

```json
{
  "dex_id": 727,
  "name": "Incineroar",
  "competitive": {
    "usage_rank": 1,
    "usage_rate": 0.5557,
    "moves": [...],
    "items": [...],
    "abilities": [...],
    "teammates": [...]
  }
}
```

---

## 📱 Mobile App Integration

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /battle_meta.json` | Full competitive metadata |
| `GET /pokemon/{dex_id}.json` | Per-Pokémon competitive data |

### Caching Strategy

Data updates **weekly** (source is monthly). Use conditional requests:

```kotlin
// Android (OkHttp)
val request = Request.Builder()
    .url(BATTLE_META_URL)
    .header("If-Modified-Since", lastFetchTimestamp)
    .build()
// 304 = use cache, 200 = new data
```

```swift
// iOS (URLSession)
let config = URLSessionConfiguration.default
config.requestCachePolicy = .useProtocolCachePolicy
```

```typescript
// HarmonyOS (ArkTS)
import http from '@ohos.net.http';
httpRequest.request(BATTLE_META_URL, {
  header: { 'If-Modified-Since': lastFetchTimestamp }
});
```

---

## GitHub Actions

### Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `scrape.yml` | **Mondays 2 AM UTC** | Scrape and deploy to gh-pages |
| `validate.yml` | On PR | Validate schema, dry-run scrape |

### Manual Trigger

Go to **Actions → Scrape and Deploy → Run workflow** with options:
- `limit`: Number of Pokémon (default: 100)
- `notify`: Send Telegram notification (default: false)

### Secrets (Optional)

For Telegram notifications:
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `TELEGRAM_CHAT_ID`: Target chat ID

---

## Configuration

```yaml
# config.yaml
scraper:
  user_agent: "PocketGallery-Scraper/1.0"
  request_delay_ms: 1000  # Be polite
  max_retries: 3
  timeout_seconds: 30

sources:
  pikalytics:
    enabled: true
  opgg:
    enabled: false  # Optional secondary source
```

## License

MIT
