"""Application settings and configuration."""
import sys
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings

# Default data directory — resolves to <project_root>/data on all platforms
_DEFAULT_DATA_DIR = str(Path(__file__).parent.parent.parent / "data")

# Load .env file before Settings class is defined
# Try multiple locations for the .env file
_env_loaded = False
_env_paths = [
    Path(__file__).parent.parent.parent / ".env",      # Project root
    Path(__file__).parent.parent.parent / "config" / ".env",  # config/.env
    Path.cwd() / ".env",                                 # Current directory
    Path.cwd() / "config" / ".env",                      # Current/config/
]

for _env_path in _env_paths:
    if _env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=True)
        _env_loaded = True
        break


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "crawler_platform"
    max_concurrent_requests: int = 50
    max_depth: int = 5
    request_timeout: int = 30
    retry_attempts: int = 3
    rate_limit_per_domain: int = 10
    data_dir: str = _DEFAULT_DATA_DIR
    max_file_size_mb: int = 100
    verification_token_secret: str = "change-me-in-production"
    admin_email_domain: str = "localhost"
    api_host: str = "0.0.0.0"
    api_port: int = 9000
    api_workers: int = 1
    playwright_headless: bool = True
    playwright_browser: str = "chromium"
    use_uvloop: bool = sys.platform != "win32"
    enable_caching: bool = True
    cache_ttl_seconds: int = 3600
    max_parallel_jobs: int = 3

    @property
    def project_dir(self) -> Path:
        return Path(self.data_dir) / "project"

    @property
    def html_dir(self) -> Path:
        return self.project_dir / "htmls"

    @property
    def assets_dir(self) -> Path:
        return self.project_dir / "assets"

    @property
    def analyses_dir(self) -> Path:
        return Path(self.data_dir) / "analyses"

    @property
    def server_dir(self) -> Path:
        return Path(self.data_dir) / "server"

    @property
    def uploads_dir(self) -> Path:
        return Path(self.data_dir) / "uploads"

    class Config:
        # Environment variables are loaded via python-dotenv at module level
        # Environment variables take precedence over default values
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def ensure_directories():
    settings = get_settings()
    dirs = [
        settings.html_dir,
        settings.assets_dir / "css",
        settings.assets_dir / "js",
        settings.assets_dir / "images",
        settings.assets_dir / "pdfs",
        settings.assets_dir / "fonts",
        settings.assets_dir / "icons",
        settings.assets_dir / "videos",
        settings.analyses_dir,
        settings.server_dir,
        settings.uploads_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
