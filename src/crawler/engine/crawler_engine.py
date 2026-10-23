"""Main crawler engine with async workers."""
import asyncio
from typing import Optional, Callable, Dict, List
from dataclasses import dataclass, field

import httpx
from playwright.async_api import async_playwright

from src.core.models import (
    CrawlJob, CrawlJobConfig, QueueItem, JobStatus, JobStage
)
from src.core.settings import get_settings
from src.crawler.engine.queue_manager import QueueManager
from src.crawler.engine.depth_manager import DepthManager
from src.crawler.engine.url_filter import URLFilter, DomainRateLimiter, RobotsChecker
from src.crawler.downloaders.html_downloader import HTMLDownloader
from src.crawler.downloaders.asset_downloader import AssetDownloader
from src.crawler.extractors.link_extractor import LinkExtractor
from src.crawler.extractors.asset_extractor import AssetExtractor
from src.database.job_repository import JobRepository
from src.database.content_indexer import ContentIndexer
from src.utils.deduplicator import Deduplicator

from src.crawler.engine.seeder import seed_queue
from src.crawler.engine.workers import html_crawl_worker, asset_download_worker, progress_reporter

@dataclass
class CrawlerEngine:
    """High-performance async crawler engine."""
    
    job: CrawlJob
    config: CrawlJobConfig
    queue_manager: QueueManager = field(default_factory=QueueManager)
    depth_manager: DepthManager = field(default_factory=DepthManager)
    url_filter: URLFilter = None
    rate_limiter: DomainRateLimiter = None
    robots_checker: RobotsChecker = field(default_factory=RobotsChecker)
    deduplicator: Deduplicator = field(default_factory=Deduplicator)
    
    # Workers
    html_workers: int = 20
    asset_workers: int = 10
    _worker_tasks: List[asyncio.Task] = field(default_factory=list, repr=False)
    
    # State
    is_running: bool = False
    is_paused: bool = False
    stop_requested: bool = False
    assets_downloaded: int = 0
    
    # Components
    html_downloader: HTMLDownloader = None
    asset_downloader: AssetDownloader = None
    link_extractor: LinkExtractor = None
    asset_extractor: AssetExtractor = None
    job_repo: JobRepository = None
    content_indexer: ContentIndexer = None
    
    # HTTP Client
    http_client: httpx.AsyncClient = None
    playwright = None
    browser = None
    
    # Callbacks
    on_progress: Optional[Callable[[Dict], None]] = None
    on_stage_change: Optional[Callable[[JobStage], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None
    
    def __post_init__(self):
        if self.url_filter is None:
            self.url_filter = URLFilter(
                domain=self.config.domain,
                include_patterns=self.config.include_patterns,
                exclude_patterns=self.config.exclude_patterns,
                follow_external=self.config.follow_external_links,
                allow_subdomains=self.config.allow_subdomains,
                allowed_external_sites=self.config.allowed_external_sites,
                save_options=self.config.save_options
            )
        
        if self.rate_limiter is None:
            self.rate_limiter = DomainRateLimiter(self.config.rate_limit_per_domain)
        
        self.depth_manager.set_max_depth(self.config.max_depth)
        
        settings = get_settings()
        self.html_workers = min(self.config.concurrent_requests, 50)
        self.asset_workers = max(self.html_workers // 2, 10)
    
    async def initialize(self):
        """Initialize crawler components."""
        limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
        timeout = httpx.Timeout(self.config.request_timeout, connect=5.0)
        
        headers = {
            "User-Agent": self.config.user_agent or 
                "Mozilla/5.0 (compatible; CrawlerBot/2.0; +http://localhost/bot)"
        }
        if self.config.headers:
            headers.update(self.config.headers)
        
        self.http_client = httpx.AsyncClient(
            limits=limits, timeout=timeout, headers=headers, follow_redirects=True, http2=True
        )
        
        self.playwright = await async_playwright().start()
        browser_type = getattr(self.playwright, get_settings().playwright_browser)
        self.browser = await browser_type.launch(headless=get_settings().playwright_headless)
        
        self.html_downloader = HTMLDownloader(
            http_client=self.http_client, browser=self.browser, timeout=self.config.timeout_for_htmls / 1000
        )
        self.asset_downloader = AssetDownloader(
            http_client=self.http_client, timeout=self.config.timeout_for_assets / 1000
        )
        self.link_extractor = LinkExtractor(self.config.domain)
        self.asset_extractor = AssetExtractor(
            save_images=self.config.save_images, save_videos=self.config.save_videos, save_pdfs=self.config.save_pdfs,
            save_css=self.config.save_css, save_js=self.config.save_js, save_icons=self.config.save_icons, save_fonts=self.config.save_fonts
        )
        
        self.job_repo = JobRepository()
        self.content_indexer = ContentIndexer()
        
        self.queue_manager.set_callbacks(
            on_url_added=lambda item: self._on_url_discovered(item),
            on_asset_added=lambda url: None
        )
    
    async def crawl(self) -> Dict:
        """Start crawling process."""
        self.is_running = True
        self.stop_requested = False
        
        await self.job_repo.update_job_status(self.job.job_id, JobStatus.RUNNING, JobStage.CRAWLING_MAIN_SITE)
        
        await seed_queue(self)
        
        self._worker_tasks = []
        for i in range(self.html_workers):
            self._worker_tasks.append(asyncio.create_task(html_crawl_worker(self, i)))
        for i in range(self.asset_workers):
            self._worker_tasks.append(asyncio.create_task(asset_download_worker(self, i)))
        self._worker_tasks.append(asyncio.create_task(progress_reporter(self)))
        
        try:
            await asyncio.gather(*self._worker_tasks)
        except asyncio.CancelledError:
            pass
        
        self.is_running = False
        self._worker_tasks = []
        
        return self._get_stats()
    
    def _on_url_discovered(self, item: QueueItem):
        """Handle URL discovered event."""
        pass
    
    def _get_stats(self) -> Dict:
        """Get current crawl statistics."""
        return {
            **self.queue_manager.get_stats(),
            "depth_distribution": self.depth_manager.get_urls_by_depth()
        }
    
    async def pause(self):
        """Pause crawling."""
        self.is_paused = True
        await self.job_repo.update_job_status(self.job.job_id, JobStatus.PAUSED)
    
    async def resume(self):
        """Resume crawling."""
        self.is_paused = False
        await self.job_repo.update_job_status(self.job.job_id, JobStatus.RUNNING)
    
    async def stop(self):
        """Stop crawling."""
        self.stop_requested = True
        self.is_running = False
        
        await self.job_repo.update_job_status(self.job.job_id, JobStatus.STOPPED, JobStage.COMPLETED)
        
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        
        if self._worker_tasks:
            try:
                await asyncio.wait(self._worker_tasks, timeout=2.0)
            except Exception:
                pass
        
        self._worker_tasks = []
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.http_client:
            await self.http_client.aclose()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
