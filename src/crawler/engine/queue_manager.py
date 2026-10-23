"""Queue manager for crawl jobs."""
import asyncio
from typing import Optional, List, Set, Dict, Callable
from dataclasses import dataclass, field
from src.core.models import QueueItem, DiscoveryType


@dataclass
class QueueManager:
    """Manages crawl and asset queues with priority support."""
    
    # Main crawl queue (HTML pages)
    crawl_queue: asyncio.PriorityQueue = field(default_factory=lambda: asyncio.PriorityQueue())
    
    # Asset download queue
    asset_queue: asyncio.PriorityQueue = field(default_factory=lambda: asyncio.PriorityQueue())
    
    # Tracking sets
    visited_urls: Set[str] = field(default_factory=set)
    discovered_urls: Set[str] = field(default_factory=set)
    failed_urls: Set[str] = field(default_factory=set)
    asset_urls: Set[str] = field(default_factory=set)
    
    # Counters
    total_queued: int = 0
    total_assets_queued: int = 0
    
    # Callbacks
    _on_url_added: Optional[Callable[[QueueItem], None]] = None
    _on_asset_added: Optional[Callable[[str], None]] = None
    
    def set_callbacks(self, on_url_added: Callable = None, on_asset_added: Callable = None):
        """Set event callbacks."""
        self._on_url_added = on_url_added
        self._on_asset_added = on_asset_added
    
    async def add_url(self, item: QueueItem, skip_duplicates: bool = True) -> bool:
        """Add URL to crawl queue."""
        if skip_duplicates and item.url in self.discovered_urls:
            return False
        
        if item.url in self.visited_urls or item.url in self.failed_urls:
            return False
        
        # Priority: lower number = higher priority
        # Entry points and sitemaps get priority
        priority_override = {
            DiscoveryType.ENTRY_POINT: 1,
            DiscoveryType.SITEMAP: 2,
            DiscoveryType.ORPHAN: 2,
            DiscoveryType.CANONICAL: 3,
            DiscoveryType.HTML_LINK: 5,
            DiscoveryType.REDIRECT: 4,
            DiscoveryType.JS_NAVIGATION: 6,
        }
        
        priority = priority_override.get(item.discovery_type, item.priority)
        
        # Add to queue (priority, item) - priority queue sorts by first element
        await self.crawl_queue.put((priority, self.total_queued, item))
        
        self.discovered_urls.add(item.url)
        self.total_queued += 1
        
        if self._on_url_added:
            self._on_url_added(item)
        
        return True
    
    async def add_urls_batch(self, items: List[QueueItem]) -> int:
        """Add multiple URLs to queue."""
        added = 0
        for item in items:
            if await self.add_url(item):
                added += 1
        return added
    
    async def add_asset(self, url: str, asset_type: str = "other", parent_url: str = None) -> bool:
        """Add asset to download queue."""
        if url in self.asset_urls:
            return False
        
        # Assets have lower priority (higher number)
        priority = 10
        if asset_type == "css":
            priority = 8  # CSS is more important
        elif asset_type == "js":
            priority = 9
        
        await self.asset_queue.put((priority, self.total_assets_queued, {
            "url": url,
            "type": asset_type,
            "parent": parent_url
        }))
        
        self.asset_urls.add(url)
        self.total_assets_queued += 1
        
        if self._on_asset_added:
            self._on_asset_added(url)
        
        return True
    
    async def get_next_url(self, timeout: Optional[float] = None) -> Optional[QueueItem]:
        """Get next URL from crawl queue."""
        try:
            _, _, item = await asyncio.wait_for(self.crawl_queue.get(), timeout=timeout)
            return item
        except asyncio.TimeoutError:
            return None
    
    async def get_next_asset(self, timeout: Optional[float] = None) -> Optional[Dict]:
        """Get next asset from asset queue."""
        try:
            _, _, asset = await asyncio.wait_for(self.asset_queue.get(), timeout=timeout)
            return asset
        except asyncio.TimeoutError:
            return None
    
    def mark_visited(self, url: str) -> None:
        """Mark URL as visited."""
        self.visited_urls.add(url)
        self.discovered_urls.discard(url)
    
    def mark_failed(self, url: str) -> None:
        """Mark URL as failed."""
        self.failed_urls.add(url)
        self.discovered_urls.discard(url)
    
    def mark_asset_downloaded(self, url: str) -> None:
        """Mark asset as downloaded."""
        # Asset stays in asset_urls to prevent re-download
        pass
    
    def is_visited(self, url: str) -> bool:
        """Check if URL was visited."""
        return url in self.visited_urls
    
    def is_discovered(self, url: str) -> bool:
        """Check if URL is in discovered set."""
        return url in self.discovered_urls
    
    def is_failed(self, url: str) -> bool:
        """Check if URL failed."""
        return url in self.failed_urls
    
    def is_asset_queued(self, url: str) -> bool:
        """Check if asset is already queued."""
        return url in self.asset_urls
    
    def get_stats(self) -> Dict:
        """Get queue statistics."""
        return {
            "crawl_queue_size": self.crawl_queue.qsize(),
            "asset_queue_size": self.asset_queue.qsize(),
            "visited_urls": len(self.visited_urls),
            "discovered_urls": len(self.discovered_urls),
            "failed_urls": len(self.failed_urls),
            "asset_urls": len(self.asset_urls),
            "total_queued": self.total_queued,
            "total_assets_queued": self.total_assets_queued
        }
    
    def get_remaining(self) -> int:
        """Get remaining items in crawl queue."""
        return self.crawl_queue.qsize()
    
    def get_remaining_assets(self) -> int:
        """Get remaining assets in queue."""
        return self.asset_queue.qsize()
    
    def clear(self) -> None:
        """Clear all queues and tracking."""
        # Drain queues
        while not self.crawl_queue.empty():
            try:
                self.crawl_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        while not self.asset_queue.empty():
            try:
                self.asset_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.visited_urls.clear()
        self.discovered_urls.clear()
        self.failed_urls.clear()
        self.asset_urls.clear()
        self.total_queued = 0
        self.total_assets_queued = 0
    
    def to_checkpoint(self) -> Dict:
        """Export queue state for checkpointing."""
        return {
            "visited_urls": list(self.visited_urls),
            "discovered_urls": list(self.discovered_urls),
            "failed_urls": list(self.failed_urls),
            "asset_urls": list(self.asset_urls),
            "total_queued": self.total_queued,
            "total_assets_queued": self.total_assets_queued
        }
    
    def from_checkpoint(self, data: Dict) -> None:
        """Restore queue state from checkpoint."""
        self.visited_urls = set(data.get("visited_urls", []))
        self.discovered_urls = set(data.get("discovered_urls", []))
        self.failed_urls = set(data.get("failed_urls", []))
        self.asset_urls = set(data.get("asset_urls", []))
        self.total_queued = data.get("total_queued", 0)
        self.total_assets_queued = data.get("total_assets_queued", 0)
