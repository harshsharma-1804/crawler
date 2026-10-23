"""Core Pydantic models for the crawler platform."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(str, Enum):
    INITIALIZING = "initializing"
    VERIFYING_SITE = "verifying_site"
    CRAWLING_MAIN_SITE = "crawling_main_site"
    CRAWLING_ORPHAN_PAGES = "crawling_orphan_pages"
    EXTRACTING_ASSETS = "extracting_assets"
    DOWNLOADING_ASSETS = "downloading_assets"
    EXTRACTING_CSS_ASSETS = "extracting_css_assets"
    DOWNLOADING_CSS_ASSETS = "downloading_css_assets"
    BUILDING_SERVER_STRUCTURE = "building_server_structure"
    GENERATING_REPORTS = "generating_reports"
    COMPLETED = "completed"


class DiscoveryType(str, Enum):
    ENTRY_POINT = "entry_point"
    HTML_LINK = "html_link"
    SITEMAP = "sitemap"
    ORPHAN = "orphan"
    CANONICAL = "canonical"
    REDIRECT = "redirect"
    JS_NAVIGATION = "js_navigation"


class CrawlMode(str, Enum):
    """Crawl mode enumeration."""
    QUEUE_BASED = "queue_based"  # Make queue from links on each page
    SITEMAP_ONLY = "sitemap_only"  # Use sitemap only
    QUEUE_AND_SITEMAP = "queue_and_sitemap"  # Both
    URL_LIST = "url_list"  # Crawl only URLs from an uploaded CSV/Excel file


class SaveOptions(str, Enum):
    """Save options enumeration."""
    FULL_MIRROR = "full_mirror"  # Create local copy of site
    HTML_CONTENT_ONLY = "html_content_only"  # Save content only for AI parsing
    PATTERN_CRAWL = "pattern_crawl"  # Crawl only URLs matching include_patterns paths


class AssetType(str, Enum):
    CSS = "css"
    JS = "js"
    IMAGE = "image"
    PDF = "pdf"
    FONT = "font"
    ICON = "icon"
    VIDEO = "video"
    OTHER = "other"


class QueueItem(BaseModel):
    url: str
    depth: int = Field(ge=0)
    source_url: Optional[str] = None
    discovery_type: DiscoveryType = DiscoveryType.HTML_LINK
    priority: int = Field(default=5, ge=1, le=10)
    retry_count: int = Field(default=0, ge=0)
    added_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


class CrawlJobConfig(BaseModel):
    domain: str
    project_name: Optional[str] = None  # Project folder name (defaults to domain if not set)
    entry_url: Optional[str] = None  # Entry point URL
    max_depth: int = Field(default=3, ge=0, le=10)
    max_pages: Optional[int] = Field(default=None, ge=1)
    concurrent_requests: int = Field(default=20, ge=1, le=100)
    rate_limit_per_domain: int = Field(default=10, ge=1)
    request_timeout: int = Field(default=30, ge=5)  # in seconds
    retry_attempts: int = Field(default=3, ge=0)
    
    # Subdomain and external site settings
    allow_subdomains: bool = True  # Allow crawling subdomains
    allowed_external_sites: List[str] = Field(default_factory=list)  # ["abc.com", "xyz.to"]
    
    # Pattern exclusions
    exclude_patterns: List[str] = Field(default_factory=list)  # [".pdf", ".zip"]
    include_patterns: List[str] = Field(default_factory=list)
    
    # Save options: "full_mirror" or "html_content_only"
    save_options: str = "full_mirror"
    
    # Crawl mode: "queue_based", "sitemap_only", "queue_and_sitemap"
    crawl_mode: str = "queue_and_sitemap"
    
    # Individual asset save options (checkbox style)
    save_images: bool = True
    save_videos: bool = True
    save_pdfs: bool = True
    save_css: bool = True
    save_js: bool = True
    save_icons: bool = True
    save_fonts: bool = True
    
    # Timeout settings in milliseconds
    timeout_for_htmls: int = Field(default=30000, ge=1000)  # 30 seconds
    timeout_for_assets: int = Field(default=60000, ge=1000)  # 60 seconds

    # Fast Mode — aggressive speed optimizations.
    # Targets ~100-300ms/page in HTML-only mode and ~1-3s/page in full-mirror mode.
    # When True, the SyncHTMLDownloader:
    #   * Skips the long networkidle wait (and the 2 s fallback hard-wait)
    #   * Caps the HTML navigation timeout (5 s HTML-only, 10 s full mirror)
    #   * Blocks heavy resources (images / fonts / media / stylesheets) when
    #     save_options == "html_content_only" so the browser only fetches HTML
    fast_mode: bool = False
    
    # Legacy options (keep for compatibility)
    follow_external_links: bool = False
    extract_assets: bool = True
    download_assets: bool = True
    
    # Verification and auth
    verify_domain: bool = True
    verification_email: Optional[str] = None
    verification_token: Optional[str] = None
    user_agent: Optional[str] = None
    respect_robots_txt: bool = True
    
    # Sitemap and orphan URLs
    sitemap_urls: List[str] = Field(default_factory=list)
    orphan_urls: List[str] = Field(default_factory=list)
    
    # Uploaded URL list (for url_list_crawl mode)
    upload_urls: List[str] = Field(default_factory=list)
    
    # Cookies and headers
    cookie_string: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    
    # Form Authentication
    auth_login_url: Optional[str] = None
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    
    # Interactive authentication (MFA / 2FA / CAPTCHA)
    # NOTE: The browser automatically launches in headed (visible) mode
    # whenever auth fields are set.  MFA is auto-detected after credentials
    # submit.  This flag is kept for backward compatibility but is no longer
    # required — the crawler always opens a visible browser for auth.
    auth_interactive: bool = False
    auth_wait_seconds: int = Field(default=120, ge=10, le=600)  # Max wait for manual MFA
    
    # Post-login entry URL override.  After auth completes the crawler uses
    # this URL (instead of entry_url / auth_login_url) as the BFS start.
    # If empty, the crawler auto-detects the post-login landing page.
    auth_post_login_url: Optional[str] = None
    
    # CSS selector for a button/link that opens a login modal.  When set,
    # the crawler clicks this element before looking for login form inputs.
    # Leave empty if the login form is on a dedicated page (not a modal).
    auth_trigger_selector: Optional[str] = None
    
    # Custom CSS selectors for non-standard login forms.  When set, these
    # are tried FIRST (before the built-in heuristic selectors).  Use
    # browser DevTools to find the right selector for the site.
    auth_username_selector: Optional[str] = None
    auth_password_selector: Optional[str] = None
    auth_submit_selector: Optional[str] = None

    @field_validator("domain")
    @classmethod
    def clean_domain(cls, v: str) -> str:
        v = v.lower().strip()
        v = v.replace("https://", "").replace("http://", "")
        v = v.split("/")[0]
        return v


class CrawlJob(BaseModel):
    job_id: str
    domain: str
    status: JobStatus = JobStatus.PENDING
    stage: JobStage = JobStage.INITIALIZING
    config: CrawlJobConfig
    pages_crawled: int = 0
    assets_discovered: int = 0
    assets_downloaded: int = 0
    queue_remaining: int = 0
    failed_urls: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    entry_point: Optional[str] = None
    sitemap_found: bool = False
    total_urls_discovered: int = 0
    error_message: Optional[str] = None
    error_count: int = 0


class CrawlProgress(BaseModel):
    job_id: str
    status: JobStatus
    stage: JobStage
    progress_percent: float = Field(ge=0.0, le=100.0)
    pages_crawled: int
    assets_downloaded: int
    queue_remaining: int
    failed_urls: int
    elapsed_seconds: Optional[int] = None
    estimated_remaining_seconds: Optional[int] = None
    current_url: Optional[str] = None
    message: Optional[str] = None


class URLRecord(BaseModel):
    url: str
    domain: str
    job_id: str
    link_type: str = "page"
    source_url: Optional[str] = None
    discovery_type: DiscoveryType = DiscoveryType.HTML_LINK
    depth: int = 0
    http_status: Optional[int] = None
    redirect_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    title: Optional[str] = None
    crawl_success: bool = False
    error_message: Optional[str] = None
    crawl_time_ms: Optional[int] = None
    cached: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    local_path: Optional[str] = None


class AssetRecord(URLRecord):
    asset_type: AssetType = AssetType.OTHER
    parent_urls: List[str] = Field(default_factory=list)
    download_success: bool = False


class HTMLContent(BaseModel):
    url: str
    domain: str
    job_id: str
    title: Optional[str] = None
    meta_description: Optional[str] = None
    headings: Dict[str, List[str]] = Field(default_factory=dict)
    content: str = ""
    links: List[Dict[str, Any]] = Field(default_factory=list)
    images: List[Dict[str, str]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CrawlReport(BaseModel):
    job_id: str
    domain: str
    status: JobStatus
    stage: JobStage
    created_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    total_urls: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    external_urls: int = 0
    assets_by_type: Dict[str, int] = Field(default_factory=dict)
    assets_downloaded: int = 0
    assets_failed: int = 0
    html_files_count: int = 0
    total_storage_mb: float = 0.0
    reports_available: List[str] = Field(default_factory=list)


class DomainVerification(BaseModel):
    domain: str
    verified: bool = False
    method: Optional[str] = None
    message: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Checkpoint(BaseModel):
    job_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    stage: JobStage
    crawl_queue: List[QueueItem] = Field(default_factory=list)
    visited_urls: Set[str] = Field(default_factory=set)
    failed_urls: Set[str] = Field(default_factory=set)
    discovered_urls: Set[str] = Field(default_factory=set)
    pages_crawled: int = 0
    assets_downloaded: int = 0
