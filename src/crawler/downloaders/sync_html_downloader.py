"""Synchronous HTML downloader using Playwright — ported from the reference crawler.

Key design decisions:
- Uses sync Playwright (playwright.sync_api) to avoid async browser lifecycle bugs.
- Single browser instance per crawl; one page per URL (open → process → close immediately).
- BFS queue with configurable max_depth and max_pages.
- SHA-256 hash-based URL deduplication (normalize first, then hash).
- Disk-first existence check — re-runnable without re-downloading already-saved pages.
- stop_event (threading.Event) allows the async manager to signal early termination.
- on_progress callback: called after each successful page save so MongoDB can be updated.
- Smart load strategy: wait_until varies by save_options + fast_mode for correctness AND speed.
"""

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Set
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from src.core.models import CrawlJobConfig
from src.crawler.utils.url_helpers import (
    normalize_url, hash_url, get_domain, is_likely_non_html,
    is_process_scheme, is_html_content
)
from src.crawler.utils.file_paths import (
    get_html_output_path, get_asset_output_path, determine_asset_category
)
from src.crawler.utils.checkers import (
    build_allowed_checker, build_persist_checker,
    build_exclude_checker, build_include_checker,
    build_pattern_checker,  # kept for any other internal use
)
from src.crawler.auth.form_login import perform_form_authentication
from src.crawler.browser.setup import create_stealth_browser_and_context, DEFAULT_USER_AGENT

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class CrawlStats:
    pages_crawled: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    assets_downloaded: int = 0
    start_time: float = field(default_factory=time.time)
    failed_urls: list = field(default_factory=list)  # [{"url", "reason", "http_status"}]
    url_log: list = field(default_factory=list)       # [{"source_url", "redirected_url", "http_status", "crawl_status", "file_size"}]
    asset_log: list = field(default_factory=list)     # [{"url", "status", "http_status", "redirected_url", "file_size", "category", "message"}]
    seen_asset_urls: set = field(default_factory=set) # dedup set — each asset URL logged at most once across all pages

    # Pause/resume support
    # The crawl thread checks this after each page.  When set, the thread
    # suspends in a tight sleep loop until the event is cleared (resumed)
    # or the stop_event fires.
    pause_event: threading.Event = field(default_factory=threading.Event)

    # Snapshot of queue state taken at the moment of pause so the manager
    # can persist a Checkpoint to MongoDB for true resume-from-state.
    paused_queue: list = field(default_factory=list)       # [(url, depth), ...]
    paused_visited: set = field(default_factory=set)       # visited_hashes at pause time

    # Skip reason counters for observability
    skipped_pattern: int = 0      # Excluded by pattern/filter
    skipped_duplicate: int = 0   # Already visited
    skipped_depth: int = 0       # Beyond max_depth
    skipped_external: int = 0    # Outside allowed domains
    skipped_exists: int = 0      # Already on disk
    total_processed: int = 0     # Total URLs processed (attempted)

    @property
    def elapsed_seconds(self) -> int:
        return int(time.time() - self.start_time)


# ---------------------------------------------------------------------------
# Sitemap seeding helper (sync, no browser required)
# ---------------------------------------------------------------------------

def _seed_from_sitemaps(
    sitemap_urls: list,
    queue: "deque",
    visited_hashes: set,
    config: "CrawlJobConfig",
    max_pages,
    stop_on_first: bool = False,
) -> int:
    """Fetch sitemap URLs synchronously and push discovered page URLs into queue.

    Uses the stdlib ``urllib.request`` so there is no extra dependency and no
    event loop required.  Returns the total number of URLs seeded.

    Parameters
    ----------
    sitemap_urls   : list of sitemap URLs to attempt.
    queue          : the BFS deque to append ``(url, depth=0)`` tuples to.
    visited_hashes : the shared dedup set; URLs already hashed here are skipped.
    config         : CrawlJobConfig — used for domain/subdomain checks.
    max_pages      : if not None, stop seeding once queue reaches this many entries.
    stop_on_first  : if True, stop after the first sitemap that returns 200.
    """
    from urllib.request import urlopen, Request as UrlRequest
    from urllib.error import URLError
    from src.crawler.discovery.sitemap_parser import SitemapParser
    from src.crawler.utils.checkers import build_allowed_checker

    is_allowed = build_allowed_checker(config)
    parser = SitemapParser()
    total_seeded = 0

    for sm_url in sitemap_urls:
        try:
            req = UrlRequest(
                sm_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; crawler/3.0)"},
            )
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    continue
                content = resp.read().decode("utf-8", errors="replace")
        except (URLError, Exception) as exc:
            print(f"[sitemap_seeder] Could not fetch {sm_url}: {exc}")
            continue

        entries = parser.parse(content)
        for entry in entries:
            loc = entry.get("loc", "").strip()
            if not loc:
                continue
            if entry.get("type") == "sitemap":
                # Sitemap index — recurse one level
                child_count = _seed_from_sitemaps(
                    [loc], queue, visited_hashes, config, max_pages
                )
                total_seeded += child_count
                continue

            norm = normalize_url(loc)
            url_hash = hash_url(norm)
            if url_hash in visited_hashes:
                continue
            if not is_allowed(norm):
                continue
            if is_likely_non_html(norm):
                continue

            if max_pages is not None and len(queue) >= max_pages:
                break

            queue.append((norm, 0))
            visited_hashes.add(url_hash)
            total_seeded += 1

        if stop_on_first and total_seeded > 0:
            break

    return total_seeded


# ---------------------------------------------------------------------------
# Main downloader class
# ---------------------------------------------------------------------------

class SyncHTMLDownloader:
    """Synchronous Playwright-based site crawler with smart load strategy."""

    def crawl(
        self,
        config: CrawlJobConfig,
        html_root: Path,
        assets_root: Path,
        stop_event: threading.Event,
        pause_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[int, str, int, int], None]] = None,
        folder_name: Optional[str] = None,
        on_stats_created: Optional[Callable] = None,
        resume_queue: Optional[list] = None,
        resume_visited: Optional[set] = None,
    ) -> CrawlStats:
        """Crawl a website and save HTML/assets.
        
        Args:
            folder_name: Optional override for the folder name (defaults to domain).
                        Used for project-based folder organization.
        """
        stats = CrawlStats()

        # Wire the external pause_event into stats so the manager can read
        # the paused queue/visited snapshot directly from the stats object.
        if pause_event is not None:
            stats.pause_event = pause_event

        # Notify the manager that stats is ready so it can register the live
        # reference for checkpoint snapshotting on pause.
        if on_stats_created is not None:
            try:
                on_stats_created(stats)
            except Exception:
                pass

        is_allowed     = build_allowed_checker(config)
        should_persist = build_persist_checker(config)
        is_excluded    = build_exclude_checker(config)   # (bool, reason)
        check_include  = build_include_checker(config)   # (bool, reason)

        # --- URL List Crawl mode: seed from uploaded list, no BFS ---
        is_url_list_mode = config.crawl_mode == "url_list" and config.upload_urls

        start_url = config.entry_url or f"https://{config.domain}"
        if not start_url.startswith("http"):
            start_url = f"https://{start_url}"

        max_depth = config.max_depth
        max_pages = config.max_pages  # None = unlimited

        visited_hashes: Set[str] = set()
        queue: deque = deque()

        # ── Resume from checkpoint ────────────────────────────────────
        # When resume_queue / resume_visited are provided (server-restart
        # resume path), skip the normal seeding logic entirely and restore
        # the exact BFS state that was saved at pause time.
        if resume_queue is not None and resume_visited is not None:
            for url, depth in resume_queue:
                queue.append((url, depth))
            visited_hashes.update(resume_visited)
            print(
                f"[SyncHTMLDownloader] Resuming from checkpoint — "
                f"queue={len(queue)}, visited={len(visited_hashes)}"
            )
            # Skip all normal seeding below
        elif is_url_list_mode:
            # Seed queue exclusively from the uploaded URL list (all at depth 0)
            for u in config.upload_urls:
                norm = normalize_url(u)
                queue.append((norm, 0))
            print(f"[SyncHTMLDownloader] URL-list mode: {len(config.upload_urls)} URLs loaded")
        else:
            queue.append((normalize_url(start_url), 0))

            # ── Sitemap seeding (sync pipeline) ─────────────────────────────
            # If sitemap_urls are provided in config, fetch and parse each one
            # synchronously using requests (no browser needed) and seed the BFS
            # queue with the discovered URLs at depth=0.
            # This runs in the same thread before the Playwright context opens,
            # so there are no async/event-loop concerns.
            if config.sitemap_urls and config.crawl_mode in (
                "sitemap_only", "queue_and_sitemap"
            ):
                _sitemap_seeded = _seed_from_sitemaps(
                    config.sitemap_urls, queue, visited_hashes,
                    config, max_pages,
                )
                print(
                    f"[SyncHTMLDownloader] Sitemap seeding: "
                    f"{_sitemap_seeded} URLs added from {len(config.sitemap_urls)} sitemap(s)"
                )
            elif config.crawl_mode in ("sitemap_only", "queue_and_sitemap"):
                # Auto-discover sitemap at the domain root
                _auto_sitemaps = [
                    f"https://{config.domain}/sitemap.xml",
                    f"https://{config.domain}/sitemap_index.xml",
                    f"https://www.{config.domain}/sitemap.xml",
                ]
                _sitemap_seeded = _seed_from_sitemaps(
                    _auto_sitemaps, queue, visited_hashes,
                    config, max_pages,
                    stop_on_first=True,   # stop after first successful fetch
                )
                if _sitemap_seeded:
                    print(
                        f"[SyncHTMLDownloader] Auto-discovered sitemap: "
                        f"{_sitemap_seeded} URLs seeded"
                    )

            # sitemap_only mode: clear the manually-added entry point so we
            # only visit what the sitemap declared
            if config.crawl_mode == "sitemap_only":
                # Remove the start_url that was added above — sitemap URLs only
                if queue and queue[0] == (normalize_url(start_url), 0):
                    queue.popleft()
                    print("[SyncHTMLDownloader] sitemap_only mode: entry point removed, using sitemap URLs")

        print(f"[SyncHTMLDownloader] Starting crawl of {start_url}")
        print(f"[SyncHTMLDownloader] max_depth={max_depth}, max_pages={max_pages}")

        # ---------- Mode flags ----------
        fast_mode = bool(getattr(config, "fast_mode", False))
        html_only_mode = config.save_options == "html_content_only"
        needs_assets = config.save_options in ("full_mirror", "pattern_crawl")

        # ---------- Asset toggle map ----------------------------------------
        # Build once from config; passed into the interceptor so each response
        # is gated before any disk write.  The category names here must match
        # exactly what determine_asset_category() returns:
        #   "css" | "js" | "pdfs" | "icons" | "images" | "fonts" | "media"
        _ALLOWED_CATEGORIES: frozenset = frozenset(
            cat for cat, enabled in {
                "css":    config.save_css,
                "js":     config.save_js,
                "pdfs":   config.save_pdfs,
                "icons":  config.save_icons,
                "images": config.save_images,
                "fonts":  config.save_fonts,
                "media":  config.save_videos,
            }.items()
            if enabled
        )
        if needs_assets:
            print(
                f"[SyncHTMLDownloader] Asset toggles — "
                f"css={config.save_css}, js={config.save_js}, "
                f"pdfs={config.save_pdfs}, icons={config.save_icons}, "
                f"images={config.save_images}, fonts={config.save_fonts}, "
                f"media(video)={config.save_videos}"
            )
            print(f"[SyncHTMLDownloader] Saving categories: {sorted(_ALLOWED_CATEGORIES) or 'NONE'}")

        # ---------- Smart load strategy ----------
        # Decide the Playwright wait_until parameter and post-nav settling
        # based on what we actually need from the page.
        #
        #   HTML-only + fast:    domcontentloaded, no settle   → ~100-300ms/page
        #   HTML-only + normal:  domcontentloaded, short settle → ~300-800ms/page
        #   Full mirror + fast:  load, short networkidle        → ~1-2s/page
        #   Full mirror + normal: load, full networkidle        → ~2-5s/page

        if html_only_mode:
            nav_wait_until = "domcontentloaded"
            if fast_mode:
                nav_timeout = min(config.timeout_for_htmls, 5000)
                settle_strategy = "none"
            else:
                nav_timeout = config.timeout_for_htmls
                settle_strategy = "short"  # brief settle for JS-rendered content
        else:
            # Full mirror / pattern_crawl — need subresources to load
            nav_wait_until = "load"
            if fast_mode:
                nav_timeout = min(config.timeout_for_htmls, 10000)
                settle_strategy = "fast_networkidle"
            else:
                nav_timeout = config.timeout_for_htmls
                settle_strategy = "full_networkidle"

        print(f"[SyncHTMLDownloader] fast_mode={fast_mode}, html_only={html_only_mode}")
        print(f"[SyncHTMLDownloader] nav_wait_until={nav_wait_until}, settle={settle_strategy}, timeout={nav_timeout}ms")

        stealth = Stealth(
            navigator_webdriver=True,
            navigator_user_agent=True,
            navigator_user_agent_override=config.user_agent or DEFAULT_USER_AGENT,
            navigator_platform=True,
            navigator_platform_override=(
                "Win32" if sys.platform == "win32"
                else "Linux x86_64" if sys.platform == "linux"
                else "MacIntel"
            ),
            navigator_languages=True,
            navigator_languages_override=("en-US", "en"),
            navigator_vendor=True,
            webgl_vendor=True,
            chrome_runtime=True,
        )

        # ── Auth detection ────────────────────────────────────────────
        needs_auth = bool(config.auth_login_url and config.auth_username and config.auth_password)
        auth_cookies = []
        post_login_url = None

        with stealth.use_sync(sync_playwright()) as playwright:

            # ── Phase A: Headed browser for authentication ───────────
            # If auth is configured, launch a VISIBLE browser so the user
            # can complete MFA / CAPTCHA if triggered.  After auth, extract
            # cookies and close the headed browser entirely.
            if needs_auth:
                print(f"[SyncHTMLDownloader] Auth configured — launching headed browser for login")
                auth_browser, auth_context = create_stealth_browser_and_context(
                    playwright, config, fast_mode, html_only_mode, headless=False,
                )
                try:
                    post_login_url = perform_form_authentication(auth_context, config)
                    # Extract cookies so they can be injected into the headless crawl context
                    auth_cookies = auth_context.cookies()
                    print(f"[SyncHTMLDownloader] Auth complete — captured {len(auth_cookies)} cookies")
                finally:
                    try:
                        auth_context.close()
                    except Exception:
                        pass
                    try:
                        auth_browser.close()
                    except Exception:
                        pass
                print(f"[SyncHTMLDownloader] Headed auth browser closed")

            # ── Phase B: Headless browser for crawling ───────────────
            browser, context = create_stealth_browser_and_context(
                playwright, config, fast_mode, html_only_mode, headless=True,
            )

            # Inject auth cookies into the headless crawl context
            if auth_cookies:
                context.add_cookies(auth_cookies)
                print(f"[SyncHTMLDownloader] Injected {len(auth_cookies)} auth cookies into headless browser")

            # ── Post-login entry URL resolution ──────────────────────
            # If auth was performed, avoid crawling the login page itself.
            # Priority: config.auth_post_login_url > detected post_login_url
            if needs_auth and not is_url_list_mode:
                override_url = getattr(config, "auth_post_login_url", None)
                effective_start = override_url or post_login_url

                if effective_start and effective_start != config.auth_login_url:
                    norm_effective = normalize_url(effective_start)
                    norm_login = normalize_url(config.auth_login_url)

                    # Replace the login URL at the front of the queue
                    if queue and queue[0] == (normalize_url(start_url), 0):
                        queue.popleft()
                    # Only add the new start if it's not the login page
                    if norm_effective != norm_login:
                        queue.appendleft((norm_effective, 0))
                        print(f"[SyncHTMLDownloader] Post-auth entry URL: {norm_effective}")

                    # ── Cross-domain auth handling ────────────────────
                    # If the post-login URL is on a different domain than
                    # config.domain (common with SSO / federated login),
                    # dynamically add the post-login domain to the allowed
                    # and persist scopes so the crawler doesn't reject it.
                    post_login_domain = get_domain(norm_effective)
                    config_domain = get_domain(config.domain)
                    if post_login_domain != config_domain:
                        # Add to allowed_external_sites if not already there
                        if post_login_domain not in {d.lower() for d in config.allowed_external_sites}:
                            config.allowed_external_sites.append(post_login_domain)
                            print(
                                f"[SyncHTMLDownloader] Post-auth domain differs from config.domain: "
                                f"{post_login_domain} != {config_domain}"
                            )
                            print(
                                f"[SyncHTMLDownloader] Auto-added '{post_login_domain}' to allowed_external_sites"
                            )

                            # Rebuild the domain-scope checkers with updated config
                            is_allowed     = build_allowed_checker(config)
                            should_persist = build_persist_checker(config)
                            print(f"[SyncHTMLDownloader] Rebuilt domain-scope checkers with expanded scope")

            try:
                while queue and not stop_event.is_set():

                    # ── Pause check ───────────────────────────────────
                    # When the manager sets pause_event, we suspend here
                    # between pages (never mid-page).  We first save a
                    # snapshot of queue + visited so the manager can
                    # persist a Checkpoint to MongoDB before we sleep.
                    if stats.pause_event.is_set():
                        # Snapshot current state for checkpoint persistence
                        stats.paused_queue   = list(queue)           # [(url, depth), ...]
                        stats.paused_visited = set(visited_hashes)   # copy of hashes
                        print(
                            f"[SyncHTMLDownloader] PAUSED — "
                            f"queue={len(stats.paused_queue)}, "
                            f"visited={len(stats.paused_visited)}, "
                            f"pages={stats.pages_crawled}"
                        )
                        # Block until resumed or stopped
                        while stats.pause_event.is_set() and not stop_event.is_set():
                            time.sleep(0.5)
                        if stop_event.is_set():
                            break
                        print("[SyncHTMLDownloader] RESUMED — continuing crawl")

                    url, depth = queue.popleft()
                    normalized = normalize_url(url)
                    url_hash = hash_url(normalized)

                    stats.total_processed += 1

                # --- Dedup check (early exit) ---
                    if url_hash in visited_hashes:
                        stats.skipped_duplicate += 1
                        print(f"  [SKIPPED][DUPLICATE] {normalized}")
                        if is_url_list_mode:
                            stats.failed_urls.append({"url": url, "reason": "Duplicate URL in uploaded list", "http_status": 0})
                        continue
                    visited_hashes.add(url_hash)

                    if is_process_scheme(url):
                        print(f"  [SKIPPED][SCHEME] {normalized}")
                        if is_url_list_mode:
                            stats.failed_urls.append({"url": url, "reason": f"Non-HTTP scheme ({url.split(':')[0]}:)", "http_status": 0})
                        continue

                    if is_likely_non_html(url):
                        ext = urlparse(url).path.rsplit('.', 1)[-1] if '.' in urlparse(url).path else 'unknown'
                        print(f"  [SKIPPED][NON-HTML] {normalized} (.{ext})")
                        if is_url_list_mode:
                            stats.failed_urls.append({"url": url, "reason": f"Non-HTML file extension (.{ext})", "http_status": 0})
                        continue

                    # Exclude-pattern check on current URL (catches sitemap-seeded URLs too)
                    _excl, _excl_reason = is_excluded(normalized)
                    if _excl:
                        stats.skipped_pattern += 1
                        print(f"  [SKIPPED][PATTERN] {normalized} (excluded: {_excl_reason})")
                        stats.url_log.append({
                            "source_url": normalized, "redirected_url": "",
                            "http_status": 0, "crawl_status": f"skipped:{_excl_reason}",
                        })
                        continue

                    # Include-pattern check is intentionally NOT applied here on dequeue.
                    # Patterns only gate which child links are enqueued (see step 6 below),
                    # so hub/entry-point pages that don't match the pattern can still be
                    # fetched and their links discovered.  Applying the check here would
                    # block the entry-point URL and produce 0 pages crawled.

                    # Check max_pages limit
                    if max_pages is not None and stats.pages_crawled >= max_pages:
                        print(f"[SyncHTMLDownloader] max_pages={max_pages} reached — stopping.")
                        if is_url_list_mode:
                            # Record current + all remaining queued URLs as skipped
                            stats.failed_urls.append({"url": url, "reason": "Max pages limit reached", "http_status": 0})
                            for remaining_url, _ in queue:
                                stats.failed_urls.append({"url": remaining_url, "reason": "Max pages limit reached", "http_status": 0})
                        break

                    page = None
                    page_start = time.perf_counter()
                    try:
                        page = context.new_page()

                        # ── Asset interceptor (full_mirror / pattern_crawl only) ──
                        if needs_assets:
                            self._attach_asset_interceptor(
                                page, stats, assets_root, should_persist,
                                _ALLOWED_CATEGORIES, folder_name,
                            )

                        # ── Phase 1: Navigate ────────────────────────────
                        response = page.goto(
                            url,
                            timeout=nav_timeout,
                            wait_until=nav_wait_until,
                        )

                        # ── Phase 2: Post-navigation settle ──────────────
                        self._settle_page(page, settle_strategy)

                        if not response:
                            stats.pages_failed += 1
                            stats.failed_urls.append({"url": url, "reason": "No response received", "http_status": 0})
                            stats.url_log.append({"source_url": url, "redirected_url": "", "http_status": 0, "crawl_status": "failed"})
                            page.close()
                            continue

                        final_url = normalize_url(page.url)
                        final_domain = get_domain(final_url)

                        if not should_persist(final_domain):
                            stats.skipped_external += 1
                            print(f"  [SKIPPED][EXTERNAL] {final_url} (domain: {final_domain})")
                            if is_url_list_mode:
                                stats.failed_urls.append({"url": url, "reason": f"Redirected to external domain ({final_domain})", "http_status": response.status})
                            stats.url_log.append({"source_url": url, "redirected_url": final_url, "http_status": response.status, "crawl_status": "skipped"})
                            page.close()
                            continue

                        # Use folder_name override if provided (for project-based organization)
                        save_folder = folder_name if folder_name else final_domain
                        html_path = get_html_output_path(html_root, save_folder, final_url)

                        # Disk-first existence check (idempotent re-runs)
                        if html_path.exists():
                            stats.skipped_exists += 1
                            print(f"  [SKIPPED][EXISTS] {final_url}")
                            stats.pages_skipped += 1
                            stats.url_log.append({"source_url": url, "redirected_url": final_url if final_url != url else "", "http_status": response.status, "crawl_status": "skipped"})
                            page.close()
                            continue

                        # ── Capture HTML ─────────────────────────────────
                        html = page.content()

                        # Log progress with counters
                        print(f"  [PROCESSED {stats.total_processed}] crawled={stats.pages_crawled} skipped=[pattern:{stats.skipped_pattern} dup:{stats.skipped_duplicate} depth:{stats.skipped_depth} external:{stats.skipped_external} exists:{stats.skipped_exists}] → {final_url}")

                        # ── Extract links BEFORE closing page (uses live DOM) ──
                        child_links = []
                        if not is_url_list_mode and depth < max_depth:
                            try:
                                child_links = page.eval_on_selector_all(
                                    "a[href]", "els => els.map(e => e.href)"
                                )
                            except Exception as e:
                                print(f"  ⚠ Link extraction error: {e}")

                        # ── Close page (frees browser resources) ─────────
                        page.close()
                        page = None  # prevent double-close in except

                        # ── Save HTML ────────────────────────────────────
                        if is_html_content(html):
                            html_path.write_text(html, encoding="utf-8")
                            stats.pages_crawled += 1
                            # Get file size after writing
                            file_size = html_path.stat().st_size
                            stats.url_log.append({
                                "source_url": url,
                                "redirected_url": final_url if final_url != url else "",
                                "http_status": response.status,
                                "crawl_status": "saved",
                                "file_size": file_size
                            })
                            page_elapsed = time.perf_counter() - page_start
                            print(f"  ✔ [{stats.pages_crawled}] depth={depth} time={page_elapsed:.1f}s size={file_size}b → {final_url}")

                            if on_progress:
                                try:
                                    on_progress(stats.pages_crawled, final_url, len(queue), stats.assets_downloaded)
                                except Exception:
                                    pass

                            # ── Enqueue discovered links ─────────────────
                            for link in child_links:
                                if not link:
                                    continue

                                # 1. Non-crawlable schemes (tel:, mailto:, …)
                                if is_process_scheme(link):
                                    continue

                                # 2. Binary/asset extensions — not HTML pages.
                                # In full_mirror/pattern_crawl mode, directly-linked
                                # assets (e.g. <a href="file.pdf">) are downloaded via
                                # a dedicated fetch instead of being queued for BFS.
                                if is_likely_non_html(link):
                                    if needs_assets:
                                        self._download_linked_asset(
                                            link, stats, assets_root,
                                            should_persist, _ALLOWED_CATEGORIES,
                                            folder_name, config,
                                        )
                                    continue

                                # 3. Domain scope — must be within allowed domains
                                if not is_allowed(link):
                                    continue

                                link_norm = normalize_url(link)
                                link_hash = hash_url(link_norm)

                                # 4. Duplicate — already visited or queued
                                if link_hash in visited_hashes:
                                    stats.skipped_duplicate += 1
                                    print(f"    [SKIPPED][DUPLICATE] {link_norm}")
                                    continue

                                # 5. Exclude pattern — user-defined block list
                                blocked, excl_reason = is_excluded(link_norm)
                                if blocked:
                                    stats.skipped_pattern += 1
                                    print(f"    [SKIPPED][PATTERN] {link_norm} (excluded: {excl_reason})")
                                    stats.url_log.append({
                                        "source_url": link_norm,
                                        "redirected_url": "",
                                        "http_status": 0,
                                        "crawl_status": f"skipped:{excl_reason}",
                                    })
                                    continue

                                # 6. Include pattern — user-defined allow list
                                included, incl_reason = check_include(link_norm)
                                if not included:
                                    stats.skipped_pattern += 1
                                    print(f"    [SKIPPED][PATTERN] {link_norm} (filtered: {incl_reason})")
                                    stats.url_log.append({
                                        "source_url": link_norm,
                                        "redirected_url": "",
                                        "http_status": 0,
                                        "crawl_status": f"skipped:{incl_reason}",
                                    })
                                    continue

                                # 7. Depth limit
                                if depth >= max_depth:
                                    stats.skipped_depth += 1
                                    print(f"    [SKIPPED][DEPTH] {link_norm} (depth:{depth}>={max_depth})")
                                    continue

                                # 8. Persist scope — only save HTML for target domain/subdomains
                                link_domain = get_domain(link)
                                if should_persist(link_domain):
                                    queue.append((link_norm, depth + 1))
                        else:
                            stats.pages_failed += 1
                            status_code = response.status if response else 0
                            stats.failed_urls.append({"url": url, "reason": "Non-HTML content", "http_status": status_code})
                            stats.url_log.append({"source_url": url, "redirected_url": final_url if final_url != url else "", "http_status": status_code, "crawl_status": "failed"})

                    except Exception as e:
                        stats.pages_failed += 1
                        stats.failed_urls.append({"url": url, "reason": str(e), "http_status": 0})
                        stats.url_log.append({"source_url": url, "redirected_url": "", "http_status": 0, "crawl_status": "failed"})
                        print(f"  ✖ FAILED → {url} | {e}")
                        if page:
                            try:
                                page.close()
                            except Exception:
                                pass

            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

        print(
            f"[SyncHTMLDownloader] Done. total_processed={stats.total_processed}, "
            f"crawled={stats.pages_crawled}, skipped={stats.pages_skipped}, failed={stats.pages_failed}, "
            f"assets={stats.assets_downloaded}, elapsed={stats.elapsed_seconds}s"
        )
        print(
            f"[SyncHTMLDownloader] Skip breakdown: "
            f"pattern={stats.skipped_pattern}, duplicate={stats.skipped_duplicate}, "
            f"depth={stats.skipped_depth}, external={stats.skipped_external}, exists={stats.skipped_exists}"
        )
        return stats

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _download_linked_asset(
        url: str,
        stats: CrawlStats,
        assets_root: Path,
        should_persist,
        allowed_categories: frozenset,
        folder_name: str,
        config,
    ) -> None:
        """Download a directly-linked asset (e.g. PDF via <a href>) using httpx.

        This handles asset URLs that the Playwright network interceptor never
        sees because the browser does not load them as sub-resources (they are
        only referenced in <a href> anchors, not fetched during page load).
        """
        import httpx

        category = determine_asset_category(url, "")
        if not category:
            return
        if category not in allowed_categories:
            return

        # Skip if this URL was already logged (e.g. PDF linked from multiple pages)
        if url in stats.seen_asset_urls:
            return
        stats.seen_asset_urls.add(url)

        try:
            req_domain = get_domain(url)
            if not should_persist(req_domain):
                return

            asset_folder = folder_name if folder_name else req_domain
            out_path = get_asset_output_path(assets_root, asset_folder, url, category)

            if out_path.exists():
                stats.asset_log.append({
                    "url": url, "status": "exists", "http_status": 0,
                    "redirected_url": "", "file_size": out_path.stat().st_size,
                    "category": category, "message": "File already on disk",
                })
                return

            timeout = getattr(config, "timeout_for_assets", 60000) / 1000
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                response = client.get(url)

            if response.status_code >= 400:
                stats.asset_log.append({
                    "url": url, "status": "failed",
                    "http_status": response.status_code,
                    "redirected_url": "", "file_size": 0,
                    "category": category,
                    "message": f"HTTP {response.status_code} error",
                })
                return

            out_path.write_bytes(response.content)
            stats.assets_downloaded += 1
            stats.asset_log.append({
                "url": url, "status": "downloaded",
                "http_status": response.status_code,
                "redirected_url": str(response.url) if str(response.url) != url else "",
                "file_size": len(response.content),
                "category": category, "message": "Downloaded via direct fetch",
            })
            print(f"    [ASSET][{category.upper()}] {url} ({len(response.content)} bytes)")

        except Exception as e:
            stats.asset_log.append({
                "url": url, "status": "failed", "http_status": 0,
                "redirected_url": "", "file_size": 0,
                "category": category, "message": f"Fetch error: {str(e)[:80]}",
            })

    @staticmethod
    def _attach_asset_interceptor(
        page,
        stats: CrawlStats,
        assets_root: Path,
        should_persist,
        allowed_categories: frozenset,
        folder_name: str = None,
    ):
        """Attach a response handler that saves intercepted assets to disk.

        This runs during page load: every sub-resource response (CSS, JS,
        images, fonts, etc.) is captured and written immediately.

        ``allowed_categories`` is a frozenset of category strings built from
        the per-asset-type toggles in ``CrawlJobConfig`` (save_css, save_js,
        save_images, save_fonts, save_videos).  Only categories in that set
        are written to disk — everything else is silently skipped.
        """

        def handle_response(response):
            req_url = response.url
            if req_url.startswith("data:"):
                return

            category = determine_asset_category(
                req_url, response.headers.get("content-type", "")
            )
            if not category:
                return

            # ── Asset toggle enforcement ──────────────────────────────
            if category not in allowed_categories:
                return  # user unchecked this asset type — skip silently

            try:
                req_domain = get_domain(req_url)
                if not should_persist(req_domain):
                    return

                # Use folder_name override if provided (for project-based organization)
                asset_folder = folder_name if folder_name else req_domain
                out_path = get_asset_output_path(assets_root, asset_folder, req_url, category)
                
                # Get redirect info if available
                redirected_url = ""
                if hasattr(response, 'request') and response.request:
                    # Check if redirected by comparing URLs
                    if response.request.url != req_url:
                        redirected_url = req_url
                        req_url = response.request.url
                
                http_status = response.status
                file_size = 0
                status = "skipped"
                message = ""
                
                if http_status >= 400:
                    status = "failed"
                    message = f"HTTP {http_status} error"
                elif out_path.exists():
                    status = "exists"
                    message = "File already on disk"
                    file_size = out_path.stat().st_size
                else:
                    # Download the asset
                    try:
                        body = response.body()
                        out_path.write_bytes(body)
                        file_size = len(body)
                        stats.assets_downloaded += 1
                        status = "downloaded"
                        message = "Downloaded successfully"
                    except Exception as e:
                        status = "failed"
                        message = f"Download error: {str(e)[:50]}"
                
                # Log each asset URL only once — subsequent pages that load the
                # same sub-resource (e.g. shared logo.png) produce "exists" hits
                # which would otherwise flood the log with duplicates.
                if req_url not in stats.seen_asset_urls:
                    stats.seen_asset_urls.add(req_url)
                    stats.asset_log.append({
                        "url": req_url,
                        "status": status,
                        "http_status": http_status,
                        "redirected_url": redirected_url,
                        "file_size": file_size,
                        "category": category,
                        "message": message
                    })
            except Exception as e:
                # Log failed assets (deduplicated)
                if req_url not in stats.seen_asset_urls:
                    stats.seen_asset_urls.add(req_url)
                    stats.asset_log.append({
                        "url": req_url,
                        "status": "failed",
                        "http_status": getattr(response, 'status', 0),
                        "redirected_url": "",
                        "file_size": 0,
                        "category": category or "unknown",
                        "message": f"Error: {str(e)[:50]}"
                    })

        page.on("response", handle_response)

    @staticmethod
    def _settle_page(page, strategy: str) -> None:
        """Wait for the page to settle after navigation.

        Strategies (from fastest to most thorough):
          - "none":              no extra wait (domcontentloaded is enough)
          - "short":             200ms hard wait for minor JS rendering
          - "fast_networkidle":  networkidle with tight 3s timeout
          - "full_networkidle":  networkidle with generous 8s timeout,
                                 fallback to 1s hard wait on timeout
        """
        if strategy == "none":
            return

        if strategy == "short":
            try:
                page.wait_for_timeout(200)
            except Exception:
                pass
            return

        if strategy == "fast_networkidle":
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass  # timeout is acceptable — most assets already captured by "load"
            return

        if strategy == "full_networkidle":
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                # Fallback: brief wait to let in-flight responses finish
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    pass
            return
