"""Link extractor for HTML content."""
import warnings
from typing import List, Dict
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Suppress XML parsing warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class LinkExtractor:
    """Extract links from HTML content."""
    
    def __init__(self, base_domain: str = None):
        self.base_domain = base_domain
    
    def extract(self, html: bytes or str, base_url: str) -> List[Dict]:
        """Extract all links from HTML."""
        links = []
        
        try:
            if isinstance(html, bytes):
                soup = BeautifulSoup(html, 'lxml')
            else:
                soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return links
        
        # Extract <a> tags
        for tag in soup.find_all('a', href=True):
            href = tag.get('href', '').strip()
            if not href or href.startswith('#'):
                continue
            
            absolute_url = urljoin(base_url, href)
            
            links.append({
                "url": absolute_url,
                "text": tag.get_text(strip=True),
                "title": tag.get('title', ''),
                "is_external": self._is_external(absolute_url),
                "is_canonical": False,
                "is_redirect": False,
                "is_js": False,
                "tag": "a"
            })
        
        # Extract canonical URL
        canonical = soup.find('link', rel='canonical', href=True)
        if canonical:
            href = canonical.get('href', '').strip()
            if href:
                absolute_url = urljoin(base_url, href)
                links.append({
                    "url": absolute_url,
                    "text": "",
                    "is_external": self._is_external(absolute_url),
                    "is_canonical": True,
                    "is_redirect": False,
                    "is_js": False,
                    "tag": "link[rel=canonical]"
                })
        
        # Extract redirect/refresh meta
        refresh = soup.find('meta', attrs={'http-equiv': 'refresh'})
        if refresh:
            content = refresh.get('content', '')
            if 'url=' in content.lower():
                url_part = content.split('url=')[1].strip().strip('"\'')
                absolute_url = urljoin(base_url, url_part)
                links.append({
                    "url": absolute_url,
                    "text": "",
                    "is_external": self._is_external(absolute_url),
                    "is_canonical": False,
                    "is_redirect": True,
                    "is_js": False,
                    "tag": "meta[http-equiv=refresh]"
                })
        
        # Extract JS navigation (window.location)
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                script_text = script.string
                # Look for window.location patterns
                import re
                location_patterns = [
                    r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
                    r'window\.location\s*=\s*["\']([^"\']+)["\']',
                    r'location\.href\s*=\s*["\']([^"\']+)["\']',
                    r'location\.replace\s*\(\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in location_patterns:
                    matches = re.findall(pattern, script_text)
                    for match in matches:
                        absolute_url = urljoin(base_url, match)
                        links.append({
                            "url": absolute_url,
                            "text": "",
                            "is_external": self._is_external(absolute_url),
                            "is_canonical": False,
                            "is_redirect": False,
                            "is_js": True,
                            "tag": "script[window.location]"
                        })
        
        return links
    
    def _is_external(self, url: str) -> bool:
        """Check if URL is external."""
        if not self.base_domain:
            return False
        
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return domain != self.base_domain.lower()


class HTMLExtractor:
    """Extract structured content from HTML for AI training."""
    
    def extract(self, html: bytes or str, url: str) -> 'HTMLContent':
        """Extract clean content from HTML."""
        from src.core.models import HTMLContent
        
        try:
            if isinstance(html, bytes):
                soup = BeautifulSoup(html, 'lxml')
            else:
                soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return None
        
        # Remove unwanted elements
        for element in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Extract title
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
        
        # Extract meta description
        meta_desc = ""
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta:
            meta_desc = meta.get('content', '')
        
        # Extract headings
        headings = {}
        for level in range(1, 7):
            h_tags = soup.find_all(f'h{level}')
            headings[f'h{level}'] = [h.get_text(strip=True) for h in h_tags]
        
        # Extract main content
        # Try to find main content area
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
        
        if not main_content:
            # Use body as fallback
            main_content = soup.find('body')
        
        # Get clean text
        content = ""
        if main_content:
            # Remove remaining navigation-like elements
            for nav in main_content.find_all(['nav', 'footer', 'header']):
                nav.decompose()
            
            content = main_content.get_text(separator='\n', strip=True)
        
        # Extract links
        links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href and not href.startswith('#'):
                from urllib.parse import urljoin
                links.append({
                    "url": urljoin(url, href),
                    "text": link.get_text(strip=True)
                })
        
        # Extract images
        images = []
        for img in soup.find_all('img', src=True):
            images.append({
                "src": urljoin(url, img.get('src')),
                "alt": img.get('alt', ''),
                "title": img.get('title', '')
            })
        
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if domain.startswith('www.'):
            domain = domain[4:]
        
        from src.database.mongo_client import MongoDB
        db = MongoDB.get_db()
        
        # Get job_id from context (this is a simplified version)
        # In real implementation, job_id should be passed through
        job_id = "extracted"
        
        return HTMLContent(
            url=url,
            domain=domain,
            job_id=job_id,
            title=title,
            meta_description=meta_desc,
            headings=headings,
            content=content,
            links=links,
            images=images
        )
