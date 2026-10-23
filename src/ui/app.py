"""UI for V3 Crawler Platform - Web interface for configuring and running crawls."""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from src.database.mongo_client import MongoDB
from src.ui.dependencies import get_crawl_manager, STATIC_DIR
from src.ui.routers import view_routes, job_routes, api_routes
from src.ui.services import asset_server
from src.ui.sync_endpoints import router as sync_router
from src.core.settings import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events."""
    settings = get_settings()
    await MongoDB.connect()
    print("V3 Crawler UI started")
    print(f"API: http://{settings.api_host}:{settings.api_port}")
    yield
    manager = get_crawl_manager()
    await manager.shutdown()
    await MongoDB.disconnect()


app = FastAPI(title="V3 Crawler Platform UI", lifespan=lifespan)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include routers (Note: prefixes are omitted if routes define full paths)
app.include_router(view_routes.router)
app.include_router(job_routes.router)
app.include_router(api_routes.router)
app.include_router(sync_router)
app.include_router(asset_server.router)


if __name__ == "__main__":
    import argparse
    import uvicorn

    settings = get_settings()

    parser = argparse.ArgumentParser(description="V3 Crawler UI")
    parser.add_argument("--host", default=settings.api_host)
    parser.add_argument("--port", type=int, default=settings.api_port)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    uvicorn.run(
        "src.ui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
