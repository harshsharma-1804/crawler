"""Filesystem storage for crawled content."""
from pathlib import Path
from typing import Optional
import aiofiles
import hashlib

from src.core.settings import get_settings
from src.storage.path_builder import PathBuilder


class FilesystemStorage:
    """Async filesystem storage for crawled content."""
    
    def __init__(self):
        self.settings = get_settings()
        self.path_builder = PathBuilder()
    
    async def save_html(self, job_id: str, domain: str, url: str, 
                        content: bytes or str) -> Optional[Path]:
        """Save HTML content to filesystem."""
        # Build path
        file_path = self.path_builder.build_html_path(domain, url)
        
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        
        return file_path
    
    async def save_asset(self, job_id: str, domain: str, url: str,
                         content: bytes, asset_type: str) -> Optional[Path]:
        """Save asset to filesystem."""
        # Build path
        file_path = self.path_builder.build_asset_path(domain, url, asset_type)
        
        if not file_path:
            return None
        
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        
        return file_path
    
    async def read_html(self, domain: str, url: str) -> Optional[bytes]:
        """Read HTML content from filesystem."""
        file_path = self.path_builder.build_html_path(domain, url)
        
        if not file_path.exists():
            return None
        
        async with aiofiles.open(file_path, 'rb') as f:
            return await f.read()
    
    async def read_asset(self, domain: str, url: str, 
                         asset_type: str) -> Optional[bytes]:
        """Read asset from filesystem."""
        file_path = self.path_builder.build_asset_path(domain, url, asset_type)
        
        if not file_path or not file_path.exists():
            return None
        
        async with aiofiles.open(file_path, 'rb') as f:
            return await f.read()
    
    async def exists(self, domain: str, url: str, 
                     asset_type: str = None) -> bool:
        """Check if file exists."""
        if asset_type:
            file_path = self.path_builder.build_asset_path(domain, url, asset_type)
        else:
            file_path = self.path_builder.build_html_path(domain, url)
        
        return file_path.exists() if file_path else False
    
    async def delete_html(self, domain: str, url: str) -> bool:
        """Delete HTML file."""
        file_path = self.path_builder.build_html_path(domain, url)
        
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    
    async def delete_asset(self, domain: str, url: str, 
                           asset_type: str) -> bool:
        """Delete asset file."""
        file_path = self.path_builder.build_asset_path(domain, url, asset_type)
        
        if file_path and file_path.exists():
            file_path.unlink()
            return True
        return False
    
    def get_html_path(self, domain: str, url: str) -> Path:
        """Get HTML file path without reading."""
        return self.path_builder.build_html_path(domain, url)
    
    def get_asset_path(self, domain: str, url: str, 
                       asset_type: str) -> Optional[Path]:
        """Get asset file path without reading."""
        return self.path_builder.build_asset_path(domain, url, asset_type)
    
    async def get_storage_stats(self, domain: str) -> dict:
        """Get storage statistics for domain."""
        domain_html_dir = self.settings.html_dir / domain
        domain_asset_dir = self.settings.assets_dir
        
        stats = {
            "html_files": 0,
            "html_size_mb": 0.0,
            "assets_by_type": {},
            "total_assets": 0,
            "total_asset_size_mb": 0.0
        }
        
        # Count HTML files
        if domain_html_dir.exists():
            for html_file in domain_html_dir.rglob('*.html'):
                stats["html_files"] += 1
                stats["html_size_mb"] += html_file.stat().st_size / (1024 * 1024)
        
        # Count assets
        for asset_type in ['css', 'js', 'images', 'pdfs', 'fonts', 'icons', 'videos']:
            type_dir = domain_asset_dir / asset_type / domain
            if type_dir.exists():
                type_count = 0
                type_size = 0
                for asset_file in type_dir.rglob('*'):
                    if asset_file.is_file():
                        type_count += 1
                        type_size += asset_file.stat().st_size
                
                if type_count > 0:
                    stats["assets_by_type"][asset_type] = {
                        "count": type_count,
                        "size_mb": round(type_size / (1024 * 1024), 2)
                    }
                    stats["total_assets"] += type_count
                    stats["total_asset_size_mb"] += type_size / (1024 * 1024)
        
        stats["html_size_mb"] = round(stats["html_size_mb"], 2)
        stats["total_asset_size_mb"] = round(stats["total_asset_size_mb"], 2)
        
        return stats
    
    async def compute_checksum(self, file_path: Path) -> str:
        """Compute MD5 checksum of file."""
        if not file_path.exists():
            return ""
        
        hash_md5 = hashlib.md5()
        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(8192):
                hash_md5.update(chunk)
        
        return hash_md5.hexdigest()
