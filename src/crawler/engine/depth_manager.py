"""Depth manager for controlling crawl depth."""
from typing import Dict, Set
from dataclasses import dataclass, field


@dataclass
class DepthManager:
    """Manages crawl depth tracking and enforcement."""
    
    max_depth: int = 5
    _depths: Dict[str, int] = field(default_factory=dict)
    _depth_urls: Dict[int, Set[str]] = field(default_factory=dict)
    
    def set_max_depth(self, max_depth: int) -> None:
        """Set maximum crawl depth."""
        self.max_depth = max(max_depth, 0)
    
    def is_allowed(self, url: str, depth: int) -> bool:
        """Check if URL is allowed at given depth."""
        if depth > self.max_depth:
            return False
        return True
    
    def record_depth(self, url: str, depth: int) -> None:
        """Record URL at specific depth."""
        self._depths[url] = depth
        if depth not in self._depth_urls:
            self._depth_urls[depth] = set()
        self._depth_urls[depth].add(url)
    
    def get_depth(self, url: str) -> int:
        """Get recorded depth for URL."""
        return self._depths.get(url, -1)
    
    def get_urls_at_depth(self, depth: int) -> Set[str]:
        """Get all URLs at specific depth."""
        return self._depth_urls.get(depth, set())
    
    def get_urls_by_depth(self) -> Dict[int, int]:
        """Get count of URLs at each depth."""
        return {d: len(urls) for d, urls in self._depth_urls.items()}
    
    def clear(self) -> None:
        """Clear all depth tracking."""
        self._depths.clear()
        self._depth_urls.clear()
    
    def to_checkpoint(self) -> Dict:
        """Export depth state for checkpointing."""
        return {
            "max_depth": self.max_depth,
            "depths": self._depths,
            "depth_urls": {str(d): list(urls) for d, urls in self._depth_urls.items()}
        }
    
    def from_checkpoint(self, data: Dict) -> None:
        """Restore depth state from checkpoint."""
        self.max_depth = data.get("max_depth", 5)
        self._depths = data.get("depths", {})
        self._depth_urls = {
            int(d): set(urls) 
            for d, urls in data.get("depth_urls", {}).items()
        }
