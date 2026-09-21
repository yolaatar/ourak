# Ourak

Research paper discovery tool for biomedical AI labs. Aggregates papers from multiple sources, scores them by relevance, and delivers a personalized feed.

## Features

- **Multi-source fetching:** arXiv, Semantic Scholar, bioRxiv, Papers With Code
- **Onboarding wizard:** describe your research, get auto-generated topic configurations from curated templates
- **Keyword scoring:** papers scored by include/exclude keyword matching, author/venue boosts, and recency
- **Deduplication:** cross-source fuzzy dedup by title similarity and DOI/arXiv ID matching
- **Digest page:** filter by topic, sort by relevance or date, filter by source
- **Feedback loop:** upvote/flag papers to calibrate future results
- **Automated digest:** GitHub Actions cron job for weekly email/Slack digests

## Stack

- **Backend:** Python, FastAPI, SQLModel (SQLite), OpenRouter LLM
- **Frontend:** React 18, Vite, CSS Modules (dark theme)
- **Sources:** arXiv, Semantic Scholar, bioRxiv, Papers With Code

## Dev Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values below.

| Variable | Required | Where to get it | What happens without it |
|---|---|---|---|
| `JWT_SECRET` | Yes | Any random string (e.g. `openssl rand -hex 32`) | App crashes on startup |
| `APP_PASSWORD` | Yes | Pick any password (used to log in) | App crashes on startup |
| `OPENROUTER_API_KEY` | For onboarding | [openrouter.ai/keys](https://openrouter.ai/keys) | App runs, but the onboarding LLM step fails |
| `S2_API_KEY` | No | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) | App runs on free-tier Semantic Scholar rate limits |
| `DATABASE_URL` | No | SQLAlchemy URL | Defaults to `sqlite:///data/paperwatch.db` |
| `FRONTEND_URL` | No | Your frontend URL | Only needed if frontend runs on a different domain |
| `SLACK_WEBHOOK_URL` | No | Slack app settings | Disables Slack digest notifications |
| `EMAIL_*` | No | Your SMTP credentials | Disables email digest notifications |

The minimum to get the app running locally: set `JWT_SECRET`, `APP_PASSWORD`, and optionally `OPENROUTER_API_KEY` if you want to use the onboarding wizard.

### 2. Backend

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
# API available at http://localhost:8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

Open `http://localhost:5173`, log in with the username of your choice and the `APP_PASSWORD` you set.

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

## Lab Watcher

Tracks new papers written by the lab and new papers citing the lab, using OpenAlex, and posts them to Slack.

1. Edit `config/lab.yaml`. Lab papers are matched by affiliation keyword (e.g. "NeuroPoly") and/or by listed authors (ORCID preferred, or OpenAlex author IDs). To find IDs:
   ```bash
   python -m app.lab_watch --find "Full Name" "Other Name"
   ```
2. Preview without posting or saving anything:
   ```bash
   python -m app.lab_watch --dry-run
   ```
3. Run for real: posts to `SLACK_WEBHOOK_URL` (or prints if unset) and marks papers as seen in the DB, so the next run only reports new ones:
   ```bash
   python -m app.lab_watch
   ```

Papers also get linked to the `lab-papers` and `citing-lab` topics, so they show up in the web feed.

### Weekly run on GitHub Actions

`.github/workflows/lab-watch.yml` runs every Monday. The DB of already-posted papers is kept on the `lab-watch-state` branch (created on first run), so nothing needs to be hosted.

Setup: add a `SLACK_WEBHOOK_URL` repo secret (Slack app with Incoming Webhooks enabled, added to a channel). `OPENALEX_EMAIL` and `OPENALEX_API_KEY` secrets are optional. To test, trigger it manually from the Actions tab with "dry run" checked.

## Running Tests

```bash
python -m pytest tests/ -x -q
```
