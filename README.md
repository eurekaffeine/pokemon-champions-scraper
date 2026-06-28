# Pokémon Champions Scraper

Scrapes competitive battle metadata (usage stats, tier lists, rankings) from [Pikalytics](https://pikalytics.com) and outputs structured JSON for [Pocket-Gallery](https://github.com/eurekaffeine/Pocket-Gallery) mobile apps.

## 🎯 Live API

- **Landing Page:** https://eurekaffeine.github.io/pokemon-champions-scraper/
- **Battle Meta:** https://eurekaffeine.github.io/pokemon-champions-scraper/battle_meta.json
- **Per-Pokémon:** https://eurekaffeine.github.io/pokemon-champions-scraper/pokemon/{dex_id}.json

## Features

- 📊 **~208 Pokémon** from the Reg M-B S3 ranked-ladder feed (full meta coverage)
- 🔄 Weekly automated updates via GitHub Actions (Mondays 2 AM UTC)
- 📱 JSON output optimized for mobile app consumption
- 🏆 Complete competitive data: moves, items, abilities, teammates
- 🔔 Optional Telegram notifications on scrape completion
- 🆔 ID-only format (no hardcoded names) for easy localization

## Data Coverage

| Data Type | Count | Source |
|-----------|-------|--------|
| Pokémon | 211 | List API |
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

## Data Source

This scraper reads the Pokémon Champions **ranked-ladder** feed that Pikalytics
labels *"Regulation Set M-B S3 Ranked Battle Data"* (format code
`battledataregmbs3`). We use the ranked-ladder feed rather than the
`championstournaments` tournament feed because it:

- has **larger, cleaner sample sizes** (ladder-wide game counts),
- exposes **richer detail** (EV spreads + natures are present in the feed for a
  future enhancement), and
- does **not** split Mega forms into separate rows — which previously caused
  `dex_id` collisions (e.g. `Floette-Eternal-Mega` and `Floette-Eternal` both
  collapsing onto one id and silently overwriting each other).

Two Pikalytics endpoints are used:

1. **List API** (`/api/l/{YYYY-MM}/battledataregmbs3-1760`)
   - Returns all ranked Pokémon (~208) with win rates, sample sizes, and
     (for the very top entry) embedded detail.
   - Single request, fast.

2. **AI Markdown API** (`/ai/pokedex/battledataregmbs3/{pokemon}`)
   - Per-Pokémon details: moves, items, abilities, teammates.
   - One request per Pokémon (rate-limited).

### Usage rate & ranking

The ranked-ladder feed reports usage as a **raw game count** (`games`), not a
pick-rate percentage. `usage_rate` is therefore derived as each Pokémon's share
of the total games in the snapshot, and `rank` is re-assigned by that derived
usage so that `rank` is always the ordinal of `usage_rate` (strictly
descending). Pikalytics' own ladder `rank` is intentionally **not** used, as it
is not monotonic with the game count.

> **Teammates:** this feed does not expose teammate usage percentages
> (the list API gives teammate *rank* only, and the markdown reports
> `undefined%`). Teammates are emitted in source order (most common first)
> with `usage = 0.0` to signal "percentage unavailable".

**Update Frequency:** Pikalytics publishes monthly (see the `Data Date` /
`data_date` field). The scraper runs daily to catch month rollovers. It refuses
to fall back to the current wall-clock month, since that month is frequently
empty and would otherwise overwrite good data.

## Output Schema

### battle_meta.json

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-16T05:23:00Z",
  "season": {
    "id": "regmb-s3",
    "name": "Regulation Set M-B S3",
    "format_code": "battledataregmbs3",
    "data_date": "2026-05",
    "start_date": "2026-05-01",
    "end_date": null
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
| Floette-Eternal | Eternal Flower | 10061 |
| Tauros-Paldea | Combat | 10250 |
| Tauros-Paldea-Blaze | Blaze | 10251 |
| Tauros-Paldea-Aqua | Aqua | 10252 |
| Meowstic-F | Female | 10025 |
| Basculegion-F | Female | 10248 |
| Palafin-Hero | Hero | 10256 |
| Calyrex-Shadow-Rider | Shadow | 10194 |
| Mr-Rime | — | 866 |

Form variants without separate asset files (e.g., Vivillon-High Plains,
Tatsugiri-Droopy, Sinistcha-Masterpiece, Maushold-Four) map to their base form ID.

### Why form IDs, not National Dex numbers?

`dex_id` (and per-Pokémon filenames `pokemon/{dex_id}.json`) use the Pocket-Gallery
**asset id**, which for form-changing Pokémon is an internal form id (e.g.
`Floette-Eternal` → `10061`, `Rotom-Wash` → `10009`), **not** the National Dex
number (Floette is #670; Rotom is #479).

This is deliberate and required by the apps:

- The apps build the request URL as `pokemon/{dex_id}.json` using the `dex_id`
  value **verbatim** (and likewise for teammate `id`s). The filename, the
  `dex_id` field, and teammate ids are a single join key.
- The apps' **local** Pokédex assets are keyed the same way — `670.json` *and*
  `10061.json` both exist locally, and `getPokemonDexById` resolves form ids via
  a dedicated form map. Champions `dex_id` is the join into that map.
- Re-keying to National Dex numbers would **break** this join and is impossible
  for multi-form species anyway (Rotom-Wash/Heat/Mow/Frost/Fan would all collide
  on `479.json`).

The human-readable form is additionally surfaced in the `form` field (e.g.
`"eternal"`, `"wash"`), but it is metadata only — the numeric id is the key.

These IDs match the Pokédex asset system used by Pocket-Gallery.

## License

MIT
