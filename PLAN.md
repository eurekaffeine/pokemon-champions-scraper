# Pokémon Champions Scraper — Implementation Plan

> **Goal:** Build a scraper that fetches competitive battle metadata (usage stats, tier lists, rankings) from public sources and outputs structured JSON for consumption by Pocket-Gallery mobile apps (Android, iOS, HarmonyOS).

---

## Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Data Sources   │     │    Scraper      │     │   Output/Host   │
│  - Pikalytics   │────▶│  (Python/cron)  │────▶│  - GitHub Pages │
│  - OP.GG        │     │                 │     │  - S3/R2 CDN    │
│  - Game8        │     └─────────────────┘     └─────────────────┘
└─────────────────┘                                     │
                                                        ▼
                                              ┌─────────────────┐
                                              │  Mobile Apps    │
                                              │  (fetch JSON)   │
                                              └─────────────────┘
```

---

## Data Schema

### Output: `battle_meta.json`

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-04-14T02:00:00Z",
  "season": {
    "id": "s1",
    "name": "Season 1",
    "start_date": "2026-04-08",
    "end_date": null
  },
  "pokemon_usage": [
    {
      "rank": 1,
      "dex_id": 445,
      "name": "Garchomp",
      "form": null,
      "usage_rate": 0.342,
      "win_rate": 0.528,
      "top_moves": [
        { "name": "Earthquake", "usage": 0.95 },
        { "name": "Dragon Claw", "usage": 0.82 },
        { "name": "Swords Dance", "usage": 0.71 },
        { "name": "Protect", "usage": 0.68 }
      ],
      "top_items": [
        { "name": "Choice Scarf", "usage": 0.45 },
        { "name": "Life Orb", "usage": 0.32 }
      ],
      "top_abilities": [
        { "name": "Rough Skin", "usage": 0.88 }
      ],
      "top_teammates": [
        { "dex_id": 591, "name": "Amoonguss", "usage": 0.34 },
        { "dex_id": 113, "name": "Chansey", "usage": 0.28 }
      ],
      "top_tera_types": [
        { "type": "Steel", "usage": 0.42 },
        { "type": "Fairy", "usage": 0.25 }
      ]
    }
  ],
  "tier_list": {
    "S": [445, 448, 149],
    "A": [591, 113, 812],
    "B": [...]
  },
  "rank_distribution": {
    "master_ball": 0.02,
    "ultra_ball": 0.08,
    "great_ball": 0.15,
    "poke_ball": 0.25,
    "beginner": 0.50
  },
  "sources": [
    { "name": "Pikalytics", "url": "https://pikalytics.com/champions", "scraped_at": "2026-04-14T02:00:00Z" },
    { "name": "OP.GG", "url": "https://op.gg/pokemon-champions", "scraped_at": "2026-04-14T02:05:00Z" }
  ]
}
```

### Output: `pokemon/{dex_id}.json` (per-Pokémon detail, optional)

For detailed views, we can generate individual files:

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
    "spreads": [
      { "nature": "Jolly", "evs": "252 Atk / 4 Def / 252 Spe", "usage": 0.65 }
    ]
  }
}
```

---

## Data Sources

| Source | URL | Data Available | Rate Limits |
|--------|-----|----------------|-------------|
| **Pikalytics** | `pikalytics.com/champions` | Usage stats, moves, items, teammates, spreads | Unknown, scrape politely |
| **OP.GG** | `op.gg/pokemon-champions` | Tier list, builds, stats | Unknown |
| **Game8** | `game8.co/games/Pokemon-Champions` | Guides, tier lists | Generous |
| **Serebii** | `serebii.net/pokemonchampions` | Pokémon availability, rules | Static, rarely changes |

### Scraping Strategy

1. **Pikalytics (Primary)** — Most comprehensive competitive data
   - Scrape `/champions/pokemon/{name}` for per-Pokémon stats
   - Scrape `/champions` main page for overall rankings
   
2. **OP.GG (Secondary)** — Cross-reference tier lists and win rates
   
3. **Game8 (Fallback)** — Human-curated tier lists for validation

---

## Project Structure

```
pokemon-champions-scraper/
├── PLAN.md                  # This file
├── README.md                # Setup & usage instructions
├── requirements.txt         # Python dependencies
├── .github/
│   └── workflows/
│       └── scrape.yml       # GitHub Actions cron workflow
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract scraper class
│   │   ├── pikalytics.py    # Pikalytics scraper
│   │   ├── opgg.py          # OP.GG scraper
│   │   └── game8.py         # Game8 scraper
│   ├── models/
│   │   ├── __init__.py
│   │   └── schema.py        # Pydantic models for output
│   ├── merge.py             # Merge data from multiple sources
│   └── output.py            # Write JSON files
├── output/                   # Generated JSON (git-ignored or separate branch)
│   ├── battle_meta.json
│   └── pokemon/
│       ├── 1.json
│       ├── 2.json
│       └── ...
├── tests/
│   └── ...
└── config.yaml              # Scraper configuration
```

---

## Implementation Tasks

### Phase 1: Core Scraper (MVP)

| Task | Description | Est. Time |
|------|-------------|-----------|
| 1.1 | Set up project structure, dependencies (`httpx`, `beautifulsoup4`, `pydantic`) | 30 min |
| 1.2 | Define Pydantic models for output schema | 1 hr |
| 1.3 | Implement Pikalytics scraper (main rankings page) | 2 hr |
| 1.4 | Implement Pikalytics scraper (per-Pokémon detail) | 2 hr |
| 1.5 | Implement JSON output writer | 30 min |
| 1.6 | Add CLI with `click` or `argparse` | 30 min |
| 1.7 | Test locally, validate output | 1 hr |

**Deliverable:** Working scraper that outputs `battle_meta.json`

### Phase 2: Multi-Source & Robustness

| Task | Description | Est. Time |
|------|-------------|-----------|
| 2.1 | Implement OP.GG scraper | 2 hr |
| 2.2 | Implement data merge logic (combine sources, resolve conflicts) | 1 hr |
| 2.3 | Add retry logic, rate limiting, error handling | 1 hr |
| 2.4 | Add logging and alerting (failed scrapes) | 30 min |

### Phase 3: Automation & Hosting

| Task | Description | Est. Time |
|------|-------------|-----------|
| 3.1 | Set up GitHub Actions workflow (daily cron) | 1 hr |
| 3.2 | Configure output to `gh-pages` branch or S3 bucket | 1 hr |
| 3.3 | Add cache headers / versioning for mobile apps | 30 min |
| 3.4 | Set up Telegram/Discord notification on scrape completion | 30 min |

### Phase 4: Mobile Integration

| Task | Description | Est. Time |
|------|-------------|-----------|
| 4.1 | Add data fetching layer to Pocket-Gallery (shared logic) | 2 hr |
| 4.2 | Implement caching (ETag / If-Modified-Since) | 1 hr |
| 4.3 | Build UI for competitive stats on Pokémon detail page | 3 hr |
| 4.4 | Build tier list / meta overview screen | 2 hr |

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Best scraping ecosystem |
| HTTP Client | `httpx` | Async support, modern API |
| HTML Parser | `beautifulsoup4` + `lxml` | Fast, reliable |
| Schema | `pydantic` v2 | Validation, JSON serialization |
| CLI | `click` | Clean interface |
| Scheduler | GitHub Actions | Free, no server needed |
| Hosting | GitHub Pages or Cloudflare R2 | Free/cheap, CDN-backed |

---

## Configuration

### `config.yaml`

```yaml
scraper:
  user_agent: "PocketGallery-Scraper/1.0 (+https://github.com/user/pocket-gallery)"
  request_delay_ms: 1000  # Be polite
  max_retries: 3
  timeout_seconds: 30

sources:
  pikalytics:
    enabled: true
    base_url: "https://pikalytics.com/champions"
  opgg:
    enabled: true
    base_url: "https://op.gg/pokemon-champions"
  game8:
    enabled: false  # Manual tier lists, less useful

output:
  format: json
  directory: ./output
  per_pokemon_files: true
  compress: false  # gzip for large files

schedule:
  cron: "0 2 * * *"  # Daily at 2 AM UTC
```

---

## Hosting Options

### Option A: GitHub Pages (Recommended for MVP)

1. Scraper runs via GitHub Actions
2. Outputs to `gh-pages` branch
3. JSON accessible at `https://{user}.github.io/pokemon-champions-scraper/battle_meta.json`

**Pros:** Free, simple, versioned via git
**Cons:** Public repo required for free Pages, 100MB limit

### Option B: Cloudflare R2 + Workers

1. Scraper uploads to R2 bucket
2. Workers handles CDN + cache headers
3. Custom domain support

**Pros:** Private, scalable, fast global CDN
**Cons:** Slightly more setup

### Option C: Bundle in App

1. JSON committed to Pocket-Gallery repo
2. Updated via PR on scraper completion
3. Ships with app binary

**Pros:** Works offline, no network dependency
**Cons:** Requires app update for data refresh

---

## Error Handling & Monitoring

- **Scrape failures:** Retry 3x with exponential backoff
- **Partial data:** Output what succeeded, log what failed
- **Alerting:** Send Telegram message on failure (via bot)
- **Validation:** Pydantic ensures output schema consistency
- **Diff detection:** Only update files if data changed (reduce noise)

---

## Mobile App Integration

### API Contract

Apps fetch from a single endpoint:

```
GET https://{host}/battle_meta.json
```

Headers:
- `If-Modified-Since` — for caching
- `Accept-Encoding: gzip` — if compressed

Response:
- `200 OK` + JSON body
- `304 Not Modified` — use cached

### Caching Strategy

| Platform | Approach |
|----------|----------|
| Android | OkHttp cache + ETag |
| iOS | URLSession cache + If-Modified-Since |
| HarmonyOS | @ohos.net.http with cache config |

### Data Layer (Pseudocode)

```kotlin
// Shared KMP or per-platform
class BattleMetaRepository(
    private val httpClient: HttpClient,
    private val cache: BattleMetaCache
) {
    suspend fun getUsageStats(): List<PokemonUsage> {
        val cached = cache.get()
        if (cached != null && !cached.isStale()) return cached.data
        
        val response = httpClient.get(BATTLE_META_URL)
        val data = response.parse<BattleMetaResponse>()
        cache.put(data)
        return data.pokemonUsage
    }
}
```

---

## Timeline

| Week | Milestone |
|------|-----------|
| Week 1 | Phase 1 complete — working Pikalytics scraper, JSON output |
| Week 2 | Phase 2 + 3 — multi-source, GitHub Actions automation |
| Week 3 | Phase 4 — mobile app integration, UI |

---

## Open Questions

1. **Data freshness requirements** — Daily updates sufficient, or need more frequent?
2. **Historical data** — Keep past seasons' data, or only current?
3. **Localization** — Pokémon names in multiple languages?
4. **Rate limits** — Need to test against actual sources

---

## Next Steps

1. ✅ Create repo, add this plan
2. ⬜ Set up project structure (Task 1.1)
3. ⬜ Define Pydantic models (Task 1.2)
4. ⬜ Implement Pikalytics scraper (Tasks 1.3–1.4)
5. ⬜ Test and validate output
6. ⬜ Set up GitHub Actions cron

---

*Last updated: 2026-04-14*
