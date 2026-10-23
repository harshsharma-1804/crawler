import sys
from src.core.models import CrawlJobConfig

def _default_user_agent() -> str:
    if sys.platform == "win32":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    elif sys.platform == "linux":
        return (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    else:  # macOS
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

def _sec_ch_ua_platform() -> str:
    if sys.platform == "win32":
        return '"Windows"'
    elif sys.platform == "linux":
        return '"Linux"'
    else:
        return '"macOS"'

DEFAULT_USER_AGENT = _default_user_agent()

def create_stealth_browser_and_context(
    playwright,
    config: CrawlJobConfig,
    fast_mode: bool,
    html_only_mode: bool,
    headless: bool = True,
):
    """Launch the Chrome browser and configure the context with stealth and Fast Mode options.

    Resource-blocking rules (IMPORTANT — do NOT change without updating the
    downloader's load-strategy logic):

      * ``html_only_mode=True``  → block images, media, fonts, stylesheets.
        These resources are not saved anyway, so blocking them is pure speed.
      * ``html_only_mode=True AND fast_mode=True``  → additionally block "other"
        (e.g. tracking pixels, beacons) for maximum speed.
      * ``html_only_mode=False`` (i.e. full_mirror / pattern_crawl) → NEVER
        block anything, because the response interceptor in the downloader
        must capture every asset the browser fetches.

    Parameters
    ----------
    headless : bool
        When False the browser window is visible — used for interactive
        authentication (MFA / CAPTCHA) where the user must interact with
        the browser manually.
    """
    _args = [
        "--disable-gpu",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-infobars",
        "--window-size=1920,1080",
    ]
    # These flags are Linux-specific; applying them on Windows is a no-op at
    # best and a security downgrade at worst.
    if sys.platform != "win32":
        _args += ["--no-sandbox", "--disable-dev-shm-usage"]

    browser = playwright.chromium.launch(
        headless=headless,
        args=_args,
    )
    context = browser.new_context(
        user_agent=config.user_agent or DEFAULT_USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=2,
        locale="en-US",
        timezone_id="America/New_York",
        color_scheme="light",
        extra_http_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": _sec_ch_ua_platform(),
            "Upgrade-Insecure-Requests": "1",
        },
    )

    # ── Resource blocking — HTML-only modes ONLY ─────────────────────
    # Full-mirror modes must NEVER block; the response interceptor needs
    # every network request to capture assets to disk.
    if html_only_mode:
        if fast_mode:
            # Aggressive: block everything except documents and scripts
            _BLOCKED = {"image", "media", "font", "stylesheet", "other"}
        else:
            # Conservative: block heavy resources but keep stylesheets
            # (stylesheets may affect rendered HTML structure)
            _BLOCKED = {"image", "media", "font"}

        def _route_block_heavy(route, request):
            try:
                if request.resource_type in _BLOCKED:
                    return route.abort()
                return route.continue_()
            except Exception:
                try:
                    return route.continue_()
                except Exception:
                    return None

        context.route("**/*", _route_block_heavy)
        blocked_str = ", ".join(sorted(_BLOCKED))
        print(f"[BrowserSetup] HTML-only mode: blocking [{blocked_str}]"
              f"{' (fast)' if fast_mode else ''}")

    return browser, context
