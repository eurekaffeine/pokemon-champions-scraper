# Pokémon Champions Scraper

Scrapes competitive battle metadata (usage stats, tier lists, rankings) from [Pikalytics](https://pikalytics.com) and outputs structured JSON for [Pocket-Gallery](https://github.com/eurekaffeine/Pocket-Gallery) mobile apps.

## 🎯 Live API

- **Landing Page:** https://eurekaffeine.github.io/pokemon-champions-scraper/
- **Battle Meta:** https://eurekaffeine.github.io/pokemon-champions-scraper/battle_meta.json
- **Per-Pokémon:** https://eurekaffeine.github.io/pokemon-champions-scraper/pokemon/{dex_id}.json

## Features

- 📊 **187 Pokémon** scraped from Pikalytics (full meta coverage)
- 🔄 Weekly automated updates via GitHub Actions (Mondays 2 AM UTC)
- 📱 JSON output optimized for mobile app consumption
- 🏆 Complete competitive data: moves, items, abilities, teammates
- 🔔 Optional Telegram notifications on scrape completion
- 🆔 ID-only format (no hardcoded names) for easy localization

## Data Coverage

| Data Type | Count | Source |
|-----------|-------|--------|
| Pokémon | 187 | List API |
| Moves per Pokémon | ~10 | AI Markdown |
| Items per Pokémon | ~10 | AI Markdown |
| Abilities per Pokémon | 3-5 | AI Markdown |
| Teammates per Pokémon | 6-12 | List API |

## Quick Start

```bash
# Clone
git clone https://github.com/eurekaffeine/pokemon-champions-scraper.git
cd pokemon-champions-scraper

# Install dependencies
pip install -r requirements.txt

# Run scraper (default: 200 Pokémon)
python -m src.main scrape --limit 200

# Output in ./output/battle_meta.json
```

## CLI Usage

```bash
# Scrape with custom limit
python -m src.main scrape --limit 100

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

## Data Sources

This scraper uses **two Pikalytics APIs**:

1. **List API** (`/api/l/{date}/championstournaments-1760`)
   - Returns all 187 Pokémon with rankings, usage rates, and teammates
   - Single request, fast

2. **AI Markdown API** (`/ai/pokedex/championstournaments/{pokemon}`)
   - Returns per-Pokémon details: moves, items, abilities
   - One request per Pokémon (rate-limited)

**Update Frequency:** Pikalytics updates data **monthly** (check the `Data Date` field). The scraper runs weekly to catch month rollovers.

## Output Schema

### battle_meta.json

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-16T05:23:00Z",
  "season": {
    "id": "s1",
    "name": "Pokemon Champions VGC 2026 Tournament",
    "start_date": "2026-04-08"
  },
  "pokemon_usage": [
    {
      "rank": 1,
      "dex_id": 727,
      "name": "Incineroar",
      "usage_rate": 0.5437
    }
  ],
  "sources": [
    { "name": "Pikalytics", "url": "https://www.pikalytics.com", "scraped_at": "..." }
  ]
}
```

### pokemon/{dex_id}.json

Uses **ID-only format** for localization:

```json
{
  "dex_id": 727,
  "name": "Incineroar",
  "form": null,
  "competitive": {
    "usage_rank": 1,
    "usage_rate": 0.5437,
    "win_rate": null,
    "moves": [
      { "id": 252, "usage": 0.99 },
      { "id": 575, "usage": 0.96 }
    ],
    "items": [
      { "id": 158, "usage": 0.56 }
    ],
    "abilities": [
      { "id": 22, "usage": 0.98 }
    ],
    "teammates": [
      { "id": 1013, "usage": 0.39 }
    ]
  }
}
```

**Note:** `moves[].id`, `items[].id`, `abilities[].id` are numeric IDs that map to your app's localized strings. No hardcoded English names in the output.

---

## 📱 Mobile App Integration

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /battle_meta.json` | Overview with all Pokémon rankings |
| `GET /pokemon/{dex_id}.json` | Detailed competitive data for one Pokémon |

### Example: Fetch Incineroar Data

```bash
curl https://eurekaffeine.github.io/pokemon-champions-scraper/pokemon/727.json
```

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
- `limit`: Number of Pokémon (default: 200)
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
  request_delay_ms: 1000  # Be polite to Pikalytics
  max_retries: 3
  timeout_seconds: 30

sources:
  pikalytics:
    enabled: true
```

## Form Variant ID Mapping

Some Pokémon have regional/mega forms with special IDs:

| Pokémon | Form | Dex ID |
|---------|------|--------|
| Rotom-Wash | Wash | 10009 |
| Rotom-Heat | Heat | 10010 |
| Ninetales-Alola | Alola | 10104 |
| Arcanine-Hisui | Hisui | 10229 |

These IDs match the Pokédex asset system used by Pocket-Gallery.

## License

MIT
