"""Synchronous analysis generator — ported from the reference crawler's pipeline.

Parses downloaded HTML files to generate comprehensive analysis CSVs.
"""

import csv
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from collections import defaultdict

from src.crawler.downloaders.sync_html_downloader import get_domain

STANDARD_URL_HEADERS = [
    "url",
    "link_type",
    "source_url",
    "redirect_url",
    "http_status",
    "message",
    "file_size",
    "file_type",
    "status"
]

STANDARD_ASSET_HEADERS = [
    "url",
    "asset_type",
    "source_url",
    "redirect_url",
    "http_status",
    "message",
    "file_size",
    "status"
]

VIDEO_EXTENSIONS = (".mp4", ".webm", ".ogg", ".mov", ".m3u8")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico")
FONT_EXTENSIONS = (".woff", ".woff2", ".ttf", ".otf")

REL_TYPE_MAP = {
    "stylesheet": "css",
    "icon": "icon",
    "shortcut icon": "icon",
    "apple-touch-icon": "icon",
    "apple-touch-icon-precomposed": "icon",
}

CSS_URL_REGEX = re.compile(
    r'url\(\s*[\'"]?(.*?)[\'"]?\s*\)',
    re.IGNORECASE
)


class SyncAnalysisGenerator:
    """Generates comprehensive CSV reports from downloaded HTML files."""

    def generate(
        self,
        domain: str,
        html_root: Path,
        analyses_root: Path,
        allowed_external_sites: list[str] = None,
        failed_urls: list = None,
        url_log: list = None,
        asset_log: list = None,
    ) -> Path:
        """Parse local HTML to generate analysis CSV files and return path to the folder."""
        
        domain_folder = domain.replace(".", "_")
        html_dir = html_root / domain_folder
        analysis_dir = analyses_root / domain_folder
        
        if not html_dir.exists():
            print(f"[SyncAnalysisGenerator] ⚠ No HTML directory found at {html_dir}")
            return analysis_dir
            
        analysis_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n[SyncAnalysisGenerator] Generating analysis for domain: {domain}")
        
        # Determine allowed internal domains
        base_domain = get_domain(domain)
        extra_domains = [get_domain(d) for d in (allowed_external_sites or [])]
        
        def is_allowed_internal(url: str) -> bool:
            try:
                d = get_domain(url)
                if d == base_domain or d.endswith("." + base_domain):
                    return True
                for extra in extra_domains:
                    if d == extra or d.endswith("." + extra):
                        return True
                return False
            except Exception:
                return False

        def get_source_url(file_path: Path) -> str:
            try:
                rel = file_path.relative_to(html_dir)
                clean = rel.with_suffix("")
                base = f"https://{domain}"
                if clean.name == "index":
                    return f"{base}/{clean.parent.as_posix()}".rstrip("/")
                return f"{base}/{clean.as_posix()}"
            except Exception:
                return f"https://{domain}"

        # Data stores
        assets_data = []      # for assets_input.csv
        urls_data = []        # for combined_report.csv
        forms_data = []       # for client_actions.csv
        html_routes = []      # for htmls_files.csv
        unique_urls = set()   # for unique_url.csv
        asset_counts = defaultdict(int)
        
        # Deduplication caches
        seen_assets = set()
        seen_urls = set()

        base_site = f"https://{domain}"

        def process_asset(url: str, asset_type: str, source_url: str):
            if not url or url.startswith("data:"): return
            
            parsed = urlparse(url)
            normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            key = (normalized_url, asset_type)
            if key in seen_assets:
                return
            seen_assets.add(key)
            
            # Add to assets report
            assets_data.append([
                normalized_url,
                asset_type,
                source_url,
                "", # redirect_url
                "", # http_status 
                "discovered", # message
                ""  # file_size
            ])
            asset_counts[asset_type] += 1
            
            # Add to combined urls report
            link_type = "internal" if is_allowed_internal(normalized_url) else "external"
            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                urls_data.append([
                    normalized_url,
                    link_type,
                    source_url,
                    "", # redirect_url
                    "", # http_status
                    "discovered",
                    "",
                    asset_type
                ])

        def process_link(url: str, source_url: str):
            if not url or url.startswith(("javascript:", "mailto:", "tel:", "#")): return
            
            parsed = urlparse(url)
            normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                link_type = "internal" if is_allowed_internal(normalized_url) else "external"
                urls_data.append([
                    normalized_url,
                    link_type,
                    source_url,
                    "", "", "discovered", "", "html"
                ])

        # Traverse HTML files
        for root, _, files in os.walk(html_dir):
            for file in files:
                if not file.lower().endswith(".html"):
                    continue
                    
                html_path = Path(root) / file
                try:
                    html_content = html_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                    
                soup = BeautifulSoup(html_content, "html.parser")
                source_url = get_source_url(html_path)
                
                # Internal Tracking
                unique_urls.add(source_url)
                html_routes.append([source_url, str(html_path.relative_to(html_root))])
                asset_counts["htmls"] += 1
                
                # Links found on page
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    full_url = urljoin(base_site, href)
                    
                    if urlparse(href).path.lower().endswith(".pdf"):
                        process_asset(full_url, "pdf", source_url)
                    else:
                        process_link(full_url, source_url)
                
                # IMAGES
                for img in soup.select("img[src]"):
                    process_asset(urljoin(base_site, img["src"]), "image", source_url)
                    
                # JS
                for script in soup.select("script[src]"):
                    process_asset(urljoin(base_site, script["src"]), "js", source_url)
                    
                # VIDEO
                for video in soup.select("video[src]"):
                    process_asset(urljoin(base_site, video["src"]), "video", source_url)
                for src in soup.select("video source[src], source[src]"):
                    href = src.get("src", "")
                    if urlparse(href).path.lower().endswith(VIDEO_EXTENSIONS):
                        process_asset(urljoin(base_site, href), "video", source_url)
                        
                # LINKS (CSS & Icons)
                for link in soup.select("link[href]"):
                    href = link.get("href", "")
                    rel = " ".join(link.get("rel", [])).lower()
                    asset_type = REL_TYPE_MAP.get(rel)
                    if asset_type:
                        process_asset(urljoin(base_site, href), asset_type, source_url)
                        
                # INLINE CSS
                for style in soup.select("style"):
                    content = style.text or ""
                    for raw_url in CSS_URL_REGEX.findall(content):
                        full = urljoin(base_site, raw_url.strip())
                        path = urlparse(full).path.lower()
                        
                        if path.endswith(IMAGE_EXTENSIONS): t = "image"
                        elif path.endswith(FONT_EXTENSIONS): t = "font"
                        elif path.endswith(VIDEO_EXTENSIONS): t = "video"
                        else: t = "asset"
                        
                        process_asset(full, t, source_url)
                        
                # FORMS (Client Actions)
                for form in soup.select("form"):
                    action = form.get("action", "")
                    method = form.get("method", "get").upper()
                    forms_data.append([source_url, method, action])

        # --- WRITE OUTPUT FILES ---
        
        def write_csv(filename, headers, rows):
            with open(analysis_dir / filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)

        # 1. assets_input.csv (All Assets - discovered from HTML parsing)
        write_csv("assets_input.csv", STANDARD_ASSET_HEADERS, assets_data)
        
        # 1b. assets_detailed.csv (All Assets with actual download status from crawl)
        detailed_asset_headers = ["url", "category", "http_status", "redirected_url", "file_size", "status", "message"]
        detailed_asset_rows = []
        if asset_log:
            for entry in asset_log:
                detailed_asset_rows.append([
                    entry.get("url", ""),
                    entry.get("category", ""),
                    entry.get("http_status", ""),
                    entry.get("redirected_url", ""),
                    entry.get("file_size", 0),
                    entry.get("status", ""),
                    entry.get("message", ""),
                ])
        write_csv("assets_detailed.csv", detailed_asset_headers, detailed_asset_rows)
        
        # 2. assets_css_input.csv (CSS Only)
        write_csv("assets_css_input.csv", STANDARD_ASSET_HEADERS, 
                  [r for r in assets_data if r[1] == "css"])
                  
        # 3. assets_js_input.csv (JS Only)
        write_csv("assets_js_input.csv", STANDARD_ASSET_HEADERS, 
                  [r for r in assets_data if r[1] == "js"])
                  
        # 4. client_actions.csv
        write_csv("client_actions.csv", ["source_url", "method", "action_url"], forms_data)
        
        # 5. htmls_files.csv
        write_csv("htmls_files.csv", ["url", "file_path"], html_routes)
        
        # 6. unique_url.csv
        write_csv("unique_url.csv", ["url"], [[u] for u in sorted(unique_urls)])
        
        # 7. total_urls_fetched.csv (Complete manifest of every URL visited with file sizes)
        fetched_headers = ["source_url", "redirected_url", "http_status", "crawl_status", "file_size"]
        fetched_rows = []
        if url_log:
            for entry in url_log:
                fetched_rows.append([
                    entry.get("source_url", ""),
                    entry.get("redirected_url", ""),
                    entry.get("http_status", ""),
                    entry.get("crawl_status", ""),
                    entry.get("file_size", 0),
                ])
        else:
            # Fallback: just list unique HTMLs when no url_log is available
            for u in sorted(unique_urls):
                fetched_rows.append([u, "", "", "saved", 0])
        write_csv("total_urls_fetched.csv", fetched_headers, fetched_rows)
        
        # 8. combined_report.csv (All URLs and Assets with full details)
        combined_rows = []

        # Status priority for deduplication: lower number = higher priority
        # When the same URL appears multiple times (e.g. asset loaded on every page),
        # keep the entry with the best status and discard the rest.
        STATUS_PRIORITY = {"downloaded": 0, "saved": 1, "exists": 2, "failed": 3, "discovered": 4}

        # Add HTML pages from url_log
        if url_log:
            for entry in url_log:
                url = entry.get("source_url", "")
                combined_rows.append([
                    url,                                                                    # url
                    "internal" if is_allowed_internal(url) else "external",                # link_type
                    url,                                                                    # source_url
                    entry.get("redirected_url", ""),                                        # redirect_url
                    entry.get("http_status", ""),                                           # http_status
                    entry.get("crawl_status", "saved"),                                     # message
                    entry.get("file_size", 0),                                              # file_size
                    "html",                                                                 # file_type
                    entry.get("crawl_status", "saved"),                                     # status
                ])

        # Add assets from asset_log
        if asset_log:
            for entry in asset_log:
                url = entry.get("url", "")
                combined_rows.append([
                    url,                                                                    # url
                    "internal" if is_allowed_internal(url) else "external",                # link_type
                    "",                                                                     # source_url
                    entry.get("redirected_url", ""),                                        # redirect_url
                    entry.get("http_status", ""),                                           # http_status
                    entry.get("message", ""),                                               # message
                    entry.get("file_size", 0),                                              # file_size
                    entry.get("category", "unknown"),                                       # file_type
                    entry.get("status", ""),                                                # status
                ])

        # Fallback: use HTML-parsed asset discovery when no asset_log is available
        # assets_data row: [url, asset_type, source_url, redirect_url, http_status, message, file_size]
        if not asset_log:
            for row in assets_data:
                url = row[0]
                combined_rows.append([
                    url,                                                                    # url
                    "internal" if is_allowed_internal(url) else "external",                # link_type
                    row[2],                                                                 # source_url
                    row[3],                                                                 # redirect_url
                    row[4],                                                                 # http_status
                    row[5],                                                                 # message
                    row[6],                                                                 # file_size
                    row[1],                                                                 # file_type (asset_type)
                    "discovered",                                                           # status
                ])

        # Deduplicate: for each URL keep only the entry with the best status.
        # This removes repeated rows caused by the same asset being seen on
        # multiple pages (e.g. shared logo.png → 1 "downloaded" + N "exists").
        deduped: dict = {}
        for row in combined_rows:
            url = row[0]
            if not url:
                continue
            if url not in deduped:
                deduped[url] = row
            else:
                existing_priority = STATUS_PRIORITY.get(deduped[url][8], 99)
                new_priority      = STATUS_PRIORITY.get(row[8], 99)
                if new_priority < existing_priority:
                    deduped[url] = row
        combined_rows = list(deduped.values())

        write_csv("combined_report.csv", STANDARD_URL_HEADERS, combined_rows)
        
        # 9. asset_summary.csv
        summary_rows = [[k, v] for k, v in asset_counts.items()]
        write_csv("asset_summary.csv", ["asset_type", "count"], summary_rows)

        # 10. failed_urls.csv (URLs that failed during crawling)
        failed_rows = []
        for entry in (failed_urls or []):
            failed_rows.append([
                entry.get("url", ""),
                entry.get("http_status", 0),
                entry.get("reason", ""),
            ])
        write_csv("failed_urls.csv", ["url", "http_status", "reason"], failed_rows)

        total_reports = 11
        print(f"[SyncAnalysisGenerator] ✅ Analysis complete. Generated {total_reports} CSV reports.")
        return analysis_dir
