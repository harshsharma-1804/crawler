"""Main FastAPI application."""
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.settings import get_settings, ensure_directories
from src.database.mongo_client import MongoDB
from src.api.routes_crawl import router as crawl_router, get_crawl_manager
from src.api.routes_reports import router as reports_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    settings = get_settings()
    
    # Ensure directories exist
    ensure_directories()
    
    # Connect to MongoDB
    await MongoDB.connect()
    
    # Try to use uvloop if available and enabled
    if settings.use_uvloop:
        try:
            import uvloop
            uvloop.install()
            print("Using uvloop for improved performance")
        except ImportError:
            pass
    
    print(f"Crawler Platform started")
    print(f"API: http://{settings.api_host}:{settings.api_port}")
    
    yield
    
    # Shutdown
    # Stop all active crawl jobs
    manager = get_crawl_manager()
    await manager.shutdown()
    
    # Disconnect from MongoDB
    await MongoDB.disconnect()
    
    print("Crawler Platform stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="V3 Crawler Platform",
        description="Next-generation website crawler with async architecture",
        version="3.0.0",
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(crawl_router)
    app.include_router(reports_router)
    
    @app.get("/")
    async def root():
        """API root endpoint."""
        return {
            "name": "V3 Crawler Platform",
            "version": "3.0.0",
            "status": "running",
            "endpoints": {
                "crawl": "/crawl/start",
                "jobs": "/crawl/jobs",
                "reports": "/reports/{job_id}/summary"
            }
        }
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        try:
            # Check database connection
            db = MongoDB.get_db()
            await db.command("ping")
            
            return {
                "status": "healthy",
                "database": "connected",
                "timestamp": __import__('datetime').datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": __import__('datetime').datetime.utcnow().isoformat()
            }
    
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    uvicorn.run(
        "src.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=False,
        log_level="info"
    )
