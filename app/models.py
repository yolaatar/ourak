"""Pydantic models for paper-watch."""

from typing import Optional
from pydantic import BaseModel, Field


class Paper(BaseModel):
    """Represents a single research paper from any source."""

    source: str
    source_id: str
    title: str
    abstract: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    published_date: Optional[str] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    topics_matched: list[str] = Field(default_factory=list)
    score: float = 0.0
    alt_ids: list[str] = Field(default_factory=list)  # source_ids of merged duplicates


class Topic(BaseModel):
    """A research topic with keyword filters and scoring hints."""

    name: str
    include_any: list[str] = Field(default_factory=list)
    include_all: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    boost_authors: list[str] = Field(default_factory=list)
    boost_venues: list[str] = Field(default_factory=list)


class Config(BaseModel):
    """Top-level configuration merging defaults and topics."""

    defaults: dict
    topics: list[Topic]
