import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

MAX_SEGMENT_LENGTH = 120

def safe_segment(segment: str) -> str:
    segment = unquote(segment)
    segment = "".join(
        c for c in segment if c.isalnum() or c in ("-", "_", ".", " ")
    ).strip()
    if not segment:
        segment = "page"
    if len(segment) > MAX_SEGMENT_LENGTH:
        h = hashlib.sha1(segment.encode()).hexdigest()[:12]
        segment = f"{segment[:60]}_{h}"
    return segment


def get_html_output_path(html_root: Path, domain: str, url: str) -> Path:
    """Build a safe file path for saving an HTML page under html_root/domain/."""
    parsed = urlparse(url)
    domain_folder = domain.replace(".", "_")
    base = html_root / domain_folder

    raw_path = parsed.path.strip("/")
    if not raw_path:
        base.mkdir(parents=True, exist_ok=True)
        return base / "index.html"

    parts = raw_path.split("/")
    safe_parts = [safe_segment(p) for p in parts if p.strip()]
    *folders, last = safe_parts

    folder = base.joinpath(*folders) if folders else base
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{last}.html"


def get_asset_output_path(assets_root: Path, domain: str, url: str, asset_category: str) -> Path:
    """Build a safe file path for saving an asset under assets_root/domain/category/."""
    parsed = urlparse(url)
    domain_folder = domain.replace(".", "_")
    base = assets_root / domain_folder / asset_category

    raw_path = parsed.path.strip("/")
    if not raw_path:
        # Fallback if path is empty (unlikely for assets)
        base.mkdir(parents=True, exist_ok=True)
        return base / "file"

    parts = raw_path.split("/")
    safe_parts = [safe_segment(p) for p in parts if p.strip()]
    *folders, last = safe_parts

    folder = base.joinpath(*folders) if folders else base
    folder.mkdir(parents=True, exist_ok=True)
    return folder / last


def determine_asset_category(url: str, content_type: str) -> Optional[str]:
    """Map a URL and content-type to an asset folder category.

    Returns one of: "css" | "js" | "pdfs" | "icons" | "images" | "fonts" | "media"
    Returns None if the URL/content-type does not match any known asset category.
    """
    p = urlparse(url).path.lower()
    ct = content_type.lower()

    if p.endswith(".css") or "text/css" in ct:
        return "css"
    if p.endswith(".js") or "javascript" in ct:
        return "js"
    # PDFs — checked before the generic image/* catch-all
    if p.endswith(".pdf") or "application/pdf" in ct:
        return "pdfs"
    # Icons — checked before the generic image/* catch-all so .ico gets its own bucket
    if p.endswith((".ico", ".cur")) or "image/x-icon" in ct or "image/vnd.microsoft.icon" in ct:
        return "icons"
    if p.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")) or "image/" in ct:
        return "images"
    if p.endswith((".woff", ".woff2", ".ttf", ".eot", ".otf")) or "font" in ct:
        return "fonts"
    if p.endswith((".mp4", ".webm", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".ogg")) or "video/" in ct or "audio/" in ct:
        return "media"

    return None
