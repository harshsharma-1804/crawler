"""Sitemap parser for XML sitemaps and uploaded URL files.

Classes
-------
SitemapParser       — parse XML sitemap / sitemap-index content (unchanged).
UploadedFileParser  — extract URLs from uploaded CSV, XLSX, or XML files.
RobotsHandler       — parse and query robots.txt rules.
OrphanHandler       — generate common orphan-page URL candidates.
"""
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Union


class SitemapParser:
    """Parse XML sitemaps (sitemap.xml and sitemap_index.xml)."""
    
    def __init__(self):
        self.namespaces = {
            'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'image': 'http://www.google.com/schemas/sitemap-image/1.1',
            'video': 'http://www.google.com/schemas/sitemap-video/1.1',
            'news': 'http://www.google.com/schemas/sitemap-news/0.9'
        }
    
    def parse(self, content: str) -> List[Dict]:
        """Parse sitemap XML content."""
        urls = []
        
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return urls
        
        # Check if this is a sitemap index
        if self._is_sitemap_index(root):
            return self._parse_sitemap_index(root)
        
        # Regular sitemap
        for url_elem in root.findall('.//sitemap:url', self.namespaces):
            url_data = self._parse_url_element(url_elem)
            if url_data:
                urls.append(url_data)
        
        # Also try without namespace
        if not urls:
            for url_elem in root.findall('.//url'):
                url_data = self._parse_url_element(url_elem)
                if url_data:
                    urls.append(url_data)
        
        return urls
    
    def _is_sitemap_index(self, root) -> bool:
        """Check if this is a sitemap index file."""
        tag = root.tag
        return 'sitemapindex' in tag.lower()
    
    def _parse_sitemap_index(self, root) -> List[Dict]:
        """Parse sitemap index to get child sitemap URLs."""
        urls = []
        
        for sitemap_elem in root.findall('.//sitemap:sitemap', self.namespaces):
            loc = sitemap_elem.find('sitemap:loc', self.namespaces)
            if loc is not None and loc.text:
                urls.append({
                    "type": "sitemap",
                    "loc": loc.text.strip(),
                    "lastmod": "",
                    "changefreq": "",
                    "priority": ""
                })
        
        # Try without namespace
        if not urls:
            for sitemap_elem in root.findall('.//sitemap'):
                loc = sitemap_elem.find('loc')
                if loc is not None and loc.text:
                    urls.append({
                        "type": "sitemap",
                        "loc": loc.text.strip(),
                        "lastmod": "",
                        "changefreq": "",
                        "priority": ""
                    })
        
        return urls
    
    def _parse_url_element(self, url_elem) -> Dict:
        """Parse a single URL element."""
        url_data = {"type": "url"}
        
        # Required: loc
        loc = url_elem.find('sitemap:loc', self.namespaces)
        if loc is None:
            loc = url_elem.find('loc')
        
        if loc is None or not loc.text:
            return None
        
        url_data["loc"] = loc.text.strip()
        
        # Optional: lastmod
        lastmod = url_elem.find('sitemap:lastmod', self.namespaces)
        if lastmod is None:
            lastmod = url_elem.find('lastmod')
        if lastmod is not None and lastmod.text:
            url_data["lastmod"] = lastmod.text
        
        # Optional: changefreq
        changefreq = url_elem.find('sitemap:changefreq', self.namespaces)
        if changefreq is None:
            changefreq = url_elem.find('changefreq')
        if changefreq is not None and changefreq.text:
            url_data["changefreq"] = changefreq.text
        
        # Optional: priority
        priority = url_elem.find('sitemap:priority', self.namespaces)
        if priority is None:
            priority = url_elem.find('priority')
        if priority is not None and priority.text:
            url_data["priority"] = priority.text
        
        # Image sitemap extensions
        images = url_elem.findall('image:image', self.namespaces)
        if images:
            url_data["images"] = []
            for img in images:
                img_loc = img.find('image:loc', self.namespaces)
                if img_loc is not None and img_loc.text:
                    url_data["images"].append(img_loc.text.strip())
        
        # Video sitemap extensions
        videos = url_elem.findall('video:video', self.namespaces)
        if videos:
            url_data["videos"] = []
            for vid in videos:
                vid_loc = vid.find('video:content_loc', self.namespaces)
                if vid_loc is not None and vid_loc.text:
                    url_data["videos"].append(vid_loc.text.strip())
        
        return url_data


class RobotsHandler:
    """Handle robots.txt parsing and checking."""
    
    def __init__(self):
        self.rules = {}
    
    def parse(self, content: str) -> Dict:
        """Parse robots.txt content."""
        lines = content.split('\n')
        current_ua = None
        rules = {}
        
        for line in lines:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Remove inline comments
            if '#' in line:
                line = line.split('#')[0].strip()
            
            if ':' in line:
                parts = line.split(':', 1)
                key = parts[0].strip().lower()
                value = parts[1].strip() if len(parts) > 1 else ''
                
                if key == 'user-agent':
                    current_ua = value
                    if current_ua not in rules:
                        rules[current_ua] = {'allow': [], 'disallow': [], 'crawl-delay': None}
                
                elif key == 'allow' and current_ua:
                    rules[current_ua]['allow'].append(value)
                
                elif key == 'disallow' and current_ua:
                    rules[current_ua]['disallow'].append(value)
                
                elif key == 'crawl-delay' and current_ua:
                    try:
                        rules[current_ua]['crawl-delay'] = float(value)
                    except ValueError:
                        pass
                
                elif key == 'sitemap':
                    if 'sitemaps' not in rules:
                        rules['sitemaps'] = []
                    rules['sitemaps'].append(value)
        
        self.rules = rules
        return rules
    
    def is_allowed(self, path: str, user_agent: str = '*') -> bool:
        """Check if path is allowed for user agent."""
        # Find matching user agent rules
        ua_rules = None
        if user_agent in self.rules:
            ua_rules = self.rules[user_agent]
        elif '*' in self.rules:
            ua_rules = self.rules['*']
        
        if not ua_rules:
            return True
        
        # Check allow rules first (they take precedence)
        for allow_path in ua_rules.get('allow', []):
            if self._matches(path, allow_path):
                return True
        
        # Check disallow rules
        for disallow_path in ua_rules.get('disallow', []):
            if self._matches(path, disallow_path):
                return False
        
        return True
    
    def get_crawl_delay(self, user_agent: str = '*') -> float:
        """Get crawl delay for user agent."""
        if user_agent in self.rules and self.rules[user_agent].get('crawl-delay'):
            return self.rules[user_agent]['crawl-delay']
        if '*' in self.rules:
            return self.rules['*'].get('crawl-delay', 0)
        return 0
    
    def get_sitemaps(self) -> List[str]:
        """Get sitemap URLs from robots.txt."""
        return self.rules.get('sitemaps', [])
    
    def _matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern."""
        # Simple pattern matching
        if pattern.endswith('*'):
            return path.startswith(pattern[:-1])
        return path.startswith(pattern)


class OrphanHandler:
    """Handle orphan pages - pages not linked from main site."""
    
    def __init__(self, domain: str):
        self.domain = domain
    
    def generate_common_orphans(self) -> List[str]:
        """Generate common orphan page URLs."""
        common_paths = [
            '/robots.txt',
            '/sitemap.xml',
            '/favicon.ico',
            '/.well-known/security.txt',
            '/humans.txt',
            '/api',
            '/feed',
            '/rss',
            '/atom.xml',
            '/404',
            '/error',
            '/search',
            '/login',
            '/admin',
            '/privacy',
            '/terms',
            '/contact',
            '/about',
            '/help',
            '/faq',
            '/blog',
            '/news',
            '/archive',
            '/sitemap',
        ]
        
        orphans = [f"https://{self.domain}{path}" for path in common_paths]
        return orphans
    
    def validate_orphan(self, url: str, http_client) -> bool:
        """Check if orphan URL exists and returns valid content."""
        import asyncio
        
        try:
            response = asyncio.run(http_client.head(url, timeout=10))
            return response.status_code < 400
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Uploaded file parser — CSV, XLSX, XML sitemap
# ---------------------------------------------------------------------------

class UploadedFileParser:
    """Extract a flat list of URLs from user-uploaded files.

    Supported formats
    -----------------
    .csv   — any column whose header contains "url" (case-insensitive), or the
             first column if no URL column is found.
    .xlsx  — same column-detection logic as CSV.
    .xml   — treated as a sitemap XML; uses SitemapParser internally.
             Only ``<loc>`` URLs are returned (sub-sitemap URLs are included
             but not recursively fetched at this stage).

    Usage
    -----
    >>> parser = UploadedFileParser()
    >>> urls = parser.parse_bytes(file_bytes, filename="urls.csv")
    >>> urls = parser.parse_path(Path("/tmp/sitemap.xml"))
    """

    # Candidate column name fragments (lowercase); checked in order
    _URL_COLUMN_HINTS = ("url", "link", "href", "address", "page")

    def parse_bytes(self, data: bytes, filename: str) -> List[str]:
        """Parse raw file bytes given the original filename (used for extension detection)."""
        ext = Path(filename).suffix.lower()
        if ext == ".csv":
            return self._parse_csv_bytes(data)
        if ext in (".xlsx", ".xls", ".xlsm"):
            return self._parse_xlsx_bytes(data)
        if ext == ".xml":
            return self._parse_xml_bytes(data)
        # Unknown extension — try XML first, then CSV as fallback
        xml_urls = self._parse_xml_bytes(data)
        if xml_urls:
            return xml_urls
        return self._parse_csv_bytes(data)

    def parse_path(self, path: Union[str, Path]) -> List[str]:
        """Parse a file on disk."""
        p = Path(path)
        return self.parse_bytes(p.read_bytes(), p.name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_csv_bytes(self, data: bytes) -> List[str]:
        try:
            import pandas as pd
            df = pd.read_csv(io.BytesIO(data), dtype=str, on_bad_lines="skip")
            return self._extract_urls_from_dataframe(df)
        except Exception as exc:
            print(f"[UploadedFileParser] CSV parse error: {exc}")
            return []

    def _parse_xlsx_bytes(self, data: bytes) -> List[str]:
        try:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(data), dtype=str, engine="openpyxl")
            return self._extract_urls_from_dataframe(df)
        except Exception as exc:
            print(f"[UploadedFileParser] XLSX parse error: {exc}")
            return []

    def _parse_xml_bytes(self, data: bytes) -> List[str]:
        try:
            text = data.decode("utf-8", errors="replace")
            parser = SitemapParser()
            entries = parser.parse(text)
            urls = []
            for entry in entries:
                loc = entry.get("loc", "").strip()
                if loc and loc.startswith("http"):
                    urls.append(loc)
            print(f"[UploadedFileParser] XML sitemap: {len(urls)} URLs extracted")
            return urls
        except Exception as exc:
            print(f"[UploadedFileParser] XML parse error: {exc}")
            return []

    def _extract_urls_from_dataframe(self, df) -> List[str]:
        """Find the best URL column and return clean http(s) values."""
        if df.empty:
            return []

        # Detect the best URL column by header hint
        url_col = None
        for col in df.columns:
            col_lower = str(col).lower()
            if any(hint in col_lower for hint in self._URL_COLUMN_HINTS):
                url_col = col
                break

        # Fallback: use the first column
        if url_col is None:
            url_col = df.columns[0]

        urls = []
        for raw in df[url_col].dropna():
            val = str(raw).strip()
            if val.startswith("http://") or val.startswith("https://"):
                urls.append(val)
            elif val and "." in val:
                # Bare domain/path like "example.com/page" — prepend https
                urls.append(f"https://{val}")

        # Deduplicate while preserving order
        seen: set = set()
        deduped = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)

        print(f"[UploadedFileParser] Extracted {len(deduped)} unique URLs from column '{url_col}'")
        return deduped
