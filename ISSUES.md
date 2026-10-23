# Crawler Platform — Known Issues

> Audit date: 2026-07-08

---

## Issue 1 — 7 of 16 `.env` Variables Are Dead Config

**File:** `config/.env`, `src/core/settings.py`  
**Severity:** Low (misleading config, no runtime impact)

These variables are loaded into `Settings` but no code ever reads them:

| Variable | Why It's Ignored |
|---|---|
| `MAX_FILE_SIZE_MB` | `AssetDownloader` hardcodes `100 * 1024 * 1024` (`asset_downloader.py:28`) |
| `MAX_CONCURRENT_REQUESTS` | App-level global cap that is never enforced anywhere |
| `MAX_DEPTH` | Per-job `config.max_depth` is used instead |
| `REQUEST_TIMEOUT` | Per-job `config.request_timeout` is used instead |
| `RETRY_ATTEMPTS` | Per-job `config.retry_attempts` is used instead |
| `ENABLE_CACHING` | No caching layer exists in the codebase |
| `CACHE_TTL_SECONDS` | No caching layer exists in the codebase |

**Fix:** Either wire these as global defaults/caps for per-job config, or remove them from `.env` and `Settings` to avoid confusion.

---

## Issue 2 — `VERIFICATION_TOKEN_SECRET` Missing from `.env`

**File:** `config/.env`, `src/security/domain_verifier.py:170,187`  
**Severity:** High (security risk)

`VERIFICATION_TOKEN_SECRET` is used in production code to sign and validate domain ownership tokens. It exists only in `config/.env.sample` but not in the live `config/.env`. The app runs with the insecure hardcoded default `"change-me-in-production"`.

**Fix:** Add `VERIFICATION_TOKEN_SECRET=<strong-random-secret>` to `config/.env`.

---

## Issue 3 — `concurrent_requests` Has No Effect

**File:** `src/crawler/downloaders/sync_html_downloader.py`, `src/ui/routers/job_routes.py:19`  
**Severity:** Medium (UI setting silently ignored)

The UI uses `SyncHTMLDownloader`, which is a single-threaded synchronous BFS loop (`sync_html_downloader.py:453`). It opens one Playwright page, waits for it to load, closes it, then moves to the next URL. There is no parallelism — no semaphore, no thread pool, no worker queue.

`config.concurrent_requests` is accepted from the UI form, passed through `UISettings` → `CrawlJobConfig` → `SyncHTMLDownloader.crawl(config)`, but **never read inside the downloader**. Setting it to 1 or 100 makes no difference.

The field only has effect in the legacy async `CrawlerEngine` (`crawler_engine.py:87`), which the UI does not use.

**Fix:** Rewrite `SyncHTMLDownloader` to run multiple Playwright browser contexts in parallel threads, or switch to async Playwright. This is a larger change.

---

## Issue 4 — `rate_limit_per_domain` Has No Effect

**File:** `src/crawler/downloaders/sync_html_downloader.py`, `src/crawler/engine/url_filter.py:132`  
**Severity:** High (hammers target domains at full speed)

The `DomainRateLimiter` class (`url_filter.py:132`) is async-only and is only wired into the legacy async engine (`crawler_engine.py:82`, `workers.py:24,155`). `SyncHTMLDownloader` has no rate limiting at all — the BFS loop fires `page.goto()` back-to-back with zero delay between requests.

`config.rate_limit_per_domain` travels from the UI form all the way into `CrawlJobConfig` and is passed to `SyncHTMLDownloader.crawl(config)`, but is **never read inside the downloader**.

**Fix:** Add `time.sleep(1.0 / config.rate_limit_per_domain)` between pages in the BFS loop in `SyncHTMLDownloader`. Simple, low-risk fix.

---

## Issue 5 — UI Startup Bypassed Settings ✅ Fixed

**File:** `src/ui/app.py`, `README.md`  
**Severity:** Medium (config values silently ignored on startup)

The server was started via `uvicorn src.ui.app:app --reload --port 8000` (hardcoded in README), which completely bypassed `API_HOST` and `API_PORT` from `.env`. Additionally `src/ui/app.py:40` had `:8000` hardcoded in the startup print.

**Resolution:**
- Added a `__main__` block to `src/ui/app.py` that reads `api_host`/`api_port` from settings and supports CLI overrides (`--host`, `--port`, `--reload`).
- Fixed the hardcoded `:8000` in the startup print.
- Updated README with correct start command: `python -m src.ui.app`.

---

## Issue 6 — `on_event` Deprecation ✅ Fixed

**File:** `src/ui/app.py`  
**Severity:** Low (deprecation warning on every startup)

FastAPI's `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators are deprecated in favour of the `lifespan` context manager pattern.

**Resolution:** Migrated to `@asynccontextmanager` lifespan handler in `src/ui/app.py`.

---

## What Actually Works in the Sync Path

| Setting | Works? |
|---|---|
| `MONGODB_URL` / `MONGODB_DB_NAME` | Yes |
| `DATA_DIR` (and all derived paths) | Yes |
| `MAX_PARALLEL_JOBS` | Yes |
| `API_HOST` / `API_PORT` / `API_WORKERS` | Yes (after Issue 5 fix) |
| `PLAYWRIGHT_HEADLESS` / `PLAYWRIGHT_BROWSER` | Yes |
| `USE_UVLOOP` | Yes |
| `max_depth` | Yes |
| `max_pages` | Yes |
| `save_images` / `save_css` / `save_js` / `save_fonts` / etc. | Yes |
| `concurrent_requests` | No — see Issue 3 |
| `rate_limit_per_domain` | No — see Issue 4 |
