"""FastAPI application for paper-watch."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse

load_dotenv()  # load .env before anything reads os.getenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app.db import init_db
from backend.auth import require_auth, router as auth_router
from backend.api.onboarding import router as onboarding_router
from backend.api.papers import router as papers_router
from backend.api.topics import router as topics_router
from backend.api.users import router as users_router

# Module-level engine reference for tests
_engine: Engine | None = None

# Path to built frontend assets (populated by Dockerfile)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    global _engine

    app = FastAPI(title="paper-watch", version="0.1.0")

    # CORS
    frontend_url = os.getenv("FRONTEND_URL", "")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:3000",
            *([] if not frontend_url else [frontend_url]),
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

    # Serve frontend static files (production build)
    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve static files or fall back to index.html for SPA routing."""
            file = STATIC_DIR / path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(STATIC_DIR / "index.html")

    return app


# For `uvicorn backend.main:app`
app = create_app()
