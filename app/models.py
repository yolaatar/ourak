"""Pydantic models for paper-watch."""

from typing import Literal, Optional
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


class LabPaper(Paper):
    """A paper found by the lab watcher: written by the lab, or citing its work."""

    kind: Literal["authored", "citing"]
    lab_authors: list[str] = Field(default_factory=list)  # lab members on the paper
    cited_lab_titles: list[str] = Field(default_factory=list)  # lab papers it cites


class LabAuthor(BaseModel):
    """A lab member, identified by ORCID and/or OpenAlex author IDs."""

    name: str
    orcid: Optional[str] = None
    openalex_ids: list[str] = Field(default_factory=list)


class LabConfig(BaseModel):
    """Settings for the lab watcher (config/lab.yaml)."""

    lab_name: str
    lookback_days: int = 30
    authors: list[LabAuthor] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)  # matched in raw affiliation strings


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
