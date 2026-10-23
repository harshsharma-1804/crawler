"""Content indexer for MongoDB operations."""
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from src.core.models import URLRecord, AssetRecord, HTMLContent
from src.database.mongo_client import MongoDB


class ContentIndexer:
    """Indexer for crawled content."""

    def __init__(self, db: AsyncIOMotorDatabase = None):
        self.db = db or MongoDB.get_db()
        self.urls_collection = self.db.urls
        self.assets_collection = self.db.assets
        self.html_content_collection = self.db.html_content

    async def index_url(self, record: URLRecord) -> str:
        await self.urls_collection.update_one(
            {"url": record.url, "job_id": record.job_id},
            {"$set": record.model_dump()},
            upsert=True
        )
        return record.url

    async def index_urls_batch(self, records: List[URLRecord]) -> int:
        if not records:
            return 0
        operations = [
            {
                "updateOne": {
                    "filter": {"url": r.url, "job_id": r.job_id},
                    "update": {"$set": r.model_dump()},
                    "upsert": True
                }
            }
            for r in records
        ]
        result = await self.urls_collection.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    async def index_asset(self, record: AssetRecord) -> str:
        await self.assets_collection.update_one(
            {"url": record.url, "job_id": record.job_id},
            {"$set": record.model_dump()},
            upsert=True
        )
        return record.url

    async def index_assets_batch(self, records: List[AssetRecord]) -> int:
        if not records:
            return 0
        operations = [
            {
                "updateOne": {
                    "filter": {"url": r.url, "job_id": r.job_id},
                    "update": {"$set": r.model_dump()},
                    "upsert": True
                }
            }
            for r in records
        ]
        result = await self.assets_collection.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    async def index_html_content(self, content: HTMLContent) -> str:
        await self.html_content_collection.update_one(
            {"url": content.url, "job_id": content.job_id},
            {"$set": content.model_dump()},
            upsert=True
        )
        return content.url

    async def get_url(self, url: str, job_id: str) -> Optional[URLRecord]:
        data = await self.urls_collection.find_one({"url": url, "job_id": job_id})
        return URLRecord(**data) if data else None

    async def get_urls_by_job(self, job_id: str, success_only: bool = False) -> List[URLRecord]:
        query = {"job_id": job_id}
        if success_only:
            query["crawl_success"] = True
        cursor = self.urls_collection.find(query)
        return [URLRecord(**doc) async for doc in cursor]

    async def get_assets_by_job(self, job_id: str, asset_type: str = None) -> List[AssetRecord]:
        query = {"job_id": job_id}
        if asset_type:
            query["asset_type"] = asset_type
        cursor = self.assets_collection.find(query)
        return [AssetRecord(**doc) async for doc in cursor]

    async def get_html_content(self, url: str, job_id: str) -> Optional[HTMLContent]:
        data = await self.html_content_collection.find_one({"url": url, "job_id": job_id})
        return HTMLContent(**data) if data else None

    async def get_html_content_by_job(self, job_id: str, limit: int = 1000) -> List[HTMLContent]:
        cursor = self.html_content_collection.find({"job_id": job_id}).limit(limit)
        return [HTMLContent(**doc) async for doc in cursor]

    async def url_exists(self, url: str, job_id: str) -> bool:
        count = await self.urls_collection.count_documents({"url": url, "job_id": job_id}, limit=1)
        return count > 0

    async def asset_exists(self, url: str, job_id: str) -> bool:
        count = await self.assets_collection.count_documents({"url": url, "job_id": job_id}, limit=1)
        return count > 0

    async def delete_job_content(self, job_id: str) -> dict:
        urls_result = await self.urls_collection.delete_many({"job_id": job_id})
        assets_result = await self.assets_collection.delete_many({"job_id": job_id})
        html_result = await self.html_content_collection.delete_many({"job_id": job_id})
        return {
            "urls_deleted": urls_result.deleted_count,
            "assets_deleted": assets_result.deleted_count,
            "html_deleted": html_result.deleted_count
        }
