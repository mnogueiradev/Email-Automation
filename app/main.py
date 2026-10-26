"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import get_settings
from app.infrastructure.database.session import dispose_database_engine
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release a lazily created database pool during application shutdown."""

    yield
    dispose_database_engine()


app = FastAPI(
    title="Email-Automation API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

_frontend_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the local operations dashboard."""

    return FileResponse(_frontend_dir / "index.html")


app.include_router(api_router)
