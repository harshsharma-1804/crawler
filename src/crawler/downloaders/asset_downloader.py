"""Asset downloader for static files."""
from dataclasses import dataclass
from typing import Optional, List
import mimetypes

import httpx


@dataclass
class AssetDownloadResult:
    """Asset download result container."""
    url: str
    success: bool
    content: bytes = b""
    status_code: int = 0
    content_type: str = ""
    file_extension: str = ""
    error_message: str = ""
    final_url: str = ""


class AssetDownloader:
    """High-performance asset downloader."""
    
    def __init__(self, 
                 http_client: httpx.AsyncClient,
                 timeout: int = 60,
                 max_file_size: int = 100 * 1024 * 1024):  # 100MB
        self.http_client = http_client
        self.timeout = timeout
        self.max_file_size = max_file_size
        
        # Asset-specific headers
        self.asset_headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }
    
    async def download(self, url: str) -> AssetDownloadResult:
        """Download asset from URL."""
        try:
            # Get file extension
            ext = self._get_extension(url)
            
            # Make request with streaming for large files
            async with self.http_client.stream(
                "GET",
                url,
                headers=self.asset_headers,
                timeout=self.timeout,
                follow_redirects=True
            ) as response:
                
                if response.status_code >= 400:
                    return AssetDownloadResult(
                        url=url,
                        success=False,
                        status_code=response.status_code,
                        content_type=response.headers.get('content-type', ''),
                        file_extension=ext,
                        error_message=f"HTTP {response.status_code}"
                    )
                
                # Check content length
                content_length = response.headers.get('content-length')
                if content_length:
                    size = int(content_length)
                    if size > self.max_file_size:
                        return AssetDownloadResult(
                            url=url,
                            success=False,
                            status_code=response.status_code,
                            content_type=response.headers.get('content-type', ''),
                            file_extension=ext,
                            error_message=f"File too large: {size} bytes"
                        )
                
                # Download content
                content = await response.aread()
                
                # Verify size
                if len(content) > self.max_file_size:
                    return AssetDownloadResult(
                        url=url,
                        success=False,
                        status_code=response.status_code,
                        content_type=response.headers.get('content-type', ''),
                        file_extension=ext,
                        error_message=f"Downloaded file too large: {len(content)} bytes"
                    )
                
                return AssetDownloadResult(
                    url=url,
                    success=True,
                    content=content,
                    status_code=response.status_code,
                    content_type=response.headers.get('content-type', ''),
                    file_extension=ext,
                    final_url=str(response.url)
                )
                
        except httpx.TimeoutException:
            return AssetDownloadResult(
                url=url,
                success=False,
                file_extension=self._get_extension(url),
                error_message=f"Timeout after {self.timeout}s"
            )
        except Exception as e:
            return AssetDownloadResult(
                url=url,
                success=False,
                file_extension=self._get_extension(url),
                error_message=str(e)
            )
    
    async def download_batch(self, urls: List[str], max_concurrent: int = 10) -> List[AssetDownloadResult]:
        """Download multiple assets concurrently."""
        import asyncio
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def download_with_limit(url: str) -> AssetDownloadResult:
            async with semaphore:
                return await self.download(url)
        
        tasks = [download_with_limit(url) for url in urls]
        return await asyncio.gather(*tasks)
    
    def _get_extension(self, url: str) -> str:
        """Get file extension from URL."""
        from urllib.parse import urlparse
        import os
        
        parsed = urlparse(url)
        path = parsed.path
        
        # Get extension
        ext = os.path.splitext(path)[1].lower()
        if ext.startswith('.'):
            ext = ext[1:]
        
        return ext
    
    def detect_mime_type(self, content: bytes, url: str) -> str:
        """Detect MIME type from content and URL."""
        # Try from URL extension
        mime, _ = mimetypes.guess_type(url)
        if mime:
            return mime
        
        # Try from content magic numbers
        if content.startswith(b'\xff\xd8'):
            return 'image/jpeg'
        elif content.startswith(b'\x89PNG'):
            return 'image/png'
        elif content.startswith(b'GIF89a') or content.startswith(b'GIF87a'):
            return 'image/gif'
        elif content.startswith(b'\x1f\x8b'):
            return 'application/gzip'
        elif content.startswith(b'PK'):
            return 'application/zip'
        elif b'<!DOCTYPE html' in content[:100] or b'<html' in content[:100]:
            return 'text/html'
        elif content.startswith(b'{') or content.startswith(b'['):
            return 'application/json'
        
        return 'application/octet-stream'
