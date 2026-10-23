"""URL filter for crawl filtering."""
import re
from typing import List, Optional, Set
from urllib.parse import urlparse


class URLFilter:
    """Filters URLs based on patterns and rules."""
    
    def __init__(self, 
                 domain: str,
                 include_patterns: List[str] = None,
                 exclude_patterns: List[str] = None,
                 follow_external: bool = False,
                 allow_subdomains: bool = True,
                 allowed_external_sites: List[str] = None,
                 save_options: str = "full_mirror"):
        self.domain = domain.lower().strip()
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []
        self.follow_external = follow_external
        self.allow_subdomains = allow_subdomains
        self.allowed_external_sites = [s.lower().strip() for s in (allowed_external_sites or [])]
        self.save_options = save_options
        
        # Compile exclude patterns
        self._exclude_regexes = [re.compile(p, re.IGNORECASE) for p in self.exclude_patterns]
        
        # Default exclusions (common non-content URLs)
        self._default_excludes = [
            r'\.pdf$', r'\.zip$', r'\.exe$', r'\.dmg$', r'\.apk$',
            r'\.doc$', r'\.docx$', r'\.xls$', r'\.xlsx$',
            r'mailto:', r'tel:', r'javascript:',
            r'/wp-json/', r'/wp-admin/', r'/wp-includes/',
            r'/admin/', r'/login', r'/logout',
            r'\.xml\.gz$', r'\.xml\.zip$',
        ]
        self._default_exclude_regex = re.compile(
            '|'.join(self._default_excludes), 
            re.IGNORECASE
        )
    
    def _matches_pattern_crawl(self, url: str) -> bool:
        """Check if URL path starts with any of the include_patterns (Pattern Crawl mode).
        
        In pattern_crawl mode, include_patterns are treated as URL path prefixes/substrings,
        e.g. '/careers' matches 'https://example.com/careers/jobs'.
        """
        parsed = urlparse(url)
        path = parsed.path  # e.g. '/careers/senior-engineer'
        for pattern in self.include_patterns:
            # Normalise the pattern: ensure it starts with /
            p = pattern.strip()
            if not p.startswith('/'):
                p = '/' + p
            if path == p or path.startswith(p.rstrip('/') + '/'):
                return True
        return False

    def should_crawl(self, url: str, source_url: str = None) -> bool:
        """Determine if URL should be crawled."""
        if not url:
            return False
        
        parsed = urlparse(url)
        
        # Skip non-HTTP schemes
        if parsed.scheme not in ('', 'http', 'https'):
            return False
        
        # Check domain
        url_domain = parsed.netloc.lower()
        if url_domain.startswith('www.'):
            url_domain = url_domain[4:]
        
        is_external = url_domain and url_domain != self.domain
        
        # Check if it's a subdomain
        is_subdomain = url_domain and url_domain.endswith('.' + self.domain)
        
        # Domain filtering logic
        if is_external:
            # Allow specific external sites
            if self.allowed_external_sites and url_domain in self.allowed_external_sites:
                pass  # Allow this external site
            elif is_subdomain and self.allow_subdomains:
                pass  # Allow subdomain
            elif not self.follow_external:
                return False
        
        # Skip fragment-only URLs
        if url.startswith('#'):
            return False
        
        # Check default exclusions
        if self._default_exclude_regex.search(url):
            return False
        
        # Check custom exclude patterns
        for regex in self._exclude_regexes:
            if regex.search(url):
                return False
        
        # --- Pattern Crawl mode: strict path-prefix matching ---
        if self.save_options == "pattern_crawl":
            if not self.include_patterns:
                # No patterns configured → crawl nothing extra beyond entry point
                return False
            return self._matches_pattern_crawl(url)
        
        # Normal mode: check include patterns (regex on full URL)
        if self.include_patterns:
            for pattern in self.include_patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return True
            return False
        
        return True
    
    def is_asset(self, url: str) -> bool:
        """Check if URL is an asset."""
        from src.utils.url_normalizer import get_asset_type
        asset_type = get_asset_type(url)
        return asset_type != 'other'
    
    def get_url_type(self, url: str) -> str:
        """Determine URL type."""
        from src.utils.url_normalizer import get_asset_type
        return get_asset_type(url)


class DomainRateLimiter:
    """Rate limiter per domain."""
    
    def __init__(self, requests_per_second: float = 10.0):
        self.requests_per_second = requests_per_second
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request: dict = {}
    
    async def acquire(self, domain: str = "default"):
        """Acquire rate limit token."""
        import asyncio
        
        now = asyncio.get_event_loop().time()
        last = self._last_request.get(domain, 0)
        
        if last > 0:
            elapsed = now - last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
        
        self._last_request[domain] = asyncio.get_event_loop().time()


class RobotsChecker:
    """Simple robots.txt checker."""
    
    def __init__(self):
        self._rules: dict = {}
    
    def parse_robots_txt(self, content: str, user_agent: str = '*') -> None:
        """Parse robots.txt content."""
        lines = content.split('\n')
        current_ua = None
        disallowed: Set[str] = set()
        allowed: Set[str] = set()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'user-agent':
                    if current_ua and (current_ua == '*' or user_agent in current_ua):
                        self._rules[current_ua] = {
                            'disallow': disallowed,
                            'allow': allowed
                        }
                    current_ua = value
                    disallowed = set()
                    allowed = set()
                elif key == 'disallow' and current_ua:
                    disallowed.add(value)
                elif key == 'allow' and current_ua:
                    allowed.add(value)
        
        if current_ua:
            self._rules[current_ua] = {
                'disallow': disallowed,
                'allow': allowed
            }
    
    def is_allowed(self, path: str, user_agent: str = '*') -> bool:
        """Check if path is allowed for user agent."""
        # Find matching user agent
        ua_rules = None
        if user_agent in self._rules:
            ua_rules = self._rules[user_agent]
        elif '*' in self._rules:
            ua_rules = self._rules['*']
        
        if not ua_rules:
            return True
        
        # Check allow rules first (they take precedence)
        for allow_path in ua_rules.get('allow', set()):
            if path.startswith(allow_path):
                return True
        
        # Check disallow rules
        for disallow_path in ua_rules.get('disallow', set()):
            if path.startswith(disallow_path):
                return False
        
        return True
