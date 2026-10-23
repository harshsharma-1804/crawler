"""Server builder for creating offline mirror."""
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin
import aiofiles
from bs4 import BeautifulSoup

from src.core.settings import get_settings
from src.storage.path_builder import PathBuilder
from src.storage.filesystem_storage import FilesystemStorage


class ServerBuilder:
    """Build offline server mirror from crawled content."""
    
    def __init__(self):
        self.settings = get_settings()
        self.path_builder = PathBuilder()
        self.storage = FilesystemStorage()
    
    async def build_server_mirror(self, domain: str, job_id: str) -> Path:
        """Build offline server mirror for domain."""
        # Get source and destination directories
        src_html_dir = self.settings.html_dir / domain
        dst_server_dir = self.settings.server_dir / domain
        
        if not src_html_dir.exists():
            raise ValueError(f"No crawled content found for domain: {domain}")
        
        # Ensure destination exists
        dst_server_dir.mkdir(parents=True, exist_ok=True)
        
        # Process all HTML files
        for html_file in src_html_dir.rglob('*.html'):
            await self._process_html_file(html_file, domain, dst_server_dir)
        
        # Copy assets
        await self._copy_assets(domain, dst_server_dir)
        
        # Create index.html for root if needed
        await self._ensure_root_index(dst_server_dir)
        
        return dst_server_dir
    
    async def _process_html_file(self, src_file: Path, domain: str, dst_dir: Path):
        """Process HTML file for offline serving."""
        # Read source
        async with aiofiles.open(src_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        
        # Get relative path from domain root
        rel_path = src_file.relative_to(self.settings.html_dir / domain)
        dst_file = dst_dir / rel_path
        
        # Ensure destination directory exists
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Rewrite URLs in content
        processed_content = await self._rewrite_urls(content, domain, str(rel_path))
        
        # Write processed content
        async with aiofiles.open(dst_file, 'w', encoding='utf-8') as f:
            await f.write(processed_content)
    
    async def _rewrite_urls(self, content: str, domain: str, current_path: str) -> str:
        """Rewrite URLs to point to local files."""
        try:
            soup = BeautifulSoup(content, 'lxml')
        except Exception:
            return content
        
        current_depth = len(Path(current_path).parts) - 1
        path_prefix = '../' * current_depth if current_depth > 0 else './'
        
        # Rewrite <a> tags
        for tag in soup.find_all('a', href=True):
            href = tag['href']
            new_href = self._rewrite_url(href, domain, path_prefix)
            if new_href:
                tag['href'] = new_href
        
        # Rewrite <link> tags (CSS, icons)
        for tag in soup.find_all('link', href=True):
            href = tag['href']
            new_href = self._rewrite_url(href, domain, path_prefix, is_asset=True)
            if new_href:
                tag['href'] = new_href
        
        # Rewrite <script> tags
        for tag in soup.find_all('script', src=True):
            src = tag['src']
            new_src = self._rewrite_url(src, domain, path_prefix, is_asset=True)
            if new_src:
                tag['src'] = new_src
        
        # Rewrite <img> tags
        for tag in soup.find_all('img', src=True):
            src = tag['src']
            new_src = self._rewrite_url(src, domain, path_prefix, is_asset=True)
            if new_src:
                tag['src'] = new_src
        
        # Rewrite <img> data-src
        for tag in soup.find_all('img', attrs={'data-src': True}):
            src = tag['data-src']
            new_src = self._rewrite_url(src, domain, path_prefix, is_asset=True)
            if new_src:
                tag['data-src'] = new_src
        
        # Rewrite <source> tags
        for tag in soup.find_all('source', src=True):
            src = tag['src']
            new_src = self._rewrite_url(src, domain, path_prefix, is_asset=True)
            if new_src:
                tag['src'] = new_src
        
        # Rewrite srcset
        for tag in soup.find_all(attrs={'srcset': True}):
            srcset = tag['srcset']
            new_srcset = self._rewrite_srcset(srcset, domain, path_prefix)
            tag['srcset'] = new_srcset
        
        # Rewrite inline styles
        for tag in soup.find_all(style=True):
            style = tag['style']
            new_style = self._rewrite_css_urls(style, domain, path_prefix)
            tag['style'] = new_style
        
        return str(soup)
    
    def _rewrite_url(self, url: str, domain: str, path_prefix: str, 
                     is_asset: bool = False) -> Optional[str]:
        """Rewrite single URL to local path."""
        # Skip external URLs
        if url.startswith('http://') or url.startswith('https://'):
            parsed = urlparse(url)
            url_domain = parsed.netloc.lower()
            if url_domain.startswith('www.'):
                url_domain = url_domain[4:]
            if url_domain != domain.lower():
                return None  # Keep external URLs as-is
            # Same domain, extract path
            url = parsed.path
        
        # Skip data URLs and anchors
        if url.startswith('data:') or url.startswith('#'):
            return None
        
        # Skip javascript and mailto
        if url.startswith('javascript:') or url.startswith('mailto:'):
            return None
        
        # Remove leading slash
        if url.startswith('/'):
            url = url[1:]
        
        if is_asset:
            # Determine asset type
            asset_type = self._detect_asset_type(url)
            type_folders = {
                'css': 'css',
                'js': 'js',
                'image': 'images',
                'icon': 'images',
                'pdf': 'pdfs',
                'font': 'fonts',
                'video': 'videos',
            }
            folder = type_folders.get(asset_type, 'images')
            return f"{path_prefix}{folder}/{url}"
        else:
            # HTML link
            if '.' not in url.split('/')[-1]:
                # Directory-style URL
                return f"{path_prefix}{url}/index.html"
            else:
                return f"{path_prefix}{url}"
    
    def _rewrite_srcset(self, srcset: str, domain: str, path_prefix: str) -> str:
        """Rewrite srcset attribute."""
        parts = srcset.split(',')
        new_parts = []
        
        for part in parts:
            part = part.strip()
            pieces = part.split()
            if pieces:
                url = pieces[0]
                new_url = self._rewrite_url(url, domain, path_prefix, is_asset=True)
                if new_url:
                    new_part = ' '.join([new_url] + pieces[1:])
                    new_parts.append(new_part)
                else:
                    new_parts.append(part)
        
        return ', '.join(new_parts)
    
    def _rewrite_css_urls(self, css_content: str, domain: str, path_prefix: str) -> str:
        """Rewrite URLs in CSS content."""
        def replace_url(match):
            url = match.group(1).strip('\'"')
            new_url = self._rewrite_url(url, domain, path_prefix, is_asset=True)
            return f'url({new_url})' if new_url else match.group(0)
        
        url_pattern = r'url\(["\']?([^"\']+)["\']?\)'
        return re.sub(url_pattern, replace_url, css_content)
    
    def _detect_asset_type(self, url: str) -> str:
        """Detect asset type from URL."""
        url_lower = url.lower()
        
        if '.css' in url_lower:
            return 'css'
        elif '.js' in url_lower:
            return 'js'
        elif '.pdf' in url_lower:
            return 'pdf'
        elif any(ext in url_lower for ext in ['.woff', '.woff2', '.ttf', '.otf', '.eot']):
            return 'font'
        elif any(ext in url_lower for ext in ['.mp4', '.webm', '.ogg']):
            return 'video'
        elif any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp']):
            return 'image'
        elif '.ico' in url_lower:
            return 'icon'
        
        return 'image'
    
    async def _copy_assets(self, domain: str, dst_dir: Path):
        """Copy assets to server directory."""
        import shutil
        
        asset_types = ['css', 'js', 'images', 'pdfs', 'fonts', 'icons', 'videos']
        
        for asset_type in asset_types:
            src_dir = self.settings.assets_dir / asset_type / domain
            if src_dir.exists():
                dst_asset_dir = dst_dir / asset_type
                dst_asset_dir.mkdir(parents=True, exist_ok=True)
                
                # Copy all files
                for src_file in src_dir.rglob('*'):
                    if src_file.is_file():
                        rel_path = src_file.relative_to(src_dir)
                        dst_file = dst_asset_dir / rel_path
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, dst_file)
    
    async def _ensure_root_index(self, dst_dir: Path):
        """Ensure root index.html exists."""
        root_index = dst_dir / "index.html"
        
        if not root_index.exists():
            # Try to find an index.html
            for index_file in dst_dir.rglob('index.html'):
                # Copy the first one found
                import shutil
                shutil.copy2(index_file, root_index)
                break


class ContentCleaner:
    """Clean HTML content for AI training."""
    
    def clean(self, html: str or bytes) -> str:
        """Clean HTML content."""
        try:
            if isinstance(html, bytes):
                soup = BeautifulSoup(html, 'lxml')
            else:
                soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return ""
        
        # Remove script and style elements
        for element in soup.find_all(['script', 'style']):
            element.decompose()
        
        # Remove navigation
        for element in soup.find_all(['nav', 'header', 'footer']):
            element.decompose()
        
        # Remove sidebar
        for element in soup.find_all(['aside']):
            element.decompose()
        
        # Remove ads (common ad container classes/ids)
        ad_selectors = [
            '.ad', '.ads', '.advertisement',
            '#ad', '#ads', '#advertisement',
            '[class*="advertisement"]', '[id*="advertisement"]',
            '[class*="sponsored"]', '[class*="promoted"]'
        ]
        
        for selector in ad_selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                pass
        
        # Get clean text
        text = soup.get_text(separator='\n', strip=True)
        
        # Remove extra whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        
        return text
    
    def extract_structure(self, html: str or bytes) -> Dict:
        """Extract structural elements from HTML."""
        try:
            if isinstance(html, bytes):
                soup = BeautifulSoup(html, 'lxml')
            else:
                soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return {}
        
        structure = {
            "title": "",
            "headings": {},
            "paragraphs": [],
            "lists": [],
            "tables": []
        }
        
        # Title
        title_tag = soup.find('title')
        if title_tag:
            structure["title"] = title_tag.get_text(strip=True)
        
        # Headings
        for level in range(1, 7):
            headings = soup.find_all(f'h{level}')
            structure["headings"][f'h{level}'] = [
                h.get_text(strip=True) for h in headings
            ]
        
        # Paragraphs
        paragraphs = soup.find_all('p')
        structure["paragraphs"] = [
            p.get_text(strip=True) for p in paragraphs 
            if len(p.get_text(strip=True)) > 20
        ]
        
        # Lists
        for list_tag in soup.find_all(['ul', 'ol']):
            items = [li.get_text(strip=True) for li in list_tag.find_all('li')]
            if items:
                structure["lists"].append(items)
        
        # Tables
        for table in soup.find_all('table'):
            rows = []
            for tr in table.find_all('tr'):
                cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if cells:
                    rows.append(cells)
            if rows:
                structure["tables"].append(rows)
        
        return structure


class RouteMapBuilder:
    """Build route map for crawled site."""
    
    def build(self, urls: List[str], domain: str) -> Dict:
        """Build route map from URLs."""
        route_map = {
            "domain": domain,
            "total_urls": len(urls),
            "routes": {},
            "sections": {}
        }
        
        for url in urls:
            parsed = urlparse(url)
            path = parsed.path
            
            # Build route hierarchy
            parts = [p for p in path.split('/') if p]
            
            current = route_map["routes"]
            for i, part in enumerate(parts):
                if part not in current:
                    current[part] = {"_urls": [], "_children": {}}
                
                if i == len(parts) - 1:
                    current[part]["_urls"].append(url)
                
                current = current[part]["_children"]
            
            # Categorize by section
            if parts:
                section = parts[0]
                if section not in route_map["sections"]:
                    route_map["sections"][section] = []
                route_map["sections"][section].append(url)
        
        return route_map
    
    def generate_breadcrumbs(self, url: str, domain: str) -> List[Dict]:
        """Generate breadcrumbs for URL."""
        parsed = urlparse(url)
        path = parsed.path
        
        breadcrumbs = [{"name": "Home", "url": f"https://{domain}/"}]
        
        parts = [p for p in path.split('/') if p]
        current_path = ""
        
        for part in parts:
            current_path += f"/{part}"
            breadcrumbs.append({
                "name": part.replace('-', ' ').replace('_', ' ').title(),
                "url": f"https://{domain}{current_path}"
            })
        
        return breadcrumbs
