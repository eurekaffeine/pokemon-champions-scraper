# src/models/schema.py
"""Pydantic models for competitive battle metadata."""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


class MoveUsage(BaseModel):
    """Usage statistics for a move."""
    name: str
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class ItemUsage(BaseModel):
    """Usage statistics for an item."""
    name: str
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class AbilityUsage(BaseModel):
    """Usage statistics for an ability."""
    name: str
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class TeammateUsage(BaseModel):
    """Usage statistics for a teammate Pokémon."""
    dex_id: int = Field(0, ge=0, description="National Pokédex ID (0 if unknown)")
    name: str
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class TeraTypeUsage(BaseModel):
    """Usage statistics for a Tera type."""
    type: str
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class EVSpread(BaseModel):
    """EV spread and nature usage."""
    nature: str
    evs: str = Field(..., description="EV spread string, e.g., '252 Atk / 4 Def / 252 Spe'")
    usage: float = Field(..., ge=0, le=1, description="Usage rate (0-1)")


class PokemonUsage(BaseModel):
    """Usage statistics for a single Pokémon in competitive play."""
    rank: int = Field(..., ge=1, description="Usage rank")
    dex_id: int = Field(..., ge=1, description="National Pokédex ID")
    name: str
    form: Optional[str] = Field(None, description="Form variant, e.g., 'Mega', 'Alola'")
    usage_rate: float = Field(..., ge=0, le=1, description="Overall usage rate")
    win_rate: Optional[float] = Field(None, ge=0, le=1, description="Win rate")
    top_moves: list[MoveUsage] = Field(default_factory=list)
    top_items: list[ItemUsage] = Field(default_factory=list)
    top_abilities: list[AbilityUsage] = Field(default_factory=list)
    top_teammates: list[TeammateUsage] = Field(default_factory=list)
    top_tera_types: list[TeraTypeUsage] = Field(default_factory=list)
    top_spreads: list[EVSpread] = Field(default_factory=list)


class Season(BaseModel):
    """Information about the competitive season."""
    id: str
    name: str
    start_date: date
    end_date: Optional[date] = None


class SourceInfo(BaseModel):
    """Information about a data source."""
    name: str
    url: str
    scraped_at: datetime


class TierList(BaseModel):
    """Tier list categorization of Pokémon by Dex IDs."""
    S: list[int] = Field(default_factory=list)
    A: list[int] = Field(default_factory=list)
    B: list[int] = Field(default_factory=list)
    C: list[int] = Field(default_factory=list)
    D: list[int] = Field(default_factory=list)


class RankDistribution(BaseModel):
    """Distribution of players across competitive ranks."""
    master_ball: float = Field(0.0, ge=0, le=1)
    ultra_ball: float = Field(0.0, ge=0, le=1)
    great_ball: float = Field(0.0, ge=0, le=1)
    poke_ball: float = Field(0.0, ge=0, le=1)
    beginner: float = Field(0.0, ge=0, le=1)


class BattleMeta(BaseModel):
    """Root model for competitive battle metadata."""
    schema_version: str = "1.0.0"
    updated_at: datetime
    season: Optional[Season] = None
    pokemon_usage: list[PokemonUsage] = Field(default_factory=list)
    tier_list: Optional[TierList] = None
    rank_distribution: Optional[RankDistribution] = None
    sources: list[SourceInfo] = Field(default_factory=list)


class PokemonCompetitive(BaseModel):
    """Competitive stats for a single Pokémon (per-Pokémon file)."""
    usage_rank: int
    usage_rate: float
    win_rate: Optional[float] = None
    moves: list[MoveUsage] = Field(default_factory=list)
    items: list[ItemUsage] = Field(default_factory=list)
    abilities: list[AbilityUsage] = Field(default_factory=list)
    teammates: list[TeammateUsage] = Field(default_factory=list)
    tera_types: list[TeraTypeUsage] = Field(default_factory=list)
    spreads: list[EVSpread] = Field(default_factory=list)


class PokemonDetail(BaseModel):
    """Per-Pokémon detail file structure."""
    dex_id: int
    name: str
    form: Optional[str] = None
    competitive: PokemonCompetitive
