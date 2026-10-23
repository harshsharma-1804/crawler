"""Sync Crawl Manager — orchestrates the two-phase sync crawl pipeline.

Architecture:
  - Wraps SyncHTMLDownloader and SyncServerBuilder (both purely synchronous).
  - Runs them in a thread via asyncio.loop.run_in_executor so the FastAPI event
    loop stays unblocked during the crawl.
  - Uses threading.Event for cooperative stop signalling to the running thread.
  - Persists job state to MongoDB via v3's existing JobRepository.
"""

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Optional

from src.core.models import (
    CrawlJob,
    CrawlJobConfig,
    JobStatus,
    JobStage,
    Checkpoint,
    QueueItem,
    DiscoveryType,
)
from src.core.settings import get_settings
from src.database.job_repository import JobRepository
from src.crawler.downloaders.sync_html_downloader import SyncHTMLDownloader
from src.crawler.processors.sync_server_builder import SyncServerBuilder
from src.crawler.processors.sync_analysis_generator import SyncAnalysisGenerator


class SyncCrawlManager:
    """Manages sync crawl job lifecycle with async-compatible interface."""

    def __init__(self):
        self.settings = get_settings()
        self.job_repo = JobRepository()
        # Map job_id -> threading.Event (set to signal stop)
        self._stop_events: Dict[str, threading.Event] = {}
        # Map job_id -> threading.Event (set to signal pause; cleared to resume)
        self._pause_events: Dict[str, threading.Event] = {}
        # Map job_id -> live CrawlStats reference (set once the crawl thread starts)
        self._active_stats: Dict[str, object] = {}
        # Parallel job tracking: job_id -> domain
        self._running_jobs: Dict[str, str] = {}
        # Async lock to protect _running_jobs from race conditions
        self._lock = asyncio.Lock()
        # Dedicated thread pool sized to the parallel job limit
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.max_parallel_jobs,
            thread_name_prefix="crawl-worker",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_and_start_job(self, config: CrawlJobConfig) -> CrawlJob:
        """Create a crawl job in MongoDB and launch it as a background task.

        Raises RuntimeError if the parallel job limit is reached or if a crawl
        for the same domain is already running.
        """
        async with self._lock:
            max_jobs = self.settings.max_parallel_jobs

            if len(self._running_jobs) >= max_jobs:
                running_domains = list(self._running_jobs.values())
                raise RuntimeError(
                    f"All {max_jobs} crawl slots are in use. "
                    f"Currently crawling: {', '.join(running_domains)}. "
                    f"Wait for a job to finish or stop one first."
                )

            if config.domain in self._running_jobs.values():
                raise RuntimeError(
                    f"A crawl for domain '{config.domain}' is already running. "
                    f"Stop the existing job first or wait for it to finish."
                )

            job_id = str(uuid.uuid4())[:8]

            job = CrawlJob(
                job_id=job_id,
                domain=config.domain,
                config=config,
                status=JobStatus.PENDING,
                stage=JobStage.INITIALIZING,
            )

            await self.job_repo.create_job(job)

            # Register the job as running BEFORE launching the task
            self._running_jobs[job_id] = config.domain

            # Kick off the background coroutine (non-blocking)
            asyncio.create_task(self._run_job(job_id, config))

            return job

    async def stop_job(self, job_id: str) -> bool:
        """Signal the crawl thread to stop gracefully."""
        event = self._stop_events.get(job_id)
        if event is None:
            return False
        event.set()
        # Note: _running_jobs cleanup happens in _run_job's finally block
        # when the thread actually finishes, not here.
        return True

    async def get_job(self, job_id: str) -> Optional[CrawlJob]:
        return await self.job_repo.get_job(job_id)

    async def list_jobs(self, *args, **kwargs) -> list[CrawlJob]:
        return await self.job_repo.list_jobs(*args, **kwargs)

    async def count_jobs(self, *args, **kwargs) -> int:
        return await self.job_repo.count_jobs(*args, **kwargs)

    async def get_job_progress(self, job_id: str):
        return await self.job_repo.get_progress(job_id)

    async def delete_job(self, job_id: str) -> bool:
        await self.stop_job(job_id)
        return await self.job_repo.delete_job(job_id)

    async def pause_job(self, job_id: str) -> bool:
        """Pause a running crawl job.

        Sets the pause_event so the BFS loop suspends after the current page.
        Waits up to 3 s for the crawler thread to acknowledge the pause and
        write its queue snapshot, then persists a Checkpoint to MongoDB.
        """
        pause_event = self._pause_events.get(job_id)
        if pause_event is None:
            return False  # job not running

        # Signal the crawl thread to suspend
        pause_event.set()

        # Update DB status immediately so the UI reflects PAUSED
        await self._update_job(job_id, {
            "status": JobStatus.PAUSED.value,
            "stage": JobStage.CRAWLING_MAIN_SITE.value,
            "last_updated": datetime.utcnow(),
        })

        # Wait for the crawl thread to write the queue snapshot into stats
        # (it does so before entering its sleep loop — typically < 1 page time)
        stats = self._active_stats.get(job_id)
        if stats is not None:
            import time as _time
            deadline = _time.monotonic() + 10  # wait at most 10 s
            while _time.monotonic() < deadline:
                if stats.paused_queue or stats.paused_visited:
                    break
                await asyncio.sleep(0.2)

            # Persist checkpoint so resume can restore state
            await self._save_checkpoint(job_id, stats)

        print(f"[SyncCrawlManager] Job {job_id} paused.")
        return True

    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused crawl job from its saved checkpoint.

        Clears the pause_event so the suspended BFS loop wakes and continues.
        If the job is no longer in memory (e.g. server restarted), restores
        queue state from the MongoDB checkpoint and relaunches the crawl.
        """
        pause_event = self._pause_events.get(job_id)

        if pause_event is not None:
            # Job thread is still alive — just wake it up
            pause_event.clear()
            await self._update_job(job_id, {
                "status": JobStatus.RUNNING.value,
                "last_updated": datetime.utcnow(),
            })
            print(f"[SyncCrawlManager] Job {job_id} resumed (in-memory).")
            return True

        # Thread is gone (server restart / crash) — reload from checkpoint
        job = await self.job_repo.get_job(job_id)
        if not job or job.status != JobStatus.PAUSED:
            return False

        checkpoint = await self.job_repo.get_latest_checkpoint(job_id)
        if not checkpoint:
            return False

        print(f"[SyncCrawlManager] Resuming job {job_id} from checkpoint "
              f"({len(checkpoint.crawl_queue)} queued URLs, "
              f"{len(checkpoint.visited_urls)} visited).")

        async with self._lock:
            if len(self._running_jobs) >= self.settings.max_parallel_jobs:
                raise RuntimeError("All crawl slots are in use. Cannot resume right now.")
            self._running_jobs[job_id] = job.domain

        asyncio.create_task(self._run_job_from_checkpoint(job_id, job.config, checkpoint))
        return True

    async def _save_checkpoint(self, job_id: str, stats) -> None:
        """Serialise the current BFS queue and visited set to MongoDB."""
        try:
            queue_items = [
                QueueItem(
                    url=url,
                    depth=depth,
                    discovery_type=DiscoveryType.HTML_LINK,
                )
                for url, depth in stats.paused_queue
            ]
            checkpoint = Checkpoint(
                job_id=job_id,
                stage=JobStage.CRAWLING_MAIN_SITE,
                crawl_queue=queue_items,
                visited_urls=stats.paused_visited,
                pages_crawled=stats.pages_crawled,
                assets_downloaded=stats.assets_downloaded,
            )
            await self.job_repo.save_checkpoint(checkpoint)
            print(
                f"[SyncCrawlManager] Checkpoint saved for job {job_id}: "
                f"{len(queue_items)} URLs queued, "
                f"{len(stats.paused_visited)} visited."
            )
        except Exception as e:
            print(f"[SyncCrawlManager] Failed to save checkpoint for {job_id}: {e}")

    def get_capacity(self) -> dict:
        """Return current parallel job capacity info (sync, no await needed)."""
        return {
            "running": len(self._running_jobs),
            "max": self.settings.max_parallel_jobs,
            "available": self.settings.max_parallel_jobs - len(self._running_jobs),
            "running_domains": list(self._running_jobs.values()),
            "running_job_ids": list(self._running_jobs.keys()),
        }

    def is_domain_running(self, domain: str) -> bool:
        """Check if a crawl for the given domain is currently active."""
        return domain in self._running_jobs.values()

    async def shutdown(self):
        """Shutdown all active threads/jobs."""
        for event in self._stop_events.values():
            event.set()
        self._running_jobs.clear()
        self._pause_events.clear()
        self._active_stats.clear()
        self._executor.shutdown(wait=False)

    async def get_server_info(self, job_id: str) -> dict:
        """Return server directory path and file count for a completed job."""
        job = await self.job_repo.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        # Use project-specific directory (flat structure)
        project_name = job.config.project_name or job.domain
        project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
        server_dir = self.settings.server_dir / project_safe_name

        if not server_dir.exists():
            return {
                "job_id": job_id,
                "domain": job.domain,
                "server_dir": str(server_dir),
                "exists": False,
                "file_count": 0,
            }

        file_count = sum(1 for _ in server_dir.rglob("*") if _.is_file())
        return {
            "job_id": job_id,
            "domain": job.domain,
            "server_dir": str(server_dir),
            "exists": True,
            "file_count": file_count,
        }

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    async def _run_job(self, job_id: str, config: CrawlJobConfig) -> None:
        """Background coroutine that drives the two-phase pipeline."""
        stop_event  = threading.Event()
        pause_event = threading.Event()
        self._stop_events[job_id]  = stop_event
        self._pause_events[job_id] = pause_event

        loop = asyncio.get_running_loop()

        try:
            # ── Phase 1: HTML crawl ──────────────────────────────────
            await self._update_job(job_id, {
                "status": JobStatus.RUNNING.value,
                "stage": JobStage.CRAWLING_MAIN_SITE.value,
                "started_at": datetime.utcnow(),
            })

            downloader = SyncHTMLDownloader()

            def on_progress(pages_crawled: int, current_url: str, queue_size: int = 0, assets_downloaded: int = 0):
                """Called from the crawl thread after each saved page."""
                # Schedule a MongoDB update on the event loop (thread-safe)
                asyncio.run_coroutine_threadsafe(
                    self._update_job(job_id, {
                        "pages_crawled": pages_crawled,
                        "assets_downloaded": assets_downloaded,
                        "queue_remaining": queue_size,
                        "last_updated": datetime.utcnow(),
                    }),
                    loop,
                )

            # Determine project-specific folder name (flat structure)
            project_name = config.project_name or config.domain
            project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")

            # stats_ref is a one-element list used as a mutable cell so the
            # executor thread can expose the live CrawlStats to the event-loop
            # thread (for checkpoint snapshotting on pause) without any extra
            # synchronisation primitives.
            stats_ref: list = [None]

            def _on_stats_created(s):
                """Called by the crawl thread as soon as CrawlStats is ready."""
                stats_ref[0] = s
                self._active_stats[job_id] = s

            stats = await loop.run_in_executor(
                self._executor,
                lambda: downloader.crawl(
                    config=config,
                    html_root=self.settings.html_dir,
                    assets_root=self.settings.assets_dir,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    on_progress=on_progress,
                    folder_name=project_safe_name,
                    on_stats_created=_on_stats_created,
                ),
            )

            if stop_event.is_set():
                # Don't overwrite PAUSED — a paused job looks like a stop from
                # the executor's perspective (BFS loop exited) but the job is
                # still resumable.  The PAUSED status was already written by
                # pause_job() before the thread exited its sleep loop.
                job_now = await self.job_repo.get_job(job_id)
                if job_now and job_now.status == JobStatus.PAUSED:
                    return  # leave status as PAUSED
                await self._update_job(job_id, {
                    "status": JobStatus.STOPPED.value,
                    "stage": JobStage.COMPLETED.value,
                    "pages_crawled": stats.pages_crawled,
                    "assets_downloaded": stats.assets_downloaded,
                    "failed_urls": stats.pages_failed,
                    "completed_at": datetime.utcnow(),
                })
                return

            # ── Phase 1.5: Generate Analysis CSVs ────────────────────
            await self._update_job(job_id, {
                "stage": JobStage.GENERATING_REPORTS.value,
            })
            
            analysis_gen = SyncAnalysisGenerator()
            # Use project-specific paths for analysis (flat structure)
            await loop.run_in_executor(
                self._executor,
                lambda: analysis_gen.generate(
                    domain=project_safe_name,  # Use project name as domain folder
                    html_root=self.settings.html_dir,
                    analyses_root=self.settings.analyses_dir,
                    allowed_external_sites=config.allowed_external_sites,
                    failed_urls=stats.failed_urls,
                    url_log=stats.url_log,
                    asset_log=stats.asset_log,
                )
            )

            # Record completed time for crawler + analysis ONLY
            completion_time = datetime.utcnow()

            # ── Phase 2: Build server mirror ─────────────────────────
            if config.save_options in ("full_mirror", "pattern_crawl"):
                await self._update_job(job_id, {
                    "stage": JobStage.BUILDING_SERVER_STRUCTURE.value,
                    "pages_crawled": stats.pages_crawled,
                    "assets_downloaded": stats.assets_downloaded,
                    "failed_urls": stats.pages_failed,
                })

                builder = SyncServerBuilder()

                await loop.run_in_executor(
                    self._executor,
                    lambda: builder.build(
                        domain=project_safe_name,  # Use project name as domain folder
                        html_root=self.settings.html_dir,
                        assets_root=self.settings.assets_dir,
                        server_root=self.settings.server_dir,
                    ),
                )

            # ── Completion ───────────────────────────────────────────
            await self._update_job(job_id, {
                "status": JobStatus.COMPLETED.value,
                "stage": JobStage.COMPLETED.value,
                "pages_crawled": stats.pages_crawled,
                "assets_downloaded": stats.assets_downloaded,
                "failed_urls": stats.pages_failed,
                "completed_at": completion_time,  # Measured just before server builder
            })

        except Exception as exc:
            print(f"[SyncCrawlManager] Job {job_id} failed: {exc}")
            await self._update_job(job_id, {
                "status": JobStatus.FAILED.value,
                "stage": JobStage.COMPLETED.value,
                "error_message": str(exc),
                "completed_at": datetime.utcnow(),
            })

        finally:
            self._stop_events.pop(job_id, None)
            self._pause_events.pop(job_id, None)
            self._active_stats.pop(job_id, None)
            self._running_jobs.pop(job_id, None)

    async def _run_job_from_checkpoint(
        self, job_id: str, config: CrawlJobConfig, checkpoint: Checkpoint
    ) -> None:
        """Re-launch a paused job from a persisted Checkpoint.

        Rebuilds the BFS queue and visited set from the checkpoint, then
        delegates to _run_job which handles the full pipeline.
        The SyncHTMLDownloader accepts an optional `resume_queue` and
        `resume_visited` parameter to seed itself from saved state.
        """
        stop_event  = threading.Event()
        pause_event = threading.Event()
        self._stop_events[job_id]  = stop_event
        self._pause_events[job_id] = pause_event

        loop = asyncio.get_running_loop()

        try:
            await self._update_job(job_id, {
                "status": JobStatus.RUNNING.value,
                "stage": JobStage.CRAWLING_MAIN_SITE.value,
                "last_updated": datetime.utcnow(),
            })

            downloader = SyncHTMLDownloader()

            def on_progress(pages_crawled: int, current_url: str, queue_size: int = 0, assets_downloaded: int = 0):
                asyncio.run_coroutine_threadsafe(
                    self._update_job(job_id, {
                        "pages_crawled": pages_crawled,
                        "assets_downloaded": assets_downloaded,
                        "queue_remaining": queue_size,
                        "last_updated": datetime.utcnow(),
                    }),
                    loop,
                )

            project_name = config.project_name or config.domain
            project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")

            # Reconstruct queue and visited from checkpoint
            resume_queue   = [(item.url, item.depth) for item in checkpoint.crawl_queue]
            resume_visited = set(checkpoint.visited_urls)

            def _on_stats_created(s):
                self._active_stats[job_id] = s

            stats = await loop.run_in_executor(
                self._executor,
                lambda: downloader.crawl(
                    config=config,
                    html_root=self.settings.html_dir,
                    assets_root=self.settings.assets_dir,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    on_progress=on_progress,
                    folder_name=project_safe_name,
                    on_stats_created=_on_stats_created,
                    resume_queue=resume_queue,
                    resume_visited=resume_visited,
                ),
            )

            if stop_event.is_set():
                job_now = await self.job_repo.get_job(job_id)
                if job_now and job_now.status == JobStatus.PAUSED:
                    return
                await self._update_job(job_id, {
                    "status": JobStatus.STOPPED.value,
                    "stage": JobStage.COMPLETED.value,
                    "pages_crawled": stats.pages_crawled,
                    "assets_downloaded": stats.assets_downloaded,
                    "failed_urls": stats.pages_failed,
                    "completed_at": datetime.utcnow(),
                })
                return

            # Analysis + server build (same as _run_job)
            await self._update_job(job_id, {"stage": JobStage.GENERATING_REPORTS.value})
            analysis_gen = SyncAnalysisGenerator()
            await loop.run_in_executor(
                self._executor,
                lambda: analysis_gen.generate(
                    domain=project_safe_name,
                    html_root=self.settings.html_dir,
                    analyses_root=self.settings.analyses_dir,
                    allowed_external_sites=config.allowed_external_sites,
                    failed_urls=stats.failed_urls,
                    url_log=stats.url_log,
                    asset_log=stats.asset_log,
                ),
            )

            completion_time = datetime.utcnow()

            if config.save_options in ("full_mirror", "pattern_crawl"):
                await self._update_job(job_id, {
                    "stage": JobStage.BUILDING_SERVER_STRUCTURE.value,
                    "pages_crawled": stats.pages_crawled,
                    "assets_downloaded": stats.assets_downloaded,
                })
                builder = SyncServerBuilder()
                await loop.run_in_executor(
                    self._executor,
                    lambda: builder.build(
                        domain=project_safe_name,
                        html_root=self.settings.html_dir,
                        assets_root=self.settings.assets_dir,
                        server_root=self.settings.server_dir,
                    ),
                )

            await self._update_job(job_id, {
                "status": JobStatus.COMPLETED.value,
                "stage": JobStage.COMPLETED.value,
                "pages_crawled": stats.pages_crawled,
                "assets_downloaded": stats.assets_downloaded,
                "failed_urls": stats.pages_failed,
                "completed_at": completion_time,
            })

        except Exception as exc:
            print(f"[SyncCrawlManager] Job {job_id} (resumed) failed: {exc}")
            await self._update_job(job_id, {
                "status": JobStatus.FAILED.value,
                "stage": JobStage.COMPLETED.value,
                "error_message": str(exc),
                "completed_at": datetime.utcnow(),
            })

        finally:
            self._stop_events.pop(job_id, None)
            self._pause_events.pop(job_id, None)
            self._active_stats.pop(job_id, None)
            self._running_jobs.pop(job_id, None)

    async def _update_job(self, job_id: str, updates: dict) -> None:
        """Update job fields in MongoDB (fire-and-forget style; errors are logged)."""
        try:
            await self.job_repo.update_job(job_id, updates)
        except Exception as e:
            print(f"[SyncCrawlManager] DB update error for job {job_id}: {e}")

    async def rebuild_server(self, job_id: str, force: bool = False) -> dict:
        """Rebuild server folder from existing HTML and assets for a completed job.

        Args:
            job_id: The job ID to rebuild server for
            force: If True, rebuild even for html_content_only jobs (for explicit user requests)
        """
        job = await self.job_repo.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        # Use project_name if set, otherwise fall back to domain
        project_name = job.config.project_name or job.config.domain
        project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")

        # Check if HTML folder exists (flat structure)
        html_root = self.settings.html_dir / project_safe_name
        if not html_root.exists():
            return {"success": False, "error": "No HTML files found for this domain"}

        # Check if job used html_content_only mode - only block if not forced (auto-build)
        if job.config.save_options == "html_content_only" and not force:
            return {"success": False, "error": "Cannot build server for html_content_only jobs. No assets were saved."}

        # Build server
        builder = SyncServerBuilder()
        loop = asyncio.get_running_loop()

        try:
            server_path = await loop.run_in_executor(
                self._executor,
                lambda: builder.build(
                    domain=project_safe_name,  # Use project name as domain folder
                    html_root=self.settings.html_dir,
                    assets_root=self.settings.assets_dir,
                    server_root=self.settings.server_dir,
                ),
            )

            # Different message for html_content_only jobs
            if job.config.save_options == "html_content_only":
                message = f"Server rebuilt successfully (HTML only, no assets). Path: {server_path}"
            else:
                message = f"Server rebuilt successfully at {server_path}"

            return {
                "success": True,
                "server_path": str(server_path),
                "message": message,
            }
        except Exception as e:
            return {"success": False, "error": f"Server build failed: {str(e)}"}
