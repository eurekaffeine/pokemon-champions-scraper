# Pokémon Champions Scraper

Scrapes competitive battle metadata (usage stats, tier lists, rankings) from public sources and outputs structured JSON for [Pocket-Gallery](https://github.com/user/pocket-gallery) mobile apps.

## Features

- 📊 Scrapes Pikalytics, OP.GG, and Game8 for competitive data
- 🔄 Daily automated updates via GitHub Actions (2 AM UTC)
- 📱 JSON output optimized for mobile app consumption
- 🏆 Pokémon usage rates, moves, items, teammates, tier lists
- 🔔 Optional Telegram notifications on scrape completion

## Quick Start

```bash
# Clone
git clone https://github.com/user/pokemon-champions-scraper.git
cd pokemon-champions-scraper

# Install dependencies
pip install -r requirements.txt

# Run scraper
python -m src.main scrape --limit 100

# Output in ./output/battle_meta.json
```

## CLI Usage

```bash
# Scrape with custom limit
python -m src.main scrape --limit 50

# Scrape without per-Pokémon files
python -m src.main scrape --no-per-pokemon

# Scrape with notification
python -m src.main scrape --notify

# Validate output
python -m src.main validate output/battle_meta.json

# Show version
python -m src.main version
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

---

## 📱 API Contract for Mobile Apps

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /battle_meta.json` | Full competitive metadata |
| `GET /pokemon/{dex_id}.json` | Per-Pokémon competitive data |

### Base URLs

- **GitHub Pages:** `https://{user}.github.io/pokemon-champions-scraper/`
- **CDN (if configured):** `https://your-cdn-domain.com/`

### Response Format

All responses are JSON with UTF-8 encoding.

#### battle_meta.json

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-14T02:00:00Z",
  "season": { "id": "s1", "name": "Season 1", ... },
  "pokemon_usage": [...],
  "tier_list": { "S": [...], "A": [...], ... },
  "sources": [...]
}
```

#### pokemon/{dex_id}.json

```json
{
  "dex_id": 445,
  "name": "Garchomp",
  "competitive": {
    "usage_rank": 1,
    "usage_rate": 0.342,
    "win_rate": 0.528,
    "moves": [...],
    "items": [...],
    "spreads": [...]
  }
}
```

### Update Schedule

Data is refreshed **daily at 2 AM UTC** via GitHub Actions.

---

## 🚀 CDN & Caching Recommendations

### For GitHub Pages

GitHub Pages automatically serves with reasonable cache headers. For optimal mobile app performance:

1. **Use conditional requests** — Send `If-Modified-Since` header with the last fetch timestamp
2. **Cache locally** — Store JSON in app cache, refresh on 200, skip refresh on 304
3. **Respect `updated_at`** — Check the field to know if data changed

### For CDN Deployment (Cloudflare, Fastly, etc.)

If hosting on a CDN, configure these cache headers:

```
Cache-Control: public, max-age=3600, stale-while-revalidate=86400
ETag: "{hash-of-content}"
Last-Modified: {updated_at-value}
```

**Recommended settings:**
| Header | Value | Rationale |
|--------|-------|-----------|
| `max-age` | 3600 (1 hour) | Frequent enough for competitive meta |
| `stale-while-revalidate` | 86400 (24 hours) | Serve stale while fetching fresh |
| `ETag` | Content hash | Enable conditional requests |

### Mobile App Caching Strategy

#### Android (OkHttp)

```kotlin
val client = OkHttpClient.Builder()
    .cache(Cache(cacheDir, 10 * 1024 * 1024)) // 10 MB
    .build()

val request = Request.Builder()
    .url(BATTLE_META_URL)
    .header("If-Modified-Since", lastFetchTimestamp)
    .build()

// Response 304 = use cache, 200 = new data
```

#### iOS (URLSession)

```swift
let config = URLSessionConfiguration.default
config.requestCachePolicy = .useProtocolCachePolicy

let request = URLRequest(url: battleMetaURL)
// URLSession handles If-Modified-Since automatically with caching
```

#### HarmonyOS (ArkTS)

```typescript
import http from '@ohos.net.http';

let httpRequest = http.createHttp();
httpRequest.request(BATTLE_META_URL, {
  header: { 'If-Modified-Since': lastFetchTimestamp },
  readTimeout: 30000,
  connectTimeout: 30000
});
```

### Versioning

The `schema_version` field uses semantic versioning:

- **Patch (1.0.x):** Bug fixes, no breaking changes
- **Minor (1.x.0):** New fields added, backward compatible
- **Major (x.0.0):** Breaking changes, app update required

Apps should check `schema_version` and handle gracefully if unexpected.

---

## Configuration

Edit `config.yaml` to customize sources, rate limits, and output options.

```yaml
scraper:
  user_agent: "PocketGallery-Scraper/1.0"
  request_delay_ms: 1000
  max_retries: 3
  timeout_seconds: 30

# Optional: Telegram notifications
notify:
  telegram_bot_token: "YOUR_BOT_TOKEN"  # or set TELEGRAM_BOT_TOKEN env var
  telegram_chat_id: "YOUR_CHAT_ID"       # or set TELEGRAM_CHAT_ID env var
```

## GitHub Actions

The scraper runs automatically via GitHub Actions:

- **Daily scrape:** `.github/workflows/scrape.yml` — Runs at 2 AM UTC
- **PR validation:** `.github/workflows/validate.yml` — Validates schema on PRs

### Manual Trigger

You can trigger a scrape manually from the Actions tab with custom parameters:
- `limit`: Number of Pokémon to scrape (default: 100)
- `notify`: Send Telegram notification (default: false)

### Secrets Required

For notifications, add these secrets to your repository:
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token from @BotFather
- `TELEGRAM_CHAT_ID`: The chat ID to send notifications to

---

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio mypy

# Run tests
pytest tests/ -v

# Type check
mypy src/ --ignore-missing-imports
```

## License

MIT
