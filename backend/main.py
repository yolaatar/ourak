"""FastAPI application for paper-watch."""

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI

load_dotenv()  # load .env before anything reads os.getenv
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from app.db import init_db
from backend.auth import require_auth, router as auth_router
from backend.api.onboarding import router as onboarding_router
from backend.api.papers import router as papers_router
from backend.api.topics import router as topics_router
from backend.api.users import router as users_router

# Module-level engine reference for tests
_engine: Engine | None = None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    global _engine

    app = FastAPI(title="paper-watch", version="0.1.0")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:3000",
            os.getenv("FRONTEND_URL", ""),
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Init DB
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/paperwatch.db")
    _engine = init_db(db_url)

    # Public routes
    app.include_router(auth_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # Protected routes — require auth
    app.include_router(onboarding_router, dependencies=[Depends(require_auth)])
    app.include_router(papers_router, dependencies=[Depends(require_auth)])
    app.include_router(topics_router, dependencies=[Depends(require_auth)])
    app.include_router(users_router, dependencies=[Depends(require_auth)])

    return app


# For `uvicorn backend.main:app`
app = create_app()
