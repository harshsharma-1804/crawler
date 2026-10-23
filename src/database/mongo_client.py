"""MongoDB client and connection management."""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from src.core.settings import get_settings


class MongoDB:
    """MongoDB client singleton."""
    _client: AsyncIOMotorClient = None
    _db: AsyncIOMotorDatabase = None

    @classmethod
    async def connect(cls) -> AsyncIOMotorClient:
        if cls._client is None:
            settings = get_settings()
            cls._client = AsyncIOMotorClient(
                settings.mongodb_url,
                maxPoolSize=50,
                minPoolSize=10,
                serverSelectionTimeoutMS=5000,
            )
            cls._db = cls._client[settings.mongodb_db_name]
        return cls._client

    @classmethod
    async def disconnect(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        if cls._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return cls._db

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        if cls._client is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return cls._client


async def get_database() -> AsyncIOMotorDatabase:
    await MongoDB.connect()
    return MongoDB.get_db()
