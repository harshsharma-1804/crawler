"""URL normalization utilities."""
import re
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode
from typing import Optional


def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
    """Normalize URL to canonical form."""
    if not url:
        return None
    
    url = url.strip()
    
    # Remove common tracking parameters
    tracking_params = [
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'fbclid', 'gclid', 'ref', 'source', 'mc_cid', 'mc_eid'
    ]
    
    # Handle relative URLs
    if base_url and not bool(urlparse(url).netloc):
        url = urljoin(base_url, url)
    
    parsed = urlparse(url)
    
    # Skip non-HTTP schemes
    if parsed.scheme not in ('http', 'https', ''):
        return None
    
    # Default to http if no scheme
    scheme = parsed.scheme or 'https'
    
    # Lowercase netloc
    netloc = parsed.netloc.lower()
    
    # Remove www prefix
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    
    # Remove default port
    if ':80' in netloc and scheme == 'http':
        netloc = netloc.replace(':80', '')
    if ':443' in netloc and scheme == 'https':
        netloc = netloc.replace(':443', '')
    
    # Clean path
    path = parsed.path
    
    # Remove fragment (except for special cases)
    fragment = ''
    
    # Clean query parameters
    query = parsed.query
    if query:
        params = parse_qs(query, keep_blank_values=True)
        # Remove tracking params
        for param in tracking_params:
            params.pop(param, None)
        if params:
            # Sort params for consistency
            query = urlencode(sorted(params.items()), doseq=True)
        else:
            query = ''
    
    # Rebuild URL
    normalized = urlunparse((scheme, netloc, path, '', query, fragment))
    
    return normalized


def get_domain(url: str) -> Optional[str]:
    """Extract domain from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain


def is_same_domain(url: str, domain: str) -> bool:
    """Check if URL belongs to same domain."""
    url_domain = get_domain(url)
    return url_domain == domain.lower()


def is_external_link(url: str, base_domain: str) -> bool:
    """Check if URL is external."""
    url_domain = get_domain(url)
    if not url_domain:
        return False
    return url_domain != base_domain.lower()


def get_url_path(url: str) -> str:
    """Get path component from URL."""
    parsed = urlparse(url)
    return parsed.path


def get_file_extension(url: str) -> str:
    """Get file extension from URL."""
    path = get_url_path(url)
    if '.' in path:
        return path.split('.')[-1].lower()
    return ''


def is_asset_url(url: str) -> bool:
    """Check if URL is likely an asset."""
    asset_extensions = {
        'css', 'js', 'jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'ico',
        'pdf', 'mp4', 'webm', 'mp3', 'woff', 'woff2', 'ttf', 'otf', 'eot'
    }
    ext = get_file_extension(url)
    return ext in asset_extensions


def get_asset_type(url: str) -> str:
    """Determine asset type from URL."""
    ext = get_file_extension(url)
    
    type_map = {
        'css': 'css',
        'js': 'js',
        'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
        'svg': 'image', 'webp': 'image', 'ico': 'icon',
        'pdf': 'pdf',
        'mp4': 'video', 'webm': 'video',
        'mp3': 'audio',
        'woff': 'font', 'woff2': 'font', 'ttf': 'font', 'otf': 'font', 'eot': 'font'
    }
    
    return type_map.get(ext, 'other')


def clean_url_for_filename(url: str) -> str:
    """Clean URL for use as filename."""
    # Remove scheme and www
    cleaned = re.sub(r'^https?://', '', url)
    cleaned = re.sub(r'^www\.', '', cleaned)
    
    # Replace special characters
    cleaned = re.sub(r'[^a-zA-Z0-9._/-]', '_', cleaned)
    
    # Limit length
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    
    return cleaned
