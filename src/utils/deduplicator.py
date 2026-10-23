"""URL deduplication with Bloom filter and set-based tracking."""
import hashlib
from typing import Set, Optional
from dataclasses import dataclass, field


@dataclass
class Deduplicator:
    """URL deduplicator using multiple strategies."""
    
    # Exact match set
    seen_urls: Set[str] = field(default_factory=set)
    
    # Normalized URL set
    seen_normalized: Set[str] = field(default_factory=set)
    
    # Content hash set for duplicate detection
    content_hashes: Set[str] = field(default_factory=set)
    
    # Statistics
    duplicates_found: int = 0
    content_duplicates: int = 0
    
    def is_seen(self, url: str, normalized: Optional[str] = None) -> bool:
        """Check if URL has been seen."""
        if url in self.seen_urls:
            return True
        if normalized and normalized in self.seen_normalized:
            return True
        return False
    
    def add(self, url: str, normalized: Optional[str] = None) -> bool:
        """Add URL to seen set. Returns False if already seen."""
        if self.is_seen(url, normalized):
            self.duplicates_found += 1
            return False
        
        self.seen_urls.add(url)
        if normalized:
            self.seen_normalized.add(normalized)
        return True
    
    def is_content_duplicate(self, content: str) -> bool:
        """Check if content is duplicate using hash."""
        content_hash = hashlib.md5(content.encode()).hexdigest()
        if content_hash in self.content_hashes:
            self.content_duplicates += 1
            return True
        return False
    
    def add_content_hash(self, content: str) -> None:
        """Add content hash to seen set."""
        content_hash = hashlib.md5(content.encode()).hexdigest()
        self.content_hashes.add(content_hash)
    
    def get_stats(self) -> dict:
        """Get deduplication statistics."""
        return {
            "unique_urls": len(self.seen_urls),
            "normalized_urls": len(self.seen_normalized),
            "content_hashes": len(self.content_hashes),
            "duplicates_found": self.duplicates_found,
            "content_duplicates": self.content_duplicates
        }
    
    def clear(self) -> None:
        """Clear all tracked URLs."""
        self.seen_urls.clear()
        self.seen_normalized.clear()
        self.content_hashes.clear()
        self.duplicates_found = 0
        self.content_duplicates = 0


class DomainDeduplicator:
    """Per-domain deduplicator for multi-domain crawling."""
    
    def __init__(self):
        self._dedups: dict = {}
    
    def get_dedup(self, domain: str) -> Deduplicator:
        """Get or create deduplicator for domain."""
        if domain not in self._dedups:
            self._dedups[domain] = Deduplicator()
        return self._dedups[domain]
    
    def is_seen(self, url: str, domain: str, normalized: Optional[str] = None) -> bool:
        """Check if URL is seen in domain."""
        return self.get_dedup(domain).is_seen(url, normalized)
    
    def add(self, url: str, domain: str, normalized: Optional[str] = None) -> bool:
        """Add URL to domain deduplicator."""
        return self.get_dedup(domain).add(url, normalized)
    
    def clear_domain(self, domain: str) -> None:
        """Clear deduplicator for specific domain."""
        if domain in self._dedups:
            self._dedups[domain].clear()
    
    def clear_all(self) -> None:
        """Clear all deduplicators."""
        self._dedups.clear()
