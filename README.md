# V3 Crawler Platform

Next-generation website crawler platform with async architecture, supporting full website mirroring, AI training data extraction, and real-time monitoring.

## Features

- **Job-based crawling** - Every crawl runs as an independent job with full state tracking
- **Full website mirroring** - Generate offline servable copies of websites
- **AI training data extraction** - Clean HTML content extraction for ML training
- **Real-time monitoring** - Live progress tracking via REST API and Web UI
- **Web UI** - Configure and monitor crawls through a web interface
- **Async performance** - 10x faster than pipeline-based crawlers
- **Resumable** - Checkpoint system for crash recovery
- **Modular architecture** - Easily extensible component system
- **Highly configurable** - Extensive options for domains, patterns, assets, timeouts

## Architecture

```
v3-crawler/
src/
    api/                # FastAPI REST API routes
    core/               # Core models, settings, job manager
    crawler/            # Crawler components
        engine/         # Queue manager, depth manager, URL filter
        extractors/     # HTML, link, asset extractors
        downloaders/    # HTTP and Playwright downloaders
        discovery/      # Sitemap, robots.txt parsers
        processors/     # Server builder, content cleaner
    database/           # MongoDB integration
    reporting/          # Report generation
    security/           # Domain verification
    storage/            # Filesystem storage
    ui/                 # Web UI (FastAPI + Jinja2 templates)
        app.py          # UI application
        templates/      # HTML templates
        static/         # CSS styles
    utils/              # URL normalization, deduplication
```

## Quick Start

### Option 1: ### Using the Web UI

1. **Install dependencies**
```bash
pip install -r requirements.txt
playwright install
```

2. **Ensure MongoDB is running**

   The app connects to the URL set in `config/.env` (`MONGODB_URL`, default: `mongodb://localhost:27017`).

3. **Configure (optional)**

   Edit `config/.env` to set your desired host, port, and other options before starting.

4. **Start the UI**
```bash
python -m src.ui.app
```
Or with CLI overrides:
```bash
python -m src.ui.app --host 0.0.0.0 --port 9000 --reload
```

5. **Open in browser**
Navigate to `http://localhost:9000` (or whichever port you configured)

### Option 2: Using the REST API

1. **Install dependencies**
```bash
pip install -r requirements.txt
playwright install
```

2. **Start MongoDB**
```bash
mongod --dbpath /path/to/data
```

3. **Run the API server**
```bash
cd v3-crawler
python -m src.api.main
```

4. **Start a crawl job**
```bash
curl -X POST http://localhost:8000/crawl/start \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "example.com",
    "max_depth": 3,
    "concurrent_requests": 20
  }'
```

## Configuration Options

The crawler supports extensive configuration through the UI or API:

### Basic Settings
- `domain` - Target domain to crawl (required)
- `entry_url` - Starting URL (defaults to https://domain)
- `max_depth` - Maximum crawl depth (0-10, default: 3)
- `max_pages` - Maximum pages to crawl (optional)
- `concurrent_requests` - Parallel requests (1-100, default: 20)
- `rate_limit_per_domain` - Requests per second limit (default: 10)

### Domain Settings
- `allow_subdomains` - Crawl subdomains (default: true)
- `allowed_external_sites` - List of allowed external domains e.g., `["cdn.example.com", "api.example.com"]`

### URL Patterns
- `exclude_patterns` - URL patterns to exclude e.g., `[".pdf", ".zip", "/admin/"]`
- `include_patterns` - URL patterns to include (whitelist)

### Crawl Mode
- `crawl_mode` - Crawling strategy:
  - `queue_and_sitemap` - Use both links from pages and sitemap (default)
  - `queue_based` - Only follow links discovered on pages
  - `sitemap_only` - Only crawl URLs from sitemap

### Save Options
- `save_options` - Output mode:
  - `full_mirror` - Create complete offline website copy (default)
  - `html_content_only` - Extract clean content for AI/ML training

### Asset Download Options (Checkbox-style)
- `save_images` - Download images (default: true)
- `save_videos` - Download videos (default: true)
- `save_pdfs` - Download PDFs (default: true)
- `save_css` - Download stylesheets (default: true)
- `save_js` - Download JavaScript files (default: true)
- `save_icons` - Download favicons (default: true)
- `save_fonts` - Download web fonts (default: true)

### Timeouts (in milliseconds)
- `timeout_for_htmls` - Page load timeout (default: 30000ms = 30s)
- `timeout_for_assets` - Asset download timeout (default: 60000ms = 60s)

### Sitemap & Orphan URLs
- `sitemap_urls` - Custom sitemap URLs to parse
- `orphan_urls` - URLs not linked from main site to include

### Domain Verification (Optional)
- `verify_domain` - Enable ownership verification (default: false)
- `verification_email` - Email for domain verification
- `verification_token` - Token for file/meta verification

## API Endpoints

### Crawl Operations
- `POST /crawl/start` - Start new crawl job
- `GET /crawl/status/{job_id}` - Get crawl progress
- `POST /crawl/pause/{job_id}` - Pause running job
- `POST /crawl/resume/{job_id}` - Resume paused job
- `POST /crawl/stop/{job_id}` - Stop running job
- `GET /crawl/jobs` - List all jobs
- `GET /crawl/job/{job_id}` - Get job details
- `DELETE /crawl/job/{job_id}` - Delete job and data

### Reports
- `GET /reports/{job_id}/summary` - Get crawl summary
- `POST /reports/{job_id}/generate` - Generate CSV reports
- `GET /reports/{job_id}/download/{report_type}` - Download CSV
- `GET /reports/{job_id}/assets` - Asset statistics
- `GET /reports/{job_id}/failures` - Failure analysis
- `GET /reports/{job_id}/storage` - Storage usage

## Web UI Routes

When running `uvicorn src.ui.app:app --port 8000`:

- `/` - Main configuration form to start new crawls
- `/jobs` - List all crawl jobs
- `/job/{job_id}` - View job details, progress, and controls
- `/start` - POST endpoint to submit crawl configuration
- `/api/jobs` - JSON API for job list
- `/api/job/{job_id}/status` - JSON API for job status

## File Storage Structure

```
data/
    project/
        htmls/          # Crawled HTML pages
        assets/         # Downloaded assets
            css/
            js/
            images/
            pdfs/
            fonts/
            icons/
            videos/
    analyses/           # CSV reports
    server/             # Offline mirror
```

## Performance Features

- **Async HTTP** with connection pooling (httpx)
- **Playwright integration** for JavaScript-heavy sites
- **Concurrent workers** for parallel crawling
- **Rate limiting** per domain
- **Smart deduplication** with bloom filter
- **Checkpoint recovery** for crash resilience
- **Domain-specific queues** for multi-domain crawling
- **Configurable timeouts** for HTML pages and assets

## Security

Domain ownership verification via:
- Email domain matching
- Verification token file (`/.crawler-verification.txt`)
- Meta tag verification (`<meta name="crawler-verification" content="TOKEN">`)

## License

MIT
