"""Job repository for MongoDB operations."""
from datetime import datetime
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from src.core.models import CrawlJob, CrawlProgress, JobStatus, JobStage, Checkpoint
from src.database.mongo_client import MongoDB


class JobRepository:
    """Repository for crawl job persistence."""

    def __init__(self, db: AsyncIOMotorDatabase = None):
        self.db = db or MongoDB.get_db()
        self.jobs_collection = self.db.jobs
        self.checkpoints_collection = self.db.checkpoints

    async def create_job(self, job: CrawlJob) -> str:
        await self.jobs_collection.insert_one(job.model_dump())
        return job.job_id

    async def get_job(self, job_id: str) -> Optional[CrawlJob]:
        data = await self.jobs_collection.find_one({"job_id": job_id})
        return CrawlJob(**data) if data else None

    async def update_job(self, job_id: str, updates: dict) -> bool:
        result = await self.jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def update_job_status(self, job_id: str, status: JobStatus, stage: JobStage = None) -> bool:
        updates = {"status": status.value, "last_updated": __import__('datetime').datetime.utcnow()}
        if stage:
            updates["stage"] = stage.value
        return await self.update_job(job_id, updates)

    async def update_job_progress(self, job_id: str, pages_crawled: int = None, 
                                   assets_downloaded: int = None, queue_remaining: int = None,
                                   failed_urls: int = None) -> bool:
        updates = {"last_updated": __import__('datetime').datetime.utcnow()}
        if pages_crawled is not None:
            updates["pages_crawled"] = pages_crawled
        if assets_downloaded is not None:
            updates["assets_downloaded"] = assets_downloaded
        if queue_remaining is not None:
            updates["queue_remaining"] = queue_remaining
        if failed_urls is not None:
            updates["failed_urls"] = failed_urls
        return await self.update_job(job_id, updates)

    async def list_jobs(
        self,
        status: JobStatus = None,
        limit: int = 100,
        skip: int = 0,
        domain: str = None,
        month: str = None,  # Format: YYYY-MM
    ) -> List[CrawlJob]:
        """List crawl jobs with pagination, domain search, and month filtering."""
        query = {}

        # Status filter
        if status:
            query["status"] = status.value

        # Domain search (case-insensitive regex match)
        if domain:
            query["domain"] = {"$regex": domain, "$options": "i"}

        # Month filtering
        if month:
            # Parse month string (YYYY-MM)
            try:
                year, mon = month.split("-")
                year = int(year)
                mon = int(mon)
                start_date = datetime(year, mon, 1, 0, 0, 0)
                if mon == 12:
                    end_date = datetime(year + 1, 1, 1, 0, 0, 0)
                else:
                    end_date = datetime(year, mon + 1, 1, 0, 0, 0)

                query["created_at"] = {
                    "$gte": start_date,
                    "$lt": end_date
                }
            except (ValueError, IndexError):
                pass  # Invalid month format, ignore filter

        cursor = self.jobs_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return [CrawlJob(**doc) async for doc in cursor]

    async def count_jobs(
        self,
        status: JobStatus = None,
        domain: str = None,
        month: str = None
    ) -> int:
        """Count total jobs matching filters."""
        query = {}

        if status:
            query["status"] = status.value

        if domain:
            query["domain"] = {"$regex": domain, "$options": "i"}

        if month:
            try:
                year, mon = month.split("-")
                year = int(year)
                mon = int(mon)
                start_date = datetime(year, mon, 1, 0, 0, 0)
                if mon == 12:
                    end_date = datetime(year + 1, 1, 1, 0, 0, 0)
                else:
                    end_date = datetime(year, mon + 1, 1, 0, 0, 0)

                query["created_at"] = {
                    "$gte": start_date,
                    "$lt": end_date
                }
            except (ValueError, IndexError):
                pass

        return await self.jobs_collection.count_documents(query)

    async def delete_job(self, job_id: str) -> bool:
        result = await self.jobs_collection.delete_one({"job_id": job_id})
        return result.deleted_count > 0

    async def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        await self.checkpoints_collection.insert_one(checkpoint.model_dump())
        return f"{checkpoint.job_id}_{checkpoint.timestamp.isoformat()}"

    async def get_latest_checkpoint(self, job_id: str) -> Optional[Checkpoint]:
        data = await self.checkpoints_collection.find_one(
            {"job_id": job_id},
            sort=[("timestamp", -1)]
        )
        return Checkpoint(**data) if data else None

    async def get_progress(self, job_id: str) -> Optional[CrawlProgress]:
        job = await self.get_job(job_id)
        if not job:
            return None

        total = job.pages_crawled + job.queue_remaining + job.failed_urls
        progress_percent = (job.pages_crawled / total * 100) if total > 0 else 0

        elapsed = None
        if job.started_at:
            end_time = job.completed_at or __import__('datetime').datetime.utcnow()
            elapsed = int((end_time - job.started_at).total_seconds())

        return CrawlProgress(
            job_id=job.job_id,
            status=job.status,
            stage=job.stage,
            progress_percent=round(progress_percent, 2),
            pages_crawled=job.pages_crawled,
            assets_downloaded=job.assets_downloaded,
            queue_remaining=job.queue_remaining,
            failed_urls=job.failed_urls,
            elapsed_seconds=elapsed,
            message=job.error_message
        )
