# Ourak

Research paper discovery tool for biomedical AI labs. Aggregates papers from multiple sources, scores them by relevance, and delivers a personalized feed.

## Features

- **Multi-source fetching** — arXiv, Semantic Scholar, bioRxiv, Papers With Code
- **Onboarding wizard** — Describe your research, get auto-generated topic configurations from curated templates
- **Keyword scoring** — Papers scored by include/exclude keyword matching, author/venue boosts, and recency
- **Deduplication** — Cross-source fuzzy dedup by title similarity and DOI/arXiv ID matching
- **Digest page** — Filter by topic, sort by relevance or date, filter by source
- **Feedback loop** — Upvote/flag papers to calibrate future results
- **Automated digest** — GitHub Actions cron job for weekly email/Slack digests

## Stack

- **Backend:** Python, FastAPI, SQLModel (SQLite), OpenRouter LLM
- **Frontend:** React 18, Vite, CSS Modules (dark theme)
- **Sources:** arXiv, Semantic Scholar, bioRxiv, Papers With Code

## Setup

```bash
# Backend
cp .env.example .env
# Fill in API keys (OPENROUTER_API_KEY required for onboarding)
pip install -r requirements.txt
uvicorn backend.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | LLM for topic generation during onboarding |
| `S2_API_KEY` | No | Semantic Scholar API (higher rate limits) |
| `APP_SECRET` | No | Auth token signing (defaults to dev key) |

## Project Structure

```
app/                  Core domain logic
  sources/            Paper fetchers (arxiv, biorxiv, s2, pwc)
  db.py               SQLite tables + helpers
  models.py           Pydantic models (Paper, Topic)
  scoring.py          Keyword scoring engine
  dedup.py            Cross-source deduplication
backend/              FastAPI API layer
  api/                Route handlers (onboarding, papers, topics, users)
  main.py             App factory + entrypoint
config/               YAML topic templates and defaults
frontend/             React + Vite
  src/pages/          Login, Onboarding, Digest
  src/components/     PaperCard, Header
tests/                pytest suite
```

## Running Tests

```bash
python -m pytest tests/ -x -q
```
