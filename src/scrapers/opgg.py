# src/scrapers/opgg.py
"""OP.GG scraper for Pokémon Champions tier lists and win rates."""

import logging
import re
from typing import Optional

from src.scrapers.base import BaseScraper, ParseError
from src.models.schema import (
    PokemonUsage,
    MoveUsage,
    ItemUsage,
    AbilityUsage,
    TeammateUsage,
    TeraTypeUsage,
    TierList,
)

logger = logging.getLogger(__name__)

# Mapping of Pokémon names to National Dex IDs (shared with pikalytics, consider extracting)
POKEMON_DEX_IDS = {
    "bulbasaur": 1, "ivysaur": 2, "venusaur": 3, "charmander": 4, "charmeleon": 5,
    "charizard": 6, "squirtle": 7, "wartortle": 8, "blastoise": 9, "pikachu": 25,
    "raichu": 26, "mewtwo": 150, "mew": 151, "chikorita": 152, "cyndaquil": 155,
    "totodile": 158, "tyranitar": 248, "lugia": 249, "ho-oh": 250,
    "treecko": 252, "torchic": 255, "mudkip": 258, "gardevoir": 282,
    "salamence": 373, "metagross": 376, "latias": 380, "latios": 381,
    "kyogre": 382, "groudon": 383, "rayquaza": 384,
    "turtwig": 387, "chimchar": 390, "piplup": 393, "garchomp": 445,
    "lucario": 448, "abomasnow": 460, "dialga": 483, "palkia": 484, "giratina": 487,
    "snivy": 495, "tepig": 498, "oshawott": 501, "amoonguss": 591,
    "landorus": 645, "kyurem": 646,
    "chespin": 650, "fennekin": 653, "froakie": 656, "greninja": 658,
    "aegislash": 681,
    "rowlet": 722, "litten": 725, "popplio": 728, "mimikyu": 778,
    "grookey": 810, "scorbunny": 813, "sobble": 816, "rillaboom": 812,
    "cinderace": 815, "inteleon": 818, "urshifu": 892, "calyrex": 898,
    "flutter-mane": 987, "iron-hands": 992, "gholdengo": 1000,
    "miraidon": 1008, "koraidon": 1007,
}

# Tier order for parsing
TIER_ORDER = ["S", "A", "B", "C", "D"]


class OPGGScraper(BaseScraper):
    """Scraper for OP.GG Pokémon Champions tier lists and stats."""

    @property
    def name(self) -> str:
        return "OP.GG"

    @property
    def base_url(self) -> str:
        return "https://op.gg/pokemon-champions"

    def _get_dex_id(self, name: str) -> int:
        """Get National Dex ID for a Pokémon name."""
        normalized = self._normalize_pokemon_name(name)
        return POKEMON_DEX_IDS.get(normalized, 0)

    async def scrape_rankings(self, limit: int = 50) -> list[PokemonUsage]:
        """
        Scrape main OP.GG tier list page for rankings and win rates.
        
        OP.GG typically shows tier-based rankings rather than pure usage rankings,
        so we extract tier information alongside win rates.
        """
        url = self.base_url
        logger.info(f"Scraping rankings from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)
            
            rankings = []
            rank = 1

            # OP.GG tier list patterns - try multiple selectors
            # Pattern 1: Tier sections with pokemon lists
            tier_sections = soup.select(
                ".tier-list-section, .tier-section, [data-tier], "
                ".champion-tier, .pokemon-tier-list"
            )

            if tier_sections:
                for section in tier_sections:
                    tier_name = self._extract_tier_name(section)
                    pokemon_entries = section.select(
                        ".champion-item, .pokemon-item, .tier-pokemon, "
                        "[data-pokemon], .champion-card"
                    )
                    
                    for entry in pokemon_entries:
                        pokemon = self._parse_pokemon_entry(entry, rank, tier_name)
                        if pokemon and rank <= limit:
                            rankings.append(pokemon)
                            rank += 1
            else:
                # Pattern 2: Table-based layout
                table_rows = soup.select(
                    "table.tier-table tr, .tier-table-row, "
                    ".ranking-table tr[data-pokemon]"
                )
                
                for row in table_rows[:limit]:
                    pokemon = self._parse_table_row(row, rank)
                    if pokemon:
                        rankings.append(pokemon)
                        rank += 1

            # Pattern 3: Card/grid layout
            if not rankings:
                cards = soup.select(
                    ".pokemon-card, .champion-card, .tier-card, "
                    "[class*='pokemon'][class*='card']"
                )
                
                for card in cards[:limit]:
                    pokemon = self._parse_card(card, rank)
                    if pokemon:
                        rankings.append(pokemon)
                        rank += 1

            # Pattern 4: List with links
            if not rankings:
                links = soup.select("a[href*='/pokemon/'], a[href*='/champion/']")
                seen_names = set()
                
                for link in links:
                    name = self._extract_name_from_link(link)
                    if name and name.lower() not in seen_names:
                        seen_names.add(name.lower())
                        win_rate = self._find_nearby_win_rate(link)
                        
                        rankings.append(PokemonUsage(
                            rank=rank,
                            dex_id=self._get_dex_id(name),
                            name=name.title(),
                            usage_rate=0.0,
                            win_rate=win_rate,
                        ))
                        rank += 1
                        
                        if rank > limit:
                            break

            logger.info(f"Scraped {len(rankings)} Pokémon from OP.GG")
            return rankings

        except Exception as e:
            logger.error(f"Failed to scrape OP.GG rankings: {e}")
            raise ParseError(f"Failed to parse OP.GG rankings: {e}") from e

    async def scrape_pokemon_detail(self, name: str) -> Optional[PokemonUsage]:
        """Scrape detailed stats for a single Pokémon from OP.GG."""
        normalized_name = self._normalize_pokemon_name(name)
        url = f"{self.base_url}/pokemon/{normalized_name}"
        logger.info(f"Scraping OP.GG details for {name} from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)

            moves = []
            items = []
            abilities = []
            win_rate = None

            # Extract win rate
            win_rate_elem = soup.select_one(
                ".win-rate, .winrate, [data-winrate], "
                ".stats-winrate, .champion-winrate"
            )
            if win_rate_elem:
                win_rate = self._parse_percentage(win_rate_elem.get_text())

            # Extract recommended builds - moves
            moves_section = soup.select_one(
                ".recommended-moves, .skill-build, .moves, "
                "[data-section='moves'], #moves"
            )
            if moves_section:
                move_items = moves_section.select(".move, .skill-item, li")
                for item in move_items[:4]:
                    move_name = item.get_text(strip=True)
                    if move_name:
                        moves.append(MoveUsage(name=move_name, usage=0.0))

            # Extract recommended items
            items_section = soup.select_one(
                ".recommended-items, .item-build, .items, "
                "[data-section='items'], #items"
            )
            if items_section:
                item_elems = items_section.select(".item, .build-item, li")
                for elem in item_elems[:4]:
                    item_name = elem.get("data-item") or elem.get_text(strip=True)
                    if item_name:
                        items.append(ItemUsage(name=item_name, usage=0.0))

            # Extract abilities
            abilities_section = soup.select_one(
                ".abilities, .ability-build, [data-section='abilities']"
            )
            if abilities_section:
                ability_elems = abilities_section.select(".ability, li")
                for elem in ability_elems[:2]:
                    ability_name = elem.get_text(strip=True)
                    if ability_name:
                        abilities.append(AbilityUsage(name=ability_name, usage=0.0))

            return PokemonUsage(
                rank=0,
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=0.0,
                win_rate=win_rate,
                top_moves=moves,
                top_items=items,
                top_abilities=abilities,
            )

        except Exception as e:
            logger.warning(f"Failed to scrape OP.GG details for {name}: {e}")
            return None

    async def scrape_tier_list(self) -> TierList:
        """
        Scrape tier list categorization from OP.GG.
        
        Returns a TierList with Pokémon dex IDs organized by tier (S/A/B/C/D).
        """
        url = self.base_url
        logger.info(f"Scraping tier list from {url}")

        try:
            html = await self._fetch(url)
            soup = self._parse_html(html)

            tiers: dict[str, list[int]] = {tier: [] for tier in TIER_ORDER}

            # Look for tier sections
            for tier in TIER_ORDER:
                # Try various selectors for tier sections
                tier_section = soup.select_one(
                    f"[data-tier='{tier}'], [data-tier='{tier.lower()}'], "
                    f".tier-{tier.lower()}, .tier-{tier}, "
                    f"#tier-{tier.lower()}, #tier-{tier}"
                )
                
                if not tier_section:
                    # Try finding by header text
                    headers = soup.find_all(["h2", "h3", "h4", "div"], 
                                           string=re.compile(f"^{tier}\\s*(Tier)?$", re.I))
                    if headers:
                        tier_section = headers[0].find_next_sibling()

                if tier_section:
                    pokemon_elems = tier_section.select(
                        ".pokemon, .champion, [data-pokemon], a[href*='pokemon']"
                    )
                    for elem in pokemon_elems:
                        name = elem.get("data-pokemon") or elem.get_text(strip=True)
                        dex_id = self._get_dex_id(name)
                        if dex_id > 0:
                            tiers[tier].append(dex_id)

            return TierList(
                S=tiers["S"],
                A=tiers["A"],
                B=tiers["B"],
                C=tiers["C"],
                D=tiers["D"],
            )

        except Exception as e:
            logger.error(f"Failed to scrape tier list: {e}")
            return TierList()

    def _extract_tier_name(self, section) -> Optional[str]:
        """Extract tier name (S/A/B/C/D) from a section element."""
        # Check data attributes
        tier = section.get("data-tier")
        if tier and tier.upper() in TIER_ORDER:
            return tier.upper()
        
        # Check class names
        for cls in section.get("class", []):
            for tier in TIER_ORDER:
                if f"tier-{tier.lower()}" in cls.lower() or f"tier{tier.lower()}" in cls.lower():
                    return tier
        
        # Check header text
        header = section.select_one("h2, h3, h4, .tier-header, .tier-name")
        if header:
            text = header.get_text(strip=True).upper()
            for tier in TIER_ORDER:
                if text.startswith(tier):
                    return tier
        
        return None

    def _parse_pokemon_entry(self, entry, rank: int, tier: Optional[str] = None) -> Optional[PokemonUsage]:
        """Parse a Pokémon entry from a tier section."""
        try:
            # Extract name
            name_elem = entry.select_one(
                ".pokemon-name, .champion-name, .name, "
                "[data-name], img[alt]"
            )
            if name_elem:
                name = name_elem.get("data-name") or name_elem.get("alt") or name_elem.get_text(strip=True)
            else:
                name = entry.get("data-pokemon") or entry.get_text(strip=True).split()[0]
            
            if not name:
                return None

            # Extract win rate
            win_rate_elem = entry.select_one(".win-rate, .winrate, [data-winrate]")
            win_rate = self._parse_percentage(win_rate_elem.get_text()) if win_rate_elem else None

            # Extract usage rate (OP.GG might call it pick rate)
            usage_elem = entry.select_one(".pick-rate, .usage, .pickrate, [data-pickrate]")
            usage_rate = self._parse_percentage(usage_elem.get_text()) if usage_elem else 0.0

            return PokemonUsage(
                rank=rank,
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=usage_rate,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.warning(f"Failed to parse pokemon entry: {e}")
            return None

    def _parse_table_row(self, row, rank: int) -> Optional[PokemonUsage]:
        """Parse a table row for Pokémon data."""
        try:
            cells = row.select("td")
            if len(cells) < 2:
                return None

            # First cell usually has name/image
            name_cell = cells[0]
            name = (name_cell.select_one("img[alt]") or {}).get("alt") or name_cell.get_text(strip=True)
            
            if not name:
                return None

            # Look for win rate and usage in other cells
            win_rate = None
            usage_rate = 0.0
            
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if "%" in text:
                    value = self._parse_percentage(text)
                    # Assume win rate is ~50%, usage is usually lower
                    if 0.4 <= value <= 0.7:
                        win_rate = value
                    else:
                        usage_rate = value

            return PokemonUsage(
                rank=rank,
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=usage_rate,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.warning(f"Failed to parse table row: {e}")
            return None

    def _parse_card(self, card, rank: int) -> Optional[PokemonUsage]:
        """Parse a card-style Pokémon entry."""
        try:
            # Try image alt, data attribute, or text
            img = card.select_one("img")
            name = (
                card.get("data-pokemon") or
                card.get("data-name") or
                (img.get("alt") if img else None) or
                card.select_one(".name, .pokemon-name", "").get_text(strip=True) or
                card.get_text(strip=True).split()[0]
            )
            
            if not name:
                return None

            win_rate_elem = card.select_one(".win-rate, .winrate")
            win_rate = self._parse_percentage(win_rate_elem.get_text()) if win_rate_elem else None

            return PokemonUsage(
                rank=rank,
                dex_id=self._get_dex_id(name),
                name=name.title(),
                usage_rate=0.0,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.warning(f"Failed to parse card: {e}")
            return None

    def _extract_name_from_link(self, link) -> Optional[str]:
        """Extract Pokémon name from a link element."""
        href = link.get("href", "")
        match = re.search(r"/(?:pokemon|champion)/([^/]+)", href)
        if match:
            return match.group(1).replace("-", " ").replace("_", " ").title()
        
        # Try text content
        text = link.get_text(strip=True)
        if text and len(text) < 30:  # Reasonable name length
            return text
        
        return None

    def _find_nearby_win_rate(self, element) -> Optional[float]:
        """Find win rate near an element (sibling or parent's child)."""
        # Check siblings
        for sibling in element.find_next_siblings()[:3]:
            text = sibling.get_text(strip=True)
            if "%" in text:
                rate = self._parse_percentage(text)
                if 0.3 <= rate <= 0.8:  # Reasonable win rate range
                    return rate
        
        # Check parent's children
        parent = element.find_parent()
        if parent:
            for child in parent.children:
                if hasattr(child, "get_text"):
                    text = child.get_text(strip=True)
                    if "%" in text and child != element:
                        rate = self._parse_percentage(text)
                        if 0.3 <= rate <= 0.8:
                            return rate
        
        return None
