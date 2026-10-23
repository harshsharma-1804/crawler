"""URL checker factories used by SyncHTMLDownloader's BFS loop.

Each factory accepts a CrawlJobConfig and returns a plain callable so the
BFS loop can call it without re-importing or re-parsing config each time.

Checkers provided
-----------------
build_allowed_checker   — should this URL be *followed* (domain scope)?
build_persist_checker   — should the downloaded HTML be *saved* to disk?
build_exclude_checker   — is this URL *blocked* by an exclude pattern?
                          Returns (blocked: bool, reason: str).
build_include_checker   — must this URL match an include pattern to be queued?
                          Returns False (with reason) when a URL is gated out.
build_pattern_checker   — legacy alias kept for backward compatibility;
                          equivalent to build_include_checker.
"""

import re
from typing import Set, Tuple
from urllib.parse import urlparse
from src.core.models import CrawlJobConfig
from src.crawler.utils.url_helpers import get_domain


# ---------------------------------------------------------------------------
# Domain-scope checkers (unchanged from original)
# ---------------------------------------------------------------------------

def build_allowed_checker(config: CrawlJobConfig):
    """Return a function that decides whether a URL should be followed."""
    base_domain = get_domain(config.domain)
    extra_domains: Set[str] = {d.lower() for d in config.allowed_external_sites}

    def is_allowed(url: str) -> bool:
        try:
            domain = get_domain(url)
            if domain == base_domain:
                return True
            if config.allow_subdomains and domain.endswith("." + base_domain):
                return True
            if domain in extra_domains:
                return True
            return False
        except Exception:
            return False

    return is_allowed


def build_persist_checker(config: CrawlJobConfig):
    """Return a function that decides whether HTML should be saved for a domain.

    Respects ``allowed_external_sites`` in addition to ``config.domain`` and
    its subdomains.  This is necessary for cross-domain auth flows (SSO) where
    the post-login portal lives on a different domain than the login page.
    """
    base_domain = get_domain(config.domain)
    extra_domains: Set[str] = {d.lower() for d in config.allowed_external_sites}

    def should_persist(domain: str) -> bool:
        if domain == base_domain:
            return True
        if config.allow_subdomains and domain.endswith("." + base_domain):
            return True
        if domain in extra_domains:
            return True
        return False

    return should_persist


# ---------------------------------------------------------------------------
# Exclude-pattern checker  (NEW)
# ---------------------------------------------------------------------------

def build_exclude_checker(config: CrawlJobConfig):
    """Return a callable ``is_excluded(url) -> (blocked: bool, reason: str)``.

    Compiles ``config.exclude_patterns`` as case-insensitive regex fragments
    and applies them to the full URL.  Works in ALL save_options modes.

    Edge cases
    ----------
    - Empty ``exclude_patterns`` list → never blocks (returns False, "").
    - Malformed regex pattern → that pattern is skipped with a warning printed
      once at construction time; remaining patterns still apply.
    - Pattern matched against the *full* URL (scheme + host + path + query),
      so callers can use e.g. ``/admin``, ``\.pdf$``, ``?debug=`` freely.
    """
    compiled = []
    for raw in config.exclude_patterns:
        pat = raw.strip()
        if not pat:
            continue
        try:
            compiled.append((pat, re.compile(pat, re.IGNORECASE)))
        except re.error as exc:
            print(f"[checkers] ⚠ Invalid exclude_pattern '{pat}': {exc} — skipped")

    if compiled:
        patterns_str = ", ".join(p for p, _ in compiled)
        print(f"[checkers] exclude_patterns active: [{patterns_str}]")

    def is_excluded(url: str) -> Tuple[bool, str]:
        for raw_pat, regex in compiled:
            if regex.search(url):
                return True, f"exclude_pattern:{raw_pat}"
        return False, ""

    return is_excluded


# ---------------------------------------------------------------------------
# Include-pattern checker  (extended, replaces build_pattern_checker)
# ---------------------------------------------------------------------------

def build_include_checker(config: CrawlJobConfig):
    """Return a callable ``check_include(url) -> (allowed: bool, reason: str)``.

    Behaviour by mode
    -----------------
    pattern_crawl + include_patterns set
        Strict path-prefix match.  URL path must start with one of the
        patterns.  No patterns → nothing queued (returns False).

    full_mirror / html_content_only + include_patterns set
        Regex match on the full URL.  Only URLs matching at least one pattern
        are queued.  Empty list → all URLs pass (returns True).

    full_mirror / html_content_only + NO include_patterns
        All URLs pass (returns True, "").

    Returns
    -------
    (True, "")                   — URL passes the include gate
    (False, "include_pattern")   — URL blocked by include gate
    """
    save_options = config.save_options
    raw_patterns = [p.strip() for p in config.include_patterns if p.strip()]

    # ── pattern_crawl mode: strict path-prefix matching ─────────────────────
    if save_options == "pattern_crawl":
        if not raw_patterns:
            # No patterns → crawl nothing beyond the entry point
            def _gate_none(url: str) -> Tuple[bool, str]:
                return False, "include_pattern:pattern_crawl_no_patterns"
            return _gate_none

        # Strip leading slash for comparison convenience
        prefixes = [p.lstrip("/") for p in raw_patterns]

        def _gate_prefix(url: str) -> Tuple[bool, str]:
            path = urlparse(url).path.lstrip("/")
            for prefix in prefixes:
                clean = prefix.rstrip("/")
                if path == clean or path.startswith(clean + "/"):
                    return True, ""
            return False, f"include_pattern:prefix_mismatch"

        return _gate_prefix

    # ── full_mirror / html_content_only: regex on full URL ──────────────────
    if not raw_patterns:
        # No restrictions — all URLs pass
        return lambda url: (True, "")

    compiled_includes = []
    for pat in raw_patterns:
        try:
            compiled_includes.append((pat, re.compile(pat, re.IGNORECASE)))
        except re.error as exc:
            print(f"[checkers] ⚠ Invalid include_pattern '{pat}': {exc} — skipped")

    if compiled_includes:
        patterns_str = ", ".join(p for p, _ in compiled_includes)
        print(f"[checkers] include_patterns active ({save_options}): [{patterns_str}]")

    def _gate_regex(url: str) -> Tuple[bool, str]:
        for raw_pat, regex in compiled_includes:
            if regex.search(url):
                return True, ""
        return False, "include_pattern:no_match"

    return _gate_regex


# ---------------------------------------------------------------------------
# Legacy alias — keeps callers that import build_pattern_checker working
# ---------------------------------------------------------------------------

def build_pattern_checker(config: CrawlJobConfig):
    """Backward-compatible alias for build_include_checker.

    Original callers used: ``if matches_pattern(link): queue.append(...)``
    New callers use:       ``allowed, reason = check_include(link)``

    This alias wraps build_include_checker so that old boolean-style callers
    (that only check the first element of the tuple) keep working without
    modification.  New code should call build_include_checker directly.
    """
    inner = build_include_checker(config)

    def matches_pattern(url: str) -> bool:
        allowed, _ = inner(url)
        return allowed

    return matches_pattern
