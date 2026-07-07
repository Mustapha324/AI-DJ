from fastapi import FastAPI

from app.api.tracks import router as tracks_router
from app.config import ensure_storage_dirs


def create_app() -> FastAPI:
    ensure_storage_dirs()

    app = FastAPI(
        title="AI DJ Track Analyzer",
        description="Foundation backend for analyzing local tracks before future AI DJ features.",
        version="0.1.0",
    )
    app.include_router(tracks_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


app = create_app()
