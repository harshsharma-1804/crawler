"""HTML downloader with HTTP and Playwright support."""
from dataclasses import dataclass
from typing import Optional
import time
import warnings

import httpx
from playwright.async_api import Page, Browser
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Suppress XML parsing warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


@dataclass
class DownloadResult:
    """Download result container."""
    url: str
    success: bool
    content: bytes = b""
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    error_message: str = ""
    final_url: str = ""
    headers: dict = None


class HTMLDownloader:
    """High-performance HTML downloader."""
    
    def __init__(self, 
                 http_client: httpx.AsyncClient,
                 browser: Browser,
                 timeout: int = 30,
                 use_playwright_for_js: bool = True):
        self.http_client = http_client
        self.browser = browser
        self.timeout = timeout
        self.use_playwright_for_js = use_playwright_for_js
        self._page_pool = []
        self._max_pool_size = 5
    
    async def download(self, url: str, force_js: bool = False) -> DownloadResult:
        """Download HTML from URL."""
        # Try HTTP first for speed
        if not force_js:
            result = await self._download_http(url)
            if result.success and not self._needs_js_rendering(result.content):
                return result
        
        # Fall back to Playwright for JS-heavy pages
        if self.use_playwright_for_js:
            return await self._download_playwright(url)
        
        return result if 'result' in locals() else DownloadResult(
            url=url, 
            success=False,
            error_message="HTTP download failed and JS rendering disabled"
        )
    
    async def _download_http(self, url: str) -> DownloadResult:
        """Download using HTTP client."""
        try:
            response = await self.http_client.get(
                url, 
                timeout=self.timeout,
                follow_redirects=True
            )
            
            content = await response.aread()
            
            # Extract title
            title = self._extract_title(content)
            
            return DownloadResult(
                url=url,
                success=response.status_code < 400,
                content=content,
                status_code=response.status_code,
                content_type=response.headers.get('content-type', ''),
                title=title,
                final_url=str(response.url),
                headers=dict(response.headers)
            )
            
        except httpx.TimeoutException:
            return DownloadResult(
                url=url,
                success=False,
                error_message=f"Timeout after {self.timeout}s"
            )
        except Exception as e:
            return DownloadResult(
                url=url,
                success=False,
                error_message=str(e)
            )
    
    async def _download_playwright(self, url: str) -> DownloadResult:
        """Download using Playwright for JS rendering."""
        page = None
        try:
            page = await self._get_page()
            
            # Navigate with timeout
            await page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            
            # Wait for content to stabilize
            await page.wait_for_load_state("domcontentloaded")
            
            # Get content
            content = await page.content()
            title = await page.title()
            
            return DownloadResult(
                url=url,
                success=True,
                content=content.encode('utf-8'),
                status_code=200,
                content_type="text/html",
                title=title,
                final_url=page.url
            )
            
        except Exception as e:
            return DownloadResult(
                url=url,
                success=False,
                error_message=f"Playwright error: {str(e)}"
            )
        finally:
            if page:
                await self._return_page(page)
    
    def _needs_js_rendering(self, content: bytes) -> bool:
        """Check if content might need JS rendering."""
        content_str = content.decode('utf-8', errors='ignore').lower()
        
        # Check for common JS frameworks or indicators
        js_indicators = [
            'react', 'vue', 'angular', 'next.js', 'nuxt',
            'data-reactroot', 'ng-app', 'v-app',
            'window.__INITIAL_STATE__', 'window.__DATA__',
            '<div id="root">', '<div id="app">',
            'client-side rendering', 'csr'
        ]
        
        for indicator in js_indicators:
            if indicator in content_str:
                return True
        
        # Check if content is very minimal (might be waiting for JS)
        soup = BeautifulSoup(content, 'lxml')
        body_text = soup.get_text(strip=True)
        if len(body_text) < 100:
            return True
        
        return False
    
    def _extract_title(self, content: bytes) -> str:
        """Extract title from HTML."""
        try:
            soup = BeautifulSoup(content, 'lxml')
            title_tag = soup.find('title')
            return title_tag.get_text(strip=True) if title_tag else ""
        except Exception:
            return ""
    
    async def _get_page(self) -> Page:
        """Get page from pool or create new."""
        if self._page_pool:
            return self._page_pool.pop()
        return await self.browser.new_page()
    
    async def _return_page(self, page: Page):
        """Return page to pool or close it."""
        if len(self._page_pool) < self._max_pool_size:
            # Clear page state
            await page.goto("about:blank")
            self._page_pool.append(page)
        else:
            await page.close()
    
    async def close(self):
        """Close all pooled pages."""
        for page in self._page_pool:
            await page.close()
        self._page_pool.clear()
