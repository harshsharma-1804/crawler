"""FastAPI routes for crawl operations."""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

from src.core.models import CrawlJob, CrawlJobConfig, CrawlProgress, JobStatus
from src.core.crawl_manager import CrawlManager


router = APIRouter(prefix="/crawl", tags=["crawl"])

# Global crawl manager instance
_crawl_manager: Optional[CrawlManager] = None


def get_crawl_manager() -> CrawlManager:
    """Get or create crawl manager instance."""
    global _crawl_manager
    if _crawl_manager is None:
        _crawl_manager = CrawlManager()
    return _crawl_manager


class StartCrawlRequest(BaseModel):
    """Request to start a crawl job."""
    domain: str = Field(..., description="Domain to crawl")
    entry_url: Optional[str] = Field(None, description="Entry point URL")
    max_depth: int = Field(default=3, ge=0, le=10, description="Maximum crawl depth")
    max_pages: Optional[int] = Field(None, ge=1, description="Maximum pages to crawl")
    concurrent_requests: int = Field(default=20, ge=1, le=100)
    rate_limit_per_domain: int = Field(default=10, ge=1)
    request_timeout: int = Field(default=30, ge=5)
    retry_attempts: int = Field(default=3, ge=0)
    
    # Domain and external site settings
    allow_subdomains: bool = Field(default=True, description="Allow crawling subdomains")
    allowed_external_sites: List[str] = Field(default_factory=list, description="List of allowed external domains")
    
    # Pattern exclusions
    exclude_patterns: List[str] = Field(default_factory=list, description="URL patterns to exclude")
    include_patterns: List[str] = Field(default_factory=list, description="URL patterns to include")
    
    # Save options
    save_options: str = Field(default="full_mirror", pattern="^(full_mirror|html_content_only)$")
    crawl_mode: str = Field(default="queue_and_sitemap", pattern="^(queue_based|sitemap_only|queue_and_sitemap)$")
    
    # Individual asset save options (checkbox style)
    save_images: bool = Field(default=True)
    save_videos: bool = Field(default=True)
    save_pdfs: bool = Field(default=True)
    save_css: bool = Field(default=True)
    save_js: bool = Field(default=True)
    save_icons: bool = Field(default=True)
    save_fonts: bool = Field(default=True)
    
    # Timeout settings (in milliseconds)
    timeout_for_htmls: int = Field(default=30000, ge=1000, description="Timeout for HTML pages in ms")
    timeout_for_assets: int = Field(default=60000, ge=1000, description="Timeout for assets in ms")

    # Fast Mode — aggressive optimizations (~100-300 ms/page HTML-only, ~1-3 s/page full mirror)
    fast_mode: bool = Field(default=False, description="Enable Fast Mode optimizations")
    
    # Legacy options
    follow_external_links: bool = Field(default=False)
    extract_assets: bool = Field(default=True)
    download_assets: bool = Field(default=True)
    
    # Verification and auth
    verify_domain: bool = Field(default=True)
    verification_email: Optional[str] = None
    verification_token: Optional[str] = None
    user_agent: Optional[str] = None
    respect_robots_txt: bool = Field(default=True)
    
    # Sitemap and orphan URLs
    sitemap_urls: List[str] = Field(default_factory=list)
    orphan_urls: List[str] = Field(default_factory=list)


class StartCrawlResponse(BaseModel):
    """Response from starting a crawl."""
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    stage: str
    progress_percent: float
    pages_crawled: int
    assets_downloaded: int
    queue_remaining: int
    failed_urls: int
    elapsed_seconds: Optional[int]
    message: Optional[str]


class JobListResponse(BaseModel):
    """Job list item."""
    job_id: str
    domain: str
    status: str
    stage: str
    pages_crawled: int
    created_at: str


@router.post("/start", response_model=StartCrawlResponse)
async def start_crawl(request: StartCrawlRequest):
    """Start a new crawl job."""
    manager = get_crawl_manager()
    
    # Create job config
    config = CrawlJobConfig(
        domain=request.domain,
        entry_url=request.entry_url,
        max_depth=request.max_depth,
        max_pages=request.max_pages,
        concurrent_requests=request.concurrent_requests,
        rate_limit_per_domain=request.rate_limit_per_domain,
        request_timeout=request.request_timeout,
        retry_attempts=request.retry_attempts,
        
        # Domain settings
        allow_subdomains=request.allow_subdomains,
        allowed_external_sites=request.allowed_external_sites,
        
        # Patterns
        exclude_patterns=request.exclude_patterns,
        include_patterns=request.include_patterns,
        
        # Save options
        save_options=request.save_options,
        crawl_mode=request.crawl_mode,
        
        # Asset save options
        save_images=request.save_images,
        save_videos=request.save_videos,
        save_pdfs=request.save_pdfs,
        save_css=request.save_css,
        save_js=request.save_js,
        save_icons=request.save_icons,
        save_fonts=request.save_fonts,
        
        # Timeouts
        timeout_for_htmls=request.timeout_for_htmls,
        timeout_for_assets=request.timeout_for_assets,

        # Fast Mode
        fast_mode=request.fast_mode,

        # Legacy options
        follow_external_links=request.follow_external_links,
        extract_assets=request.extract_assets,
        download_assets=request.download_assets,
        
        # Verification
        verify_domain=request.verify_domain,
        verification_email=request.verification_email,
        verification_token=request.verification_token,
        user_agent=request.user_agent,
        respect_robots_txt=request.respect_robots_txt,
        
        # URLs
        sitemap_urls=request.sitemap_urls,
        orphan_urls=request.orphan_urls
    )
    
    # Create job
    job = await manager.create_job(config)
    
    # Start job
    success = await manager.start_job(job.job_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start crawl job")
    
    return StartCrawlResponse(
        job_id=job.job_id,
        status=job.status.value,
        message="Crawl job started successfully"
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_crawl_status(job_id: str):
    """Get crawl job status."""
    manager = get_crawl_manager()
    
    progress = await manager.get_job_progress(job_id)
    
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(
        job_id=progress.job_id,
        status=progress.status.value,
        stage=progress.stage.value,
        progress_percent=progress.progress_percent,
        pages_crawled=progress.pages_crawled,
        assets_downloaded=progress.assets_downloaded,
        queue_remaining=progress.queue_remaining,
        failed_urls=progress.failed_urls,
        elapsed_seconds=progress.elapsed_seconds,
        message=progress.message
    )


@router.post("/stop/{job_id}")
async def stop_crawl(job_id: str):
    """Stop a running crawl job."""
    manager = get_crawl_manager()
    
    success = await manager.stop_job(job_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Job not found or not running")
    
    return {"message": "Crawl job stopped", "job_id": job_id}


@router.post("/pause/{job_id}")
async def pause_crawl(job_id: str):
    """Pause a running crawl job."""
    manager = get_crawl_manager()
    
    success = await manager.pause_job(job_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Job not found or not running")
    
    return {"message": "Crawl job paused", "job_id": job_id}


@router.post("/resume/{job_id}")
async def resume_crawl(job_id: str):
    """Resume a paused crawl job."""
    manager = get_crawl_manager()
    
    success = await manager.resume_job(job_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Job not found or not paused")
    
    return {"message": "Crawl job resumed", "job_id": job_id}


@router.get("/jobs", response_model=List[JobListResponse])
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000)
):
    """List crawl jobs."""
    manager = get_crawl_manager()
    
    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    jobs = await manager.list_jobs(job_status, limit)
    
    return [
        JobListResponse(
            job_id=job.job_id,
            domain=job.domain,
            status=job.status.value,
            stage=job.stage.value,
            pages_crawled=job.pages_crawled,
            created_at=job.created_at.isoformat()
        )
        for job in jobs
    ]


@router.get("/job/{job_id}")
async def get_job(job_id: str):
    """Get job details."""
    manager = get_crawl_manager()
    
    job = await manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job.job_id,
        "domain": job.domain,
        "status": job.status.value,
        "stage": job.stage.value,
        "config": job.config.model_dump(),
        "pages_crawled": job.pages_crawled,
        "assets_downloaded": job.assets_downloaded,
        "queue_remaining": job.queue_remaining,
        "failed_urls": job.failed_urls,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message
    }


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a crawl job and associated data."""
    manager = get_crawl_manager()
    
    success = await manager.delete_job(job_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete job")
    
    return {"message": "Job deleted", "job_id": job_id}
