"""Path builder for converting URLs to filesystem paths."""
from pathlib import Path
from urllib.parse import urlparse
import hashlib

from src.core.settings import get_settings


class PathBuilder:
    """Build filesystem paths from URLs."""
    
    def __init__(self):
        self.settings = get_settings()
    
    def build_html_path(self, domain: str, url: str) -> Path:
        """Build filesystem path for HTML file."""
        parsed = urlparse(url)
        
        # Clean domain
        clean_domain = domain.lower().strip()
        if clean_domain.startswith('www.'):
            clean_domain = clean_domain[4:]
        
        # Build path from URL path
        url_path = parsed.path
        
        # Remove leading slash
        if url_path.startswith('/'):
            url_path = url_path[1:]
        
        # Handle empty path (homepage)
        if not url_path or url_path == '/':
            url_path = 'index'
        
        # Remove trailing slash
        if url_path.endswith('/'):
            url_path = url_path[:-1]
        
        # Build final path
        if '.' in url_path.split('/')[-1]:
            # Has file extension, use as is
            file_path = self.settings.html_dir / clean_domain / url_path
        else:
            # No extension, treat as directory with index.html
            file_path = self.settings.html_dir / clean_domain / url_path / "index.html"
        
        return file_path
    
    def build_asset_path(self, domain: str, url: str, asset_type: str) -> Path:
        """Build filesystem path for asset."""
        parsed = urlparse(url)
        
        # Clean domain
        clean_domain = domain.lower().strip()
        if clean_domain.startswith('www.'):
            clean_domain = clean_domain[4:]
        
        # Map asset type to folder
        type_folders = {
            'css': 'css',
            'js': 'js',
            'image': 'images',
            'icon': 'icons',
            'pdf': 'pdfs',
            'font': 'fonts',
            'video': 'videos',
            'other': 'images',  # Default to images
        }
        
        folder = type_folders.get(asset_type, 'images')
        
        # Build path from URL path
        url_path = parsed.path
        
        # Remove leading slash
        if url_path.startswith('/'):
            url_path = url_path[1:]
        
        # Handle query parameters (some assets have cache-busting query params)
        if parsed.query:
            # Create a short hash of the query
            query_hash = hashlib.md5(parsed.query.encode()).hexdigest()[:8]
            # Append to filename
            if '.' in url_path:
                parts = url_path.rsplit('.', 1)
                url_path = f"{parts[0]}_{query_hash}.{parts[1]}"
            else:
                url_path = f"{url_path}_{query_hash}"
        
        # Build final path
        file_path = self.settings.assets_dir / folder / clean_domain / url_path
        
        return file_path
    
    def build_server_path(self, domain: str, url: str, is_asset: bool = False, 
                          asset_type: str = None) -> Path:
        """Build path for offline server mirror."""
        parsed = urlparse(url)
        
        # Clean domain
        clean_domain = domain.lower().strip()
        if clean_domain.startswith('www.'):
            clean_domain = clean_domain[4:]
        
        if is_asset:
            # Build asset path
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
            
            url_path = parsed.path
            if url_path.startswith('/'):
                url_path = url_path[1:]
            
            file_path = self.settings.server_dir / clean_domain / folder / url_path
        else:
            # Build HTML path
            url_path = parsed.path
            if url_path.startswith('/'):
                url_path = url_path[1:]
            
            if not url_path:
                url_path = 'index'
            
            if url_path.endswith('/'):
                url_path = url_path[:-1]
            
            if '.' in url_path.split('/')[-1]:
                file_path = self.settings.server_dir / clean_domain / url_path
            else:
                file_path = self.settings.server_dir / clean_domain / url_path / "index.html"
        
        return file_path
    
    def get_relative_path(self, from_url: str, to_url: str) -> str:
        """Get relative path from one URL to another."""
        from_parsed = urlparse(from_url)
        to_parsed = urlparse(to_url)
        
        from_path = from_parsed.path
        to_path = to_parsed.path
        
        # Remove filenames to get directories
        from_dir = '/'.join(from_path.split('/')[:-1])
        to_dir = '/'.join(to_path.split('/')[:-1])
        
        # Build relative path
        from_parts = from_dir.split('/')
        to_parts = to_dir.split('/')
        
        # Find common prefix
        common = 0
        for i, (f, t) in enumerate(zip(from_parts, to_parts)):
            if f == t:
                common = i + 1
            else:
                break
        
        # Build relative path
        up_levels = len(from_parts) - common
        rel_path = '../' * up_levels + '/'.join(to_parts[common:])
        
        # Add filename
        to_filename = to_path.split('/')[-1]
        if rel_path:
            rel_path = rel_path + '/' + to_filename
        else:
            rel_path = to_filename
        
        return rel_path
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem."""
        # Replace invalid characters
        invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limit length
        if len(filename) > 200:
            name, ext = self._split_extension(filename)
            filename = name[:200 - len(ext)] + ext
        
        return filename
    
    def _split_extension(self, filename: str) -> tuple:
        """Split filename into name and extension."""
        if '.' in filename:
            last_dot = filename.rfind('.')
            return filename[:last_dot], filename[last_dot:]
        return filename, ''
