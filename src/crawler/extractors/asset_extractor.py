"""Asset extractor for CSS, JS, and other static files."""
import re
import warnings
from typing import List, Dict
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from urllib.parse import urljoin

# Suppress XML parsing warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class AssetExtractor:
    """Extract asset URLs from HTML content with configurable filtering."""
    
    def __init__(self, 
                 save_images: bool = True,
                 save_videos: bool = True,
                 save_pdfs: bool = True,
                 save_css: bool = True,
                 save_js: bool = True,
                 save_icons: bool = True,
                 save_fonts: bool = True):
        self.save_config = {
            'image': save_images,
            'video': save_videos,
            'pdf': save_pdfs,
            'css': save_css,
            'js': save_js,
            'icon': save_icons,
            'font': save_fonts,
        }
        
        self.asset_patterns = {
            'css': ['.css', 'stylesheet'],
            'js': ['.js', 'javascript'],
            'image': ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico'],
            'font': ['.woff', '.woff2', '.ttf', '.otf', '.eot'],
            'video': ['.mp4', '.webm', '.ogg'],
            'pdf': ['.pdf'],
        }
    
    def should_save_asset(self, asset_type: str) -> bool:
        """Check if asset type should be saved based on configuration."""
        return self.save_config.get(asset_type, True)
    
    def extract(self, html: bytes or str, base_url: str) -> List[Dict]:
        """Extract all asset URLs from HTML."""
        assets = []
        
        try:
            if isinstance(html, bytes):
                soup = BeautifulSoup(html, 'lxml')
            else:
                soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return assets
        
        # CSS files
        if self.should_save_asset('css'):
            for link in soup.find_all('link', rel='stylesheet', href=True):
                assets.append({
                    "url": urljoin(base_url, link['href']),
                    "type": "css",
                    "tag": "link[rel=stylesheet]"
                })
            
            # Inline styles with @import
            for style in soup.find_all('style'):
                if style.string:
                    imports = self._extract_css_imports(style.string, base_url)
                    for imp in imports:
                        assets.append({
                            "url": imp,
                            "type": "css",
                            "tag": "style[@import]"
                        })
        
        # JS files
        if self.should_save_asset('js'):
            for script in soup.find_all('script', src=True):
                assets.append({
                    "url": urljoin(base_url, script['src']),
                    "type": "js",
                    "tag": "script"
                })
        
        # Images
        if self.should_save_asset('image'):
            for img in soup.find_all('img', src=True):
                img_url = urljoin(base_url, img['src'])
                img_type = self._get_image_type(img_url)
                # Check if icons should be saved separately
                if img_type == 'icon' and not self.should_save_asset('icon'):
                    continue
                assets.append({
                    "url": img_url,
                    "type": img_type,
                    "tag": "img"
                })
            
            # Picture sources
            for source in soup.find_all('source', srcset=True):
                srcset = source['srcset']
                urls = self._parse_srcset(srcset)
                for url in urls:
                    assets.append({
                        "url": urljoin(base_url, url),
                        "type": "image",
                        "tag": "source"
                    })
        
        # Videos
        if self.should_save_asset('video'):
            for video in soup.find_all('video', src=True):
                assets.append({
                    "url": urljoin(base_url, video['src']),
                    "type": "video",
                    "tag": "video"
                })
            
            for video in soup.find_all('video'):
                for source in video.find_all('source', src=True):
                    assets.append({
                        "url": urljoin(base_url, source['src']),
                        "type": "video",
                        "tag": "source[video]"
                    })
        
        # Audio (treat as video for saving purposes)
        if self.should_save_asset('video'):
            for audio in soup.find_all('audio', src=True):
                assets.append({
                    "url": urljoin(base_url, audio['src']),
                    "type": "audio",
                    "tag": "audio"
                })
        
        # Favicons
        if self.should_save_asset('icon'):
            for icon in soup.find_all('link', rel=['icon', 'shortcut icon'], href=True):
                assets.append({
                    "url": urljoin(base_url, icon['href']),
                    "type": "icon",
                    "tag": "link[rel=icon]"
                })
        
        # Background images in style attributes
        if self.should_save_asset('image'):
            for tag in soup.find_all(style=True):
                style = tag['style']
                urls = self._extract_urls_from_css(style)
                for url in urls:
                    assets.append({
                        "url": urljoin(base_url, url),
                        "type": "image",
                        "tag": f"{tag.name}[style]"
                    })
        
        # Data attributes with URLs
        if self.should_save_asset('image'):
            for tag in soup.find_all(attrs={'data-src': True}):
                assets.append({
                    "url": urljoin(base_url, tag['data-src']),
                    "type": "image",
                    "tag": f"{tag.name}[data-src]"
                })
        
        # Remove duplicates while preserving order
        seen = set()
        unique_assets = []
        for asset in assets:
            if asset['url'] not in seen:
                seen.add(asset['url'])
                unique_assets.append(asset)
        
        return unique_assets
    
    def _extract_css_imports(self, css_content: str, base_url: str) -> List[str]:
        """Extract @import URLs from CSS content."""
        import re
        
        imports = []
        # Match @import url("...") or @import "..."
        patterns = [
            r'@import\s+url\(["\']?([^"\']+)["\']?\)',
            r'@import\s+["\']([^"\']+)["\']',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, css_content, re.IGNORECASE)
            for match in matches:
                imports.append(urljoin(base_url, match))
        
        return imports
    
    def _parse_srcset(self, srcset: str) -> List[str]:
        """Parse srcset attribute to get URLs."""
        urls = []
        parts = srcset.split(',')
        for part in parts:
            # Format: "url 1x" or "url 100w"
            url = part.strip().split()[0]
            if url:
                urls.append(url)
        return urls
    
    def _extract_urls_from_css(self, css_content: str) -> List[str]:
        """Extract URLs from CSS content."""
        import re
        
        urls = []
        # Match url(...) patterns
        pattern = r'url\(["\']?([^"\']+)["\']?\)'
        matches = re.findall(pattern, css_content)
        
        for match in matches:
            if not match.startswith('data:'):
                urls.append(match)
        
        return urls
    
    def _get_image_type(self, url: str) -> str:
        """Determine image type from URL."""
        url_lower = url.lower()
        if '.jpg' in url_lower or '.jpeg' in url_lower:
            return 'image'
        elif '.png' in url_lower:
            return 'image'
        elif '.gif' in url_lower:
            return 'image'
        elif '.svg' in url_lower:
            return 'image'
        elif '.webp' in url_lower:
            return 'image'
        elif '.ico' in url_lower:
            return 'icon'
        return 'image'


class CSSAssetExtractor:
    """Extract assets referenced in CSS files."""
    
    def __init__(self):
        pass
    
    def extract(self, css_content: str, base_url: str) -> List[Dict]:
        """Extract asset URLs from CSS content."""
        assets = []
        
        # url() references
        url_pattern = r'url\(["\']?([^"\']+)["\']?\)'
        for match in re.findall(url_pattern, css_content):
            if not match.startswith('data:'):
                assets.append({
                    "url": urljoin(base_url, match),
                    "type": self._determine_asset_type(match),
                    "source": "url()"
                })
        
        # @font-face src references
        src_pattern = r'src:\s*([^;]+);'
        for match in re.findall(src_pattern, css_content, re.IGNORECASE):
            # Extract URLs from src
            for url_match in re.findall(url_pattern, match):
                if not url_match.startswith('data:'):
                    assets.append({
                        "url": urljoin(base_url, url_match),
                        "type": "font",
                        "source": "@font-face"
                    })
        
        # background-image
        bg_pattern = r'background-image:\s*url\(["\']?([^"\']+)["\']?\)'
        for match in re.findall(bg_pattern, css_content, re.IGNORECASE):
            if not match.startswith('data:'):
                assets.append({
                    "url": urljoin(base_url, match),
                    "type": "image",
                    "source": "background-image"
                })
        
        # @import rules
        import_pattern = r'@import\s+url\(["\']?([^"\']+)["\']?\)'
        for match in re.findall(import_pattern, css_content, re.IGNORECASE):
            assets.append({
                "url": urljoin(base_url, match),
                "type": "css",
                "source": "@import"
            })
        
        # Remove duplicates
        seen = set()
        unique_assets = []
        for asset in assets:
            if asset['url'] not in seen:
                seen.add(asset['url'])
                unique_assets.append(asset)
        
        return unique_assets
    
    def _determine_asset_type(self, url: str) -> str:
        """Determine asset type from URL."""
        url_lower = url.lower()
        
        if '.woff' in url_lower or '.woff2' in url_lower or '.ttf' in url_lower:
            return 'font'
        elif '.jpg' in url_lower or '.jpeg' in url_lower or '.png' in url_lower or '.gif' in url_lower or '.svg' in url_lower:
            return 'image'
        elif '.css' in url_lower:
            return 'css'
        elif '.js' in url_lower:
            return 'js'
        
        return 'other'
