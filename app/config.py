"""Configuration loading for paper-watch."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from app.models import Config, Topic


def load_config(config_dir: str = "config") -> Config:
    """Load and merge defaults.yaml + topics.yaml into a validated Config."""
    base = Path(config_dir)

    with open(base / "defaults.yaml") as f:
        defaults = yaml.safe_load(f)

    with open(base / "topics.yaml") as f:
        topics_data = yaml.safe_load(f)

    topics = [Topic(**t) for t in topics_data.get("topics", [])]
    return Config(defaults=defaults, topics=topics)


def load_env(env_path: str = ".env") -> None:
    """Load environment variables from a .env file if it exists."""
    load_dotenv(dotenv_path=env_path, override=False)


def get_ncbi_api_key() -> str | None:
    """Return the NCBI API key from the environment, if set."""
    return os.getenv("NCBI_API_KEY") or None
