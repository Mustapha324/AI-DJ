from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.jobs import router as jobs_router
from app.api.mixes import router as mixes_router
from app.api.style_profiles import router as style_profiles_router
from app.api.tracks import router as tracks_router
from app.config import ensure_storage_dirs


STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    ensure_storage_dirs()

    app = FastAPI(
        title="AI DJ Studio Mode",
        description="Studio controls for analyzing tracks, planning compatible transitions, and rendering DJ mixes.",
        version="0.2.0",
    )
    app.include_router(tracks_router)
    app.include_router(mixes_router)
    app.include_router(jobs_router)
    app.include_router(style_profiles_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def party_mode() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


app = create_app()
