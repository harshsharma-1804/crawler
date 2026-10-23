"""Crawl manager for orchestrating crawl jobs."""
import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

from src.core.models import (
    CrawlJob, CrawlJobConfig, JobStatus, JobStage,
    CrawlProgress, Checkpoint
)
from src.database.job_repository import JobRepository
from src.database.content_indexer import ContentIndexer
from src.crawler.engine.crawler_engine import CrawlerEngine
from src.security.domain_verifier import DomainVerifier
from src.crawler.processors.server_builder import ServerBuilder
from src.reporting.report_builder import ReportBuilder


@dataclass
class CrawlManager:
    """Manages crawl job lifecycle."""
    
    active_jobs: Dict[str, CrawlerEngine] = field(default_factory=dict)
    job_repo: JobRepository = field(default_factory=JobRepository)
    domain_verifier: DomainVerifier = field(default_factory=DomainVerifier)
    
    def __post_init__(self):
        self._lock = asyncio.Lock()
    
    async def create_job(self, config: CrawlJobConfig) -> CrawlJob:
        """Create new crawl job."""
        job_id = str(uuid.uuid4())[:8]
        
        job = CrawlJob(
            job_id=job_id,
            domain=config.domain,
            config=config,
            status=JobStatus.PENDING,
            stage=JobStage.INITIALIZING
        )
        
        # Save to database
        await self.job_repo.create_job(job)
        
        return job
    
    async def start_job(self, job_id: str) -> bool:
        """Start crawl job."""
        async with self._lock:
            job = await self.job_repo.get_job(job_id)
            if not job:
                return False
            
            if job_id in self.active_jobs:
                return False  # Already running
            
            # Verify domain if required
            if job.config.verify_domain:
                verification = await self.domain_verifier.verify(
                    domain=job.config.domain,
                    email=job.config.verification_email,
                    token=job.config.verification_token
                )
                
                if not verification["verified"]:
                    await self.job_repo.update_job(job_id, {
                        "status": JobStatus.FAILED.value,
                        "error_message": f"Domain verification failed: {verification['message']}"
                    })
                    return False
            
            # Initialize engine
            engine = CrawlerEngine(
                job=job,
                config=job.config
            )
            
            await engine.initialize()
            
            # Set callbacks
            engine.on_progress = lambda stats: self._on_progress(job_id, stats)
            engine.on_stage_change = lambda stage: self._on_stage_change(job_id, stage)
            engine.on_error = lambda url, error: self._on_error(job_id, url, error)
            
            self.active_jobs[job_id] = engine
            
            # Update job status
            await self.job_repo.update_job(job_id, {
                "status": JobStatus.RUNNING.value,
                "stage": JobStage.CRAWLING_MAIN_SITE.value,
                "started_at": datetime.utcnow()
            })
            
            # Start crawling in background
            asyncio.create_task(self._run_job(job_id, engine))
            
            return True
    
    async def _run_job(self, job_id: str, engine: CrawlerEngine):
        """Run crawl job and handle completion."""
        job = None
        try:
            # Run crawling
            stats = await engine.crawl()
            
            # Build server mirror if full mirror mode
            job = await self.job_repo.get_job(job_id)
            if job and job.config.save_options == "full_mirror":
                await self._build_server_mirror(job_id, job.config.domain)
            
            # Generate reports
            await self._generate_reports(job_id)
            
            # Update job status
            await self.job_repo.update_job(job_id, {
                "status": JobStatus.COMPLETED.value,
                "stage": JobStage.COMPLETED.value,
                "completed_at": datetime.utcnow()
            })
            
        except Exception as e:
            error_count = 1
            if job is not None:
                error_count = job.error_count + 1
            await self.job_repo.update_job(job_id, {
                "status": JobStatus.FAILED.value,
                "stage": JobStage.COMPLETED.value,
                "error_message": str(e),
                "error_count": error_count
            })
        finally:
            # Cleanup
            await engine.cleanup()
            async with self._lock:
                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]
    
    async def pause_job(self, job_id: str) -> bool:
        """Pause running job."""
        if job_id not in self.active_jobs:
            return False
        
        engine = self.active_jobs[job_id]
        await engine.pause()
        return True
    
    async def resume_job(self, job_id: str) -> bool:
        """Resume paused job."""
        if job_id not in self.active_jobs:
            return False
        
        engine = self.active_jobs[job_id]
        await engine.resume()
        return True
    
    async def stop_job(self, job_id: str) -> bool:
        """Stop running job."""
        if job_id not in self.active_jobs:
            return False
        
        engine = self.active_jobs[job_id]
        await engine.stop()
        return True
    
    async def get_job_progress(self, job_id: str) -> Optional[CrawlProgress]:
        """Get job progress."""
        # First check database
        progress = await self.job_repo.get_progress(job_id)
        
        # If job is active, get live stats
        if job_id in self.active_jobs:
            engine = self.active_jobs[job_id]
            live_stats = engine._get_stats()
            
            if progress:
                progress.queue_remaining = live_stats.get("crawl_queue_remaining", 0)
        
        return progress
    
    async def list_jobs(
        self,
        status: JobStatus = None,
        limit: int = 100,
        skip: int = 0,
        domain: str = None,
        month: str = None
    ) -> List[CrawlJob]:
        """List crawl jobs with pagination, domain search, and month filtering."""
        return await self.job_repo.list_jobs(
            status=status,
            limit=limit,
            skip=skip,
            domain=domain,
            month=month
        )

    async def count_jobs(
        self,
        status: JobStatus = None,
        domain: str = None,
        month: str = None
    ) -> int:
        """Count total jobs matching filters."""
        return await self.job_repo.count_jobs(
            status=status,
            domain=domain,
            month=month
        )
    
    async def get_job(self, job_id: str) -> Optional[CrawlJob]:
        """Get job by ID."""
        return await self.job_repo.get_job(job_id)
    
    async def delete_job(self, job_id: str) -> bool:
        """Delete job and associated data."""
        # Stop if running
        if job_id in self.active_jobs:
            await self.stop_job(job_id)
        
        # Delete from database
        await self.job_repo.delete_job(job_id)
        
        # Delete indexed content
        indexer = ContentIndexer()
        await indexer.delete_job_content(job_id)
        
        return True
    
    async def _build_server_mirror(self, job_id: str, domain: str):
        """Build offline server mirror."""
        try:
            await self.job_repo.update_job(job_id, {
                "stage": JobStage.BUILDING_SERVER_STRUCTURE.value
            })
            
            builder = ServerBuilder()
            await builder.build_server_mirror(domain, job_id)
        except Exception as e:
            print(f"Error building server mirror: {e}")
    
    async def _generate_reports(self, job_id: str):
        """Generate crawl reports."""
        try:
            await self.job_repo.update_job(job_id, {
                "stage": JobStage.GENERATING_REPORTS.value
            })
            
            report_builder = ReportBuilder()
            await report_builder.generate_csv_reports(job_id)
        except Exception as e:
            print(f"Error generating reports: {e}")
    
    def _on_progress(self, job_id: str, stats: Dict):
        """Handle progress update."""
        pass  # Progress is tracked via get_progress
    
    def _on_stage_change(self, job_id: str, stage: JobStage):
        """Handle stage change."""
        asyncio.create_task(self.job_repo.update_job(job_id, {
            "stage": stage.value
        }))
    
    def _on_error(self, job_id: str, url: str, error: Exception):
        """Handle crawl error."""
        print(f"Error crawling {url}: {error}")
    
    async def shutdown(self):
        """Shutdown all active jobs."""
        for job_id in list(self.active_jobs.keys()):
            await self.stop_job(job_id)
        
        await self.domain_verifier.close()
