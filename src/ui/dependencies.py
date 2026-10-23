import sys
from pathlib import Path
from typing import Optional

from starlette.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
import json

from src.core.models import CrawlJobConfig
from src.core.sync_crawl_manager import SyncCrawlManager

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Global crawl manager
_crawl_manager: Optional[SyncCrawlManager] = None

def get_crawl_manager() -> SyncCrawlManager:
    """Get or create crawl manager instance."""
    global _crawl_manager
    if _crawl_manager is None:
        _crawl_manager = SyncCrawlManager()
    return _crawl_manager


class UISettings(BaseModel):
    """Settings model for the UI form."""
    domain: str
    project_name: Optional[str] = None  # Project folder name (optional, defaults to domain)
    entry_url: Optional[str] = None
    max_depth: int = 3
    max_pages: Optional[int] = None
    concurrent_requests: int = 20
    rate_limit_per_domain: int = 10
    
    # Domain settings
    allow_subdomains: bool = True
    allowed_external_sites: str = ""  # Comma-separated
    
    # Pattern exclusions
    exclude_patterns: str = ""  # Comma-separated
    include_patterns: str = ""  # Comma-separated
    
    # Save options
    save_options: str = "full_mirror"  # full_mirror or html_content_only
    crawl_mode: str = "queue_and_sitemap"  # queue_based, sitemap_only, queue_and_sitemap
    
    # Individual asset save options
    save_images: bool = True
    save_videos: bool = True
    save_pdfs: bool = True
    save_css: bool = True
    save_js: bool = True
    save_icons: bool = True
    save_fonts: bool = True
    
    # Timeouts (in milliseconds)
    timeout_for_htmls: int = 30000
    timeout_for_assets: int = 60000

    # Fast Mode
    fast_mode: bool = False
    
    # Verification
    verify_domain: bool = False
    verification_email: Optional[str] = None
    verification_token: Optional[str] = None
    
    # Sitemap and orphan URLs
    sitemap_urls: str = ""  # Comma-separated
    orphan_urls: str = ""  # Comma-separated
    
    # Uploaded URL list (JSON-encoded list from the upload step)
    upload_urls: str = ""  # JSON string e.g. '["https://...", ...]'
    
    # Uploaded orphan URL list (JSON-encoded list from the upload step)
    upload_orphan_urls: str = ""  # JSON string e.g. '["https://...", ...]'
    
    # Form Authentication
    auth_login_url: Optional[str] = None
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    
    # Interactive auth (MFA / 2FA / CAPTCHA)
    auth_interactive: bool = False
    auth_wait_seconds: int = 120  # Max seconds to wait for manual auth
    auth_post_login_url: Optional[str] = None  # Override crawl start after auth
    
    # Modal trigger + custom CSS selectors (advanced override)
    auth_trigger_selector: Optional[str] = None
    auth_username_selector: Optional[str] = None
    auth_password_selector: Optional[str] = None
    auth_submit_selector: Optional[str] = None
    
    @field_validator("max_depth")
    @classmethod
    def validate_depth(cls, v: int) -> int:
        if v < 0 or v > 10:
            raise ValueError("MAX_DEPTH must be between 0 and 10")
        return v
    
    @field_validator("max_pages")
    @classmethod
    def validate_max_pages(cls, v):
        if v is not None and v < 1:
            raise ValueError("MAX_PAGES must be at least 1")
        return v
    
    def to_crawl_config(self) -> CrawlJobConfig:
        """Convert UI settings to CrawlJobConfig."""
        return CrawlJobConfig(
            domain=self.domain,
            project_name=self.project_name or None,
            entry_url=self.entry_url or None,
            max_depth=self.max_depth,
            max_pages=self.max_pages,
            concurrent_requests=self.concurrent_requests,
            rate_limit_per_domain=self.rate_limit_per_domain,
            
            allow_subdomains=self.allow_subdomains,
            allowed_external_sites=[s.strip() for s in self.allowed_external_sites.split(",") if s.strip()],
            
            exclude_patterns=[p.strip() for p in self.exclude_patterns.split(",") if p.strip()],
            include_patterns=[p.strip() for p in self.include_patterns.split(",") if p.strip()],
            
            save_options=self.save_options,
            crawl_mode=self.crawl_mode,
            
            save_images=self.save_images,
            save_videos=self.save_videos,
            save_pdfs=self.save_pdfs,
            save_css=self.save_css,
            save_js=self.save_js,
            save_icons=self.save_icons,
            save_fonts=self.save_fonts,
            
            timeout_for_htmls=self.timeout_for_htmls,
            timeout_for_assets=self.timeout_for_assets,
            fast_mode=self.fast_mode,
            
            verify_domain=self.verify_domain,
            verification_email=self.verification_email or None,
            verification_token=self.verification_token or None,
            
            sitemap_urls=[s.strip() for s in self.sitemap_urls.split(",") if s.strip()],
            orphan_urls=[s.strip() for s in self.orphan_urls.split(",") if s.strip()] + 
                        (json.loads(self.upload_orphan_urls) if self.upload_orphan_urls.strip() else []),
            
            upload_urls=json.loads(self.upload_urls) if self.upload_urls.strip() else [],
            
            auth_login_url=self.auth_login_url or None,
            auth_username=self.auth_username or None,
            auth_password=self.auth_password or None,
            auth_interactive=self.auth_interactive,
            auth_wait_seconds=self.auth_wait_seconds,
            auth_post_login_url=self.auth_post_login_url or None,
            auth_trigger_selector=self.auth_trigger_selector or None,
            auth_username_selector=self.auth_username_selector or None,
            auth_password_selector=self.auth_password_selector or None,
            auth_submit_selector=self.auth_submit_selector or None,
        )
