# V3 Crawler — Project Context

> **Last updated:** 2026-04-27
> **Purpose:** Reference document for future updates, feature additions, and context continuity.

---

## 1. Project Overview

A **web crawler and offline site mirroring tool** built with Python. It crawls websites using Playwright (headless browser), downloads HTML pages and assets (CSS, JS, images, fonts, videos, PDFs), builds offline server-ready mirrors, generates analysis reports, and provides both a REST API and a web UI for managing crawl jobs.

**Tech stack:** Python 3.10+, FastAPI, Playwright, Motor (async MongoDB), httpx, Pydantic, Jinja2, BeautifulSoup4.

---

## 2. Directory Structure

```
v3-crawler-windsurf_working/
├── config/.env                          # Environment variables
├── requirements.txt                     # Python dependencies
├── README.md
├── NEXTJS_MIGRATION_PROMPT.md           # Planned UI migration to Next.js
├── CONTEXT.md                           # This file
└── src/
    ├── api/                             # REST API (async pipeline)
    │   ├── main.py                      # FastAPI app entry point
    │   ├── routes_crawl.py              # Crawl job CRUD endpoints
    │   └── routes_reports.py            # Report generation/download endpoints
    │
    ├── core/                            # Core domain logic
    │   ├── settings.py                  # Pydantic BaseSettings (env-based config)
    │   ├── models.py                    # All Pydantic models & enums (278 lines)
    │   ├── crawl_manager.py             # Async crawl orchestrator
    │   └── sync_crawl_manager.py        # Sync crawl orchestrator (UI uses this)
    │
    ├── crawler/                         # Crawling engine components
    │   ├── auth/
    │   │   └── form_login.py            # Pre-crawl form-based authentication
    │   ├── browser/
    │   │   └── setup.py                 # Playwright stealth browser factory
    │   ├── discovery/
    │   │   └── sitemap_parser.py        # Sitemap/robots.txt/orphan URL parsing
    │   ├── downloaders/
    │   │   ├── sync_html_downloader.py  # Sync Playwright BFS crawler (primary)
    │   │   ├── html_downloader.py       # Async HTTP+Playwright hybrid
    │   │   └── asset_downloader.py      # Async streaming asset downloader
    │   ├── engine/
    │   │   ├── crawler_engine.py        # Async engine orchestrator
    │   │   ├── seeder.py                # Queue seeding (sitemap/entry/orphans)
    │   │   ├── workers.py               # Async HTML & asset worker pools
    │   │   ├── url_filter.py            # Domain/pattern URL filtering
    │   │   ├── depth_manager.py         # BFS depth tracking
    │   │   └── queue_manager.py         # Priority queue with dedup
    │   ├── extractors/
    │   │   ├── link_extractor.py        # HTML link extraction (a, canonical, meta refresh, JS nav)
    │   │   └── asset_extractor.py       # CSS/JS/image/font/video URL extraction from HTML & CSS
    │   ├── processors/
    │   │   ├── sync_server_builder.py   # Offline mirror builder (sync, primary)
    │   │   ├── sync_analysis_generator.py # Generates 10 CSV analysis reports
    │   │   └── server_builder.py        # Offline mirror builder (async)
    │   └── utils/
    │       ├── checkers.py              # Domain/pattern checker factories
    │       ├── file_paths.py            # URL-to-filesystem path mapping
    │       └── url_helpers.py           # URL normalization/hashing helpers
    │
    ├── database/
    │   ├── mongo_client.py              # Motor MongoDB singleton client
    │   ├── job_repository.py            # Crawl job CRUD with pagination/filtering
    │   └── content_indexer.py           # URL/asset/HTML content batch indexing
    │
    ├── reporting/
    │   └── report_builder.py            # Report generation & CSV exports
    │
    ├── security/
    │   └── domain_verifier.py           # Domain ownership verification (email/HMAC token)
    │
    ├── storage/
    │   ├── filesystem_storage.py        # Async file I/O
    │   ├── path_builder.py              # URL-to-path conversion
    │   └── csv_writer.py               # Async CSV writing
    │
    ├── ui/                              # Web UI (sync pipeline)
    │   ├── app.py                       # FastAPI app with Jinja2 templates
    │   ├── dependencies.py              # Dependency injection (manager, repo, settings)
    │   ├── sync_endpoints.py            # Legacy sync crawl endpoints, ZIP download, browse
    │   ├── routers/
    │   │   ├── api_routes.py            # API data endpoints for UI
    │   │   ├── view_routes.py           # HTML page rendering routes
    │   │   └── job_routes.py            # Job management form routes
    │   ├── services/
    │   │   ├── asset_server.py          # Serves crawled assets from filesystem
    │   │   └── file_utils.py            # File listing/ZIP archive utilities
    │   ├── static/
    │   │   └── styles.css               # UI stylesheet
    │   └── templates/
    │       ├── layout.html              # Base layout
    │       ├── index.html               # Home / new crawl form
    │       ├── jobs.html                # Job listing page
    │       ├── job_detail.html          # Single job detail view
    │       ├── analysis.html            # Analysis report viewer
    │       └── browse.html              # Crawled files browser
    │
    └── utils/
        ├── url_normalizer.py            # URL normalization & domain extraction
        ├── deduplicator.py              # Set-based & content-hash deduplication
        └── retry_handler.py             # Exponential backoff & circuit breaker
```

**Note:** There are **no `__init__.py` files** anywhere. All imports use full dotted paths (e.g., `from src.core.models import CrawlJob`).

---

## 3. Two Parallel Architectures

The project has two independent pipelines. The **sync pipeline** is the actively maintained and used one.

### 3.1 Sync Pipeline (UI) — PRIMARY

```
src/ui/app.py  →  SyncCrawlManager  →  SyncHTMLDownloader (Playwright, sync)
                                     →  SyncAnalysisGenerator
                                     →  SyncServerBuilder
```

- Entry: `uvicorn src.ui.app:app`
- Uses **sync Playwright** wrapped in `loop.run_in_executor()` to avoid blocking FastAPI
- Simpler BFS crawl, all-in-one downloader
- Three-phase pipeline: HTML crawl → Analysis generation → Server mirror build
- Stop signalling via `threading.Event`
- Pause/resume **not supported**

### 3.2 Async Pipeline (API) — SECONDARY

```
src/api/main.py  →  CrawlManager  →  CrawlerEngine  →  async workers
                                   →  ServerBuilder (async)
                                   →  ReportBuilder
```

- Entry: `uvicorn src.api.main:app`
- Uses `httpx` + async Playwright with full engine (priority queue, rate limiting, depth management)
- Supports pause/resume/stop
- Domain verification required before crawl

---

## 4. Core Models (`src/core/models.py`)

### 4.1 Enums

| Enum | Values |
|------|--------|
| `JobStatus` | `PENDING`, `RUNNING`, `PAUSED`, `STOPPED`, `COMPLETED`, `FAILED` |
| `JobStage` | `INITIALIZING`, `VERIFYING_SITE`, `CRAWLING_MAIN_SITE`, `CRAWLING_ORPHAN_PAGES`, `EXTRACTING_ASSETS`, `DOWNLOADING_ASSETS`, `EXTRACTING_CSS_ASSETS`, `DOWNLOADING_CSS_ASSETS`, `BUILDING_SERVER_STRUCTURE`, `GENERATING_REPORTS`, `COMPLETED` |
| `DiscoveryType` | `ENTRY_POINT`, `HTML_LINK`, `SITEMAP`, `ORPHAN`, `CANONICAL`, `REDIRECT`, `JS_NAVIGATION` |
| `CrawlMode` | `QUEUE_BASED`, `SITEMAP_ONLY`, `QUEUE_AND_SITEMAP`, `URL_LIST` |
| `SaveOptions` | `FULL_MIRROR`, `HTML_CONTENT_ONLY`, `PATTERN_CRAWL` |
| `AssetType` | `CSS`, `JS`, `IMAGE`, `PDF`, `FONT`, `ICON`, `VIDEO`, `OTHER` |

### 4.2 Key Models

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `CrawlJobConfig` | Full crawl configuration | `domain`, `entry_url`, `max_depth`, `max_pages`, `concurrency`, `include_patterns`, `exclude_patterns`, `save_options`, `crawl_mode`, per-asset toggles, `fast_mode`, auth fields, cookies/headers |
| `CrawlJob` | Job instance | `job_id`, `domain`, `status` (JobStatus), `stage` (JobStage), `config`, `pages_crawled`, `assets_downloaded`, timestamps, `error_message` |
| `QueueItem` | Immutable URL queue entry | `url`, `depth`, `source_url`, `discovery_type`, `priority`, `retry_count`, `added_at` |
| `CrawlProgress` | Progress snapshot for UI | `progress_percent`, `pages_crawled`, `assets_downloaded`, `queue_remaining` |
| `URLRecord` | Crawled URL record | `url`, `domain`, `job_id`, `link_type`, `status_code`, `content_type`, `local_path`, timing |
| `AssetRecord` | Asset record (extends URLRecord) | `asset_type`, `parent_urls` |
| `HTMLContent` | Parsed page data | `url`, `title`, `meta_description`, `headings`, `content`, `links`, `images` |
| `CrawlReport` | Job summary report | totals, assets by type, storage, available reports |
| `DomainVerification` | Verification result | `domain`, `verified`, `method`, `message` |
| `Checkpoint` | Pause/resume state | `crawl_queue`, `visited_urls`, `failed_urls`, `discovered_urls`, counters |

---

## 5. Settings (`src/core/settings.py`)

Pydantic `BaseSettings`, loaded from `config/.env`. Singleton via `@lru_cache`.

| Setting | Default | Description |
|---------|---------|-------------|
| `mongodb_url` | `mongodb://localhost:27017` | MongoDB connection string |
| `mongodb_db_name` | `crawler_platform` | Database name |
| `max_concurrent_requests` | `50` | Concurrent request limit |
| `max_depth` | `5` | Default BFS depth limit |
| `request_timeout` | `30` | HTTP timeout (seconds) |
| `retry_attempts` | `3` | Max retries per URL |
| `rate_limit_per_domain` | `10` | Requests/sec per domain |
| `data_dir` | `/Users/mac/.../data` | Root data directory |
| `max_file_size_mb` | `100` | Max file size for downloads |
| `verification_token_secret` | `change-me-in-production` | HMAC secret for domain verification |
| `admin_email_domain` | `localhost` | Admin email domain |
| `api_host` | `0.0.0.0` | API bind host |
| `api_port` | `8000` | API bind port |
| `api_workers` | `1` | Uvicorn workers |
| `playwright_headless` | `True` | Headless browser mode |
| `playwright_browser` | `chromium` | Browser type |
| `use_uvloop` | `True` | Use uvloop event loop |
| `enable_caching` | `True` | Enable response caching |
| `cache_ttl_seconds` | `3600` | Cache TTL |

### Directory Structure (derived properties)

```
{data_dir}/
├── project/
│   ├── htmls/              # Downloaded HTML pages
│   └── assets/
│       ├── css/
│       ├── js/
│       ├── images/
│       ├── pdfs/
│       ├── fonts/
│       ├── icons/
│       └── videos/
├── analyses/               # Generated CSV analysis reports
├── server/                 # Offline mirror output
└── uploads/                # User-uploaded URL lists
```

---

## 6. Data Flow

### 6.1 Crawl Job Lifecycle (Sync Pipeline)

```
User submits config (UI form)
  │
  ▼
CrawlJobConfig validated by Pydantic
  │
  ▼
CrawlJob created in MongoDB (status=PENDING)
  │
  ▼
SyncCrawlManager.create_and_start_job() → asyncio.Task
  │
  ▼
Phase 1: HTML Crawl (SyncHTMLDownloader via run_in_executor)
  ├── Playwright browser launched (stealth mode)
  ├── Optional form authentication
  ├── BFS crawl with link extraction
  ├── Pages saved to data/{domain}/html/
  ├── Progress updated in MongoDB via callbacks
  └── Respects stop_event for cancellation
  │
  ▼
Phase 1.5: Analysis Generation (SyncAnalysisGenerator)
  └── 10 CSV reports written to data/{domain}/analyses/
  │
  ▼
Phase 2: Server Mirror Build (SyncServerBuilder)
  ├── Only for FULL_MIRROR or PATTERN_CRAWL save options
  └── Offline-ready site in data/{domain}/server/
  │
  ▼
Job marked COMPLETED in MongoDB
```

### 6.2 Analysis Reports Generated

| # | File | Contents |
|---|------|----------|
| 1 | `page_inventory.csv` | All crawled pages with status codes |
| 2 | `link_analysis.csv` | Internal/external link mapping |
| 3 | `asset_inventory.csv` | All discovered assets by type |
| 4 | `heading_structure.csv` | Page heading hierarchy (H1-H6) |
| 5 | `meta_analysis.csv` | SEO meta tags (title, description, OG) |
| 6 | `image_analysis.csv` | Image inventory with alt text |
| 7 | `page_performance.csv` | Load time metrics |
| 8 | `content_analysis.csv` | Word count, readability metrics |
| 9 | `navigation_structure.csv` | Site navigation mapping |
| 10 | `error_pages.csv` | Failed/error pages |

---

## 7. Database Layer

- **Engine:** MongoDB via Motor (async driver)
- **Singleton:** `src/database/mongo_client.py` — `MongoDB` class with `get_database()` returning a Motor `AsyncIOMotorDatabase`
- **Collections:**
  - `crawl_jobs` — managed by `JobRepository` (CRUD, pagination, status/domain/month filtering)
  - URL records, asset records, HTML content — managed by `ContentIndexer` (batch insert, query by job_id, delete by job_id)

---

## 8. Key Features

| Feature | Location | Details |
|---------|----------|---------|
| Stealth browsing | `crawler/browser/setup.py` | Anti-detection headers, realistic UA, webdriver flag masking |
| Fast mode | `crawler/browser/setup.py` | Blocks images/fonts/media for faster crawl |
| Form authentication | `crawler/auth/form_login.py` | Pre-crawl login via configurable form selectors |
| Domain verification | `security/domain_verifier.py` | Email-match or HMAC token (file/meta tag) |
| Crawl modes | `core/models.py` | Queue BFS, sitemap-only, combined, URL list |
| Save options | `core/models.py` | Full mirror, HTML-only, pattern-based |
| Per-asset toggles | `core/models.py` | Enable/disable CSS, JS, images, PDFs, fonts, icons, videos |
| URL pattern filtering | `crawler/engine/url_filter.py` | Regex include/exclude patterns |
| Subdomain crawling | `core/models.py` | Configurable scope for subdomains & external sites |
| Pause/resume/stop | `core/crawl_manager.py` | Async pipeline only; sync pipeline supports stop only |
| Retry + backoff | `utils/retry_handler.py` | Exponential backoff with configurable attempts |
| Circuit breaker | `utils/retry_handler.py` | Stops hitting persistently failing domains |
| Rate limiting | `crawler/engine/queue_manager.py` | Per-domain request throttling |
| ZIP download | `ui/sync_endpoints.py` | Stream crawled site as ZIP archive |
| Offline mirror | `crawler/processors/` | URL rewriting for fully offline browsable sites |
| Sitemap parsing | `crawler/discovery/sitemap_parser.py` | XML sitemaps, sitemap indexes, image/video extensions |
| Deduplication | `utils/deduplicator.py` | Set-based URL dedup + content-hash dedup |

---

## 9. Entry Points

| Entry | Command | Pipeline |
|-------|---------|----------|
| Web UI | `uvicorn src.ui.app:app --host 0.0.0.0 --port 8000` | Sync (primary) |
| REST API | `uvicorn src.api.main:app --host 0.0.0.0 --port 8000` | Async (secondary) |

---

## 10. Dependency Map

### Sync Pipeline (UI) — what gets imported when

```
src/ui/app.py
 ├── src/ui/dependencies.py
 │    ├── src/core/sync_crawl_manager.py (SyncCrawlManager)
 │    ├── src/database/job_repository.py (JobRepository)
 │    └── src/core/settings.py (get_settings)
 │
 ├── src/ui/routers/view_routes.py    → job listing, detail, analysis views
 ├── src/ui/routers/job_routes.py     → job creation, start, stop, delete
 ├── src/ui/routers/api_routes.py     → JSON data endpoints
 ├── src/ui/sync_endpoints.py         → legacy sync endpoints, ZIP, browse
 └── src/ui/services/
      ├── asset_server.py             → serves files from data/{domain}/server/
      └── file_utils.py               → file listing, ZIP stream creation

src/core/sync_crawl_manager.py
 ├── src/crawler/downloaders/sync_html_downloader.py
 │    ├── src/crawler/browser/setup.py          (Playwright browser)
 │    ├── src/crawler/auth/form_login.py         (form auth)
 │    ├── src/crawler/extractors/link_extractor.py
 │    └── src/crawler/utils/*                    (checkers, file_paths, url_helpers)
 ├── src/crawler/processors/sync_server_builder.py
 ├── src/crawler/processors/sync_analysis_generator.py
 └── src/database/job_repository.py
      └── src/database/mongo_client.py
```

### Async Pipeline (API)

```
src/api/main.py
 ├── src/api/routes_crawl.py
 ├── src/api/routes_reports.py
 └── src/core/crawl_manager.py (CrawlManager)
      ├── src/crawler/engine/crawler_engine.py
      │    ├── src/crawler/engine/seeder.py
      │    ├── src/crawler/engine/workers.py
      │    │    ├── src/crawler/downloaders/html_downloader.py
      │    │    └── src/crawler/downloaders/asset_downloader.py
      │    ├── src/crawler/engine/url_filter.py
      │    ├── src/crawler/engine/queue_manager.py
      │    └── src/crawler/engine/depth_manager.py
      ├── src/crawler/processors/server_builder.py
      ├── src/reporting/report_builder.py
      ├── src/database/job_repository.py
      ├── src/database/content_indexer.py
      └── src/security/domain_verifier.py
```

---

## 11. Design Notes & Gotchas

1. **No `__init__.py` files** — All imports use full `src.` dotted paths.
2. **No packaging setup** — No `pyproject.toml`, `setup.py`, or `setup.cfg`. Only `requirements.txt`.
3. **Two separate FastAPI apps** — `src/api/main.py` and `src/ui/app.py` are independent applications.
4. **Sync pipeline is primary** — The web UI uses `SyncCrawlManager`; the async API pipeline is secondary.
5. **Filesystem + MongoDB hybrid** — Crawled files stored on disk (`data/{domain}/`), metadata and job state in MongoDB.
6. **Hardcoded `data_dir`** — `settings.py:15` has an absolute path as default; override via `.env`.
7. **Directory properties are global** — `settings.py` directory properties (`html_dir`, `assets_dir`, etc.) point to a single `project/` dir, but actual crawl data is organized per-domain by the downloaders/builders themselves.
8. **No tests** — No test files or test configuration exist in the project.
9. **No CI/CD** — No GitHub Actions, Dockerfile, or docker-compose configuration.
10. **Next.js migration planned** — `NEXTJS_MIGRATION_PROMPT.md` documents a planned migration of the UI layer.

---

## 12. File Inventory (46 Python source files)

| Module | File | Lines | Purpose |
|--------|------|-------|---------|
| `api` | `main.py` | 126 | FastAPI app entry (async) |
| `api` | `routes_crawl.py` | 318 | Crawl job CRUD endpoints |
| `api` | `routes_reports.py` | 212 | Report generation endpoints |
| `core` | `settings.py` | 79 | Application settings |
| `core` | `models.py` | 278 | All Pydantic models & enums |
| `core` | `crawl_manager.py` | 273 | Async crawl orchestrator |
| `core` | `sync_crawl_manager.py` | 305 | Sync crawl orchestrator |
| `crawler/auth` | `form_login.py` | 84 | Form-based authentication |
| `crawler/browser` | `setup.py` | 61 | Playwright browser factory |
| `crawler/discovery` | `sitemap_parser.py` | 280 | Sitemap/robots/orphan parsing |
| `crawler/downloaders` | `sync_html_downloader.py` | 323 | Sync Playwright BFS crawler |
| `crawler/downloaders` | `html_downloader.py` | 189 | Async HTTP+Playwright hybrid |
| `crawler/downloaders` | `asset_downloader.py` | 168 | Async streaming downloader |
| `crawler/engine` | `crawler_engine.py` | 203 | Async engine orchestrator |
| `crawler/engine` | `seeder.py` | 88 | Queue seeding |
| `crawler/engine` | `workers.py` | 220 | Async worker pools |
| `crawler/engine` | `url_filter.py` | 220 | URL filtering |
| `crawler/engine` | `depth_manager.py` | 63 | BFS depth tracking |
| `crawler/engine` | `queue_manager.py` | 212 | Priority queue |
| `crawler/extractors` | `link_extractor.py` | 220 | HTML link extraction |
| `crawler/extractors` | `asset_extractor.py` | 314 | Asset URL extraction |
| `crawler/processors` | `sync_server_builder.py` | 129 | Offline mirror (sync) |
| `crawler/processors` | `sync_analysis_generator.py` | 314 | Analysis CSV generation |
| `crawler/processors` | `server_builder.py` | 423 | Offline mirror (async) |
| `crawler/utils` | `checkers.py` | 63 | Checker factories |
| `crawler/utils` | `file_paths.py` | 78 | Path mapping |
| `crawler/utils` | `url_helpers.py` | 44 | URL helpers |
| `database` | `mongo_client.py` | 46 | MongoDB singleton |
| `database` | `job_repository.py` | 168 | Job CRUD |
| `database` | `content_indexer.py` | 115 | Content indexing |
| `reporting` | `report_builder.py` | 327 | Report generation |
| `security` | `domain_verifier.py` | 194 | Domain verification |
| `storage` | `csv_writer.py` | 102 | CSV writing |
| `storage` | `path_builder.py` | 198 | URL-to-path conversion |
| `storage` | `filesystem_storage.py` | 166 | Async file I/O |
| `ui` | `app.py` | 48 | FastAPI app (sync UI) |
| `ui` | `dependencies.py` | 140 | DI container |
| `ui` | `sync_endpoints.py` | 412 | Legacy sync endpoints |
| `ui/routers` | `api_routes.py` | 128 | UI API endpoints |
| `ui/routers` | `view_routes.py` | 157 | HTML view routes |
| `ui/routers` | `job_routes.py` | 193 | Job form routes |
| `ui/services` | `asset_server.py` | 72 | Asset file serving |
| `ui/services` | `file_utils.py` | 94 | File/ZIP utilities |
| `utils` | `url_normalizer.py` | 149 | URL normalization |
| `utils` | `deduplicator.py` | 102 | Deduplication |
| `utils` | `retry_handler.py` | 112 | Retry + circuit breaker |
