import hashlib
from urllib.parse import urlparse

BLOCKED_EXTENSIONS = (
    ".pdf", ".zip", ".rar", ".tar", ".gz", ".7z",
    ".mp4", ".webm", ".mkv", ".avi", ".mov",
    ".mp3", ".wav", ".ogg",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".css", ".js", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dmg", ".pkg",
)

def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def hash_url(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def get_domain(url: str) -> str:
    """Return bare domain without www. prefix."""
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    domain = parsed.netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


def is_likely_non_html(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(BLOCKED_EXTENSIONS)


def is_process_scheme(url: str) -> bool:
    return url.startswith(("tel:", "mailto:", "ftp:", "javascript:", "data:"))


def is_html_content(html: str) -> bool:
    if not html or len(html) < 100:
        return False
    snippet = html.lower()[:1500]
    return any(tag in snippet for tag in ["<html", "<body", "<head", "<!doctype"])
