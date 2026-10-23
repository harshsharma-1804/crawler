# Content Extractor — Requirements & Design Document

> **Created:** 2026-05-29
> **Status:** Draft — awaiting decisions on approach, output format, and integration model
> **Author:** Auto-generated from design session
> **Related:** `CONTEXT.md`, `docs/COMPONENT_ANALYZER_REQUIREMENTS.md`

---

## 1. Executive Summary

**Goal**: Extract clean, structured content from crawled HTML pages and produce output suitable for AI training, search indexing (Elasticsearch), structured data scraping (products, jobs, articles), and general content analysis.

**Why**: The crawler's HTML-only mode already downloads raw HTML pages. But raw HTML is unusable for downstream applications — it's full of navigation, footers, tracking scripts, and boilerplate. The missing step is a content extraction pipeline that strips boilerplate and produces clean, structured data ready for consumption by AI models, search engines, and data pipelines.

**Value**: Turns a web crawler into a complete content acquisition platform. One crawl → multiple outputs (AI training data, search index, structured datasets, content analysis).

---

## 2. Problem Statement

### Raw HTML is not usable content

A typical HTML page contains:
- **~20% actual content** (article text, product info, job listing)
- **~80% boilerplate** (navigation, footer, sidebar, ads, tracking scripts, cookie banners, social share buttons)

Downstream consumers need the 20%, not the 80%.

### Current gap

```
Crawl (existing) → Raw HTML files on disk → ???
                                              ↓
                                    No automated extraction
                                    Manual copy-paste or custom scripts
```

### Proposed solution

```
Crawl (existing) → Raw HTML files → Content Extractor (NEW)
                                              ↓
                              ┌───────────────┼───────────────┐
                              ↓               ↓               ↓
                        Clean text       Structured data   Search-ready
                        (AI training)    (products, jobs)  (Elasticsearch)
```

---

## 3. Use Cases

### 3.1 AI Training Data Preparation

**Goal**: Extract clean text from web pages for LLM fine-tuning, RAG (Retrieval-Augmented Generation), or knowledge base construction.

**Requirements**:
- Remove all HTML tags, scripts, styles, navigation, footer
- Preserve document structure (headings, paragraphs, lists)
- Output as clean text or markdown
- Include metadata (URL, title, date, author) for provenance
- Handle multi-page content (pagination)
- Deduplicate content across pages (boilerplate that leaks through)

**Output**: JSONL file with one record per page:
```json
{"url": "https://example.com/blog/post-1", "title": "...", "content": "...", "metadata": {...}}
```

### 3.2 Search Indexing (Elasticsearch / OpenSearch)

**Goal**: Produce search-ready documents that can be bulk-indexed into Elasticsearch.

**Requirements**:
- Extract title, headings (h1-h6), body text, meta description
- Extract structured metadata (Open Graph, Schema.org, JSON-LD)
- Generate text snippets for search result display
- Compute word count, reading time, language
- Output in Elasticsearch bulk-index format

**Output**: JSONL file compatible with Elasticsearch `_bulk` API:
```json
{"_index": "site_content", "_id": "hash_of_url"}
{"url": "...", "title": "...", "headings": [...], "body": "...", "meta": {...}, "word_count": 450}
```

### 3.3 E-Commerce Product Scraping

**Goal**: Extract product listings from e-commerce sites (name, price, description, images, SKU, availability).

**Requirements**:
- Auto-detect product pages (or user-configured URL patterns)
- Extract structured product fields from HTML or JSON-LD/Schema.org
- Handle price formats, currencies, sale prices
- Extract product images and variant options
- Output as structured JSON/CSV

**Output**:
```json
{
  "url": "https://shop.example.com/widget-a",
  "name": "Widget A",
  "price": {"amount": 29.99, "currency": "USD"},
  "sale_price": {"amount": 19.99, "currency": "USD"},
  "description": "A premium widget...",
  "images": ["https://..."],
  "sku": "WDG-001",
  "availability": "in_stock",
  "category": "Widgets > Premium"
}
```

### 3.4 Job Portal Scraping

**Goal**: Extract job listings from career pages (title, company, location, salary, description, requirements).

**Requirements**:
- Auto-detect job listing pages
- Extract structured job fields
- Handle salary ranges, location formats, remote/hybrid indicators
- Output as structured JSON/CSV

**Output**:
```json
{
  "url": "https://careers.example.com/job/12345",
  "title": "Senior Software Engineer",
  "company": "Example Corp",
  "location": "San Francisco, CA",
  "remote": "hybrid",
  "salary": {"min": 150000, "max": 200000, "currency": "USD", "period": "annual"},
  "description": "We are looking for...",
  "requirements": ["5+ years Python", "Distributed systems"],
  "posted_date": "2026-05-15"
}
```

### 3.5 Article / Blog Content Extraction

**Goal**: Extract article content with metadata for content analysis, archiving, or republishing.

**Requirements**:
- Extract article body with preserved formatting (headings, lists, images)
- Extract author, publish date, categories, tags
- Detect and extract featured image
- Handle multi-page articles
- Output as markdown or structured JSON

### 3.6 General Content Extraction

**Goal**: Extract all meaningful text from any page, regardless of page type.

**Requirements**:
- Works on any site without configuration
- Removes boilerplate (nav, footer, sidebar, ads)
- Preserves content hierarchy
- Falls back gracefully on unusual page layouts

---

## 4. Existing Tools Landscape

### What already exists

| Tool | Type | Boilerplate Removal | Structured Extraction | AI Training | Search Indexing | Offline |
|------|------|--------------------|-----------------------|-------------|-----------------|---------|
| **Trafilatura** | Python library | Excellent — combines jusText + readability heuristics | Metadata only (title, author, date) — no product/job extraction | Yes (primary use case) | Partial | Yes |
| **Mozilla Readability** | JS library (python-readability port) | Good — Firefox Reader View algorithm | No | Partial | No | Yes |
| **Newspaper3k/4k** | Python library | Good — article-focused | Article metadata (author, date, images) | Partial | No | Yes |
| **BeautifulSoup** | Python library | None — manual extraction | Manual — you write the selectors | No | No | Yes |
| **Unstructured.io** | Python library/API | Good — ML-based element classification | Yes — tables, lists, narrative text | Yes | Yes | Partial |
| **LangChain loaders** | Python framework | Uses Unstructured or BS4 under the hood | Depends on loader | Yes (primary use case) | No | Varies |
| **LlamaIndex parsers** | Python framework | Uses Unstructured, BS4, or Trafilatura | Depends on parser | Yes (primary use case) | No | Varies |
| **Diffbot** | Commercial API | Excellent — ML-based | Excellent — products, articles, jobs, events | No | No | No |
| **Schema.org / JSON-LD** | Standard | N/A | Structured data embedded by site owners | No | Yes | Yes |

### What's missing

No single tool combines:
1. Boilerplate removal (Trafilatura-quality)
2. Structured extraction (product, job, article schemas)
3. Search-ready output (Elasticsearch format)
4. AI training output (clean text/markdown with metadata)
5. Integration with a crawling pipeline (runs on already-crawled HTML, not live URLs)

Our content extractor would fill this gap by operating on **already-crawled HTML files** and producing **multiple output formats** from a single extraction pass.

---

## 5. Pipeline Architecture

### Where it fits in the crawl lifecycle

```
Phase 1:   HTML Crawl (SyncHTMLDownloader)            ← existing
Phase 1.5: Analysis Reports (SyncAnalysisGenerator)    ← existing
Phase 1.6: Component Analysis (ComponentAnalyzer)       ← NEW (separate doc)
Phase 1.7: Content Extraction (ContentExtractor)        ← NEW (this doc)
Phase 2:   Server Mirror Build (SyncServerBuilder)      ← existing
```

### Alternative: Standalone tool

The content extractor can also run independently, outside the crawl pipeline:

```bash
# As a crawl phase (automatic)
uvicorn src.ui.app:app  # crawl includes extraction

# As a standalone CLI tool (manual)
python -m src.tools.extract_content --input data/example_com/html/ --output data/example_com/extracted/
```

### Decision needed

Whether to implement as crawl pipeline phase, standalone tool, or both.

### New file location

```
src/crawler/processors/
├── sync_analysis_generator.py       # Existing
├── sync_server_builder.py           # Existing
├── component_analyzer.py            # NEW (component doc)
└── content_extractor.py             # NEW (this doc)

# If standalone tool is also needed:
src/tools/
└── extract_content.py               # CLI entry point
```

---

## 6. Extraction Pipeline

Five-step pipeline:

```
Step A: Parse & Clean    → Strip boilerplate, extract main content
Step B: Detect Page Type → Article, product, job, listing, generic
Step C: Extract Fields   → Type-specific structured field extraction
Step D: Enrich           → Metadata, Schema.org/JSON-LD, Open Graph
Step E: Export           → Output in configured format(s)
```

### Step A: Parse & Clean (Boilerplate Removal)

**Input**: Raw HTML files from `data/{domain}/html/`

**Process**: Two-stage cleaning:

**Stage 1 — Tag-level stripping**:
- Remove `<script>`, `<style>`, `<link>`, `<meta>`, `<noscript>`, HTML comments
- Remove known boilerplate elements: cookie banners, ad containers, tracking pixels
- Remove hidden elements (`display:none`, `visibility:hidden`, `aria-hidden="true"`)

**Stage 2 — Content-region identification**:
- Identify the main content region using (in priority order):
  1. `<main>` tag or `role="main"`
  2. `<article>` tag
  3. Largest text-dense block (highest text-to-tag ratio)
  4. `id="content"`, `class="content"`, `class="main-content"`, etc.
- Strip everything outside the main content region (header, footer, nav, sidebar)
- Preserve content structure (headings, paragraphs, lists, tables, images)

**Approach options**:

| Option | How | Accuracy | Speed | Dependencies |
|--------|-----|----------|-------|-------------|
| **A1: Built-in heuristics** | Tag-ratio scoring + semantic HTML signals | ~70-80% | Very fast | BS4 only |
| **A2: Trafilatura integration** | Use trafilatura library for extraction | ~90% | Fast | `trafilatura` pip package |
| **A3: Readability integration** | Use python-readability for main content | ~85% | Fast | `readability-lxml` pip package |
| **A4: Hybrid** | Try Trafilatura first, fall back to heuristics | ~90%+ | Fast | `trafilatura` |

**Recommendation**: **A4 (Hybrid)** — Trafilatura is battle-tested (used by HuggingFace, Microsoft Research), open source, and handles edge cases well. Fall back to built-in heuristics when Trafilatura fails or for content it doesn't handle (product pages, job listings).

**Output**: Cleaned content per page with preserved structure

### Step B: Detect Page Type

**Input**: Cleaned content + original HTML (for Schema.org/JSON-LD inspection)

**Process**: Classify each page into a content type:

| Page Type | Detection Signals |
|-----------|-------------------|
| **Article / Blog Post** | `<article>` tag, Schema.org `Article`/`BlogPosting`, has author + date + body text, URL matches `/blog/`, `/news/`, `/article/` |
| **Product Page** | Schema.org `Product`, contains price elements, URL matches `/product/`, `/shop/`, `/item/` |
| **Job Listing** | Schema.org `JobPosting`, contains job-specific fields (salary, location, requirements), URL matches `/jobs/`, `/careers/`, `/positions/` |
| **Listing / Index Page** | Contains multiple links to pages of same type, pagination present, class matches `listing`, `grid`, `results` |
| **FAQ Page** | Schema.org `FAQPage`, accordion-style Q&A pairs, URL matches `/faq/`, `/help/` |
| **Contact Page** | Contains address, phone, email, contact form, URL matches `/contact/`, `/about/` |
| **Landing Page** | Hero section + CTA blocks + feature sections, homepage or marketing page |
| **Documentation** | Code blocks, sequential headings, table of contents, URL matches `/docs/`, `/documentation/` |
| **Generic** | Fallback — doesn't match any specific type |

**Approach options**:

| Option | How | Accuracy |
|--------|-----|----------|
| **B1: Schema.org / JSON-LD first** | Check embedded structured data — if present, it's authoritative | ~95% when present (~30% of sites have it) |
| **B2: URL pattern matching** | Regex on URL path (`/product/`, `/blog/`, `/jobs/`) | ~60-70% |
| **B3: Content heuristics** | Analyze DOM structure, field presence, text patterns | ~75% |
| **B4: LLM classification** | Send page summary to LLM: "What type of page is this?" | ~95% |
| **B5: Combined** | B1 → B2 → B3 (fall through), with B4 as optional enhancement | ~85-90% |

**Recommendation**: **B5 (Combined)** — Check Schema.org first (free, authoritative), then URL patterns, then content heuristics. LLM as optional enhancement for ambiguous pages.

**Output**: Each page annotated with `page_type` and `confidence`

### Step C: Extract Fields (Type-Specific)

**Input**: Cleaned content + page type classification

**Process**: Apply type-specific extraction rules:

#### Generic extraction (all page types)

| Field | Source | Method |
|-------|--------|--------|
| `url` | Page URL | From filename/crawl metadata |
| `title` | `<title>`, `<h1>`, `og:title` | Priority: og:title > h1 > title tag |
| `description` | `<meta name="description">`, `og:description`, first paragraph | Priority: meta > og > first-p |
| `headings` | `<h1>` through `<h6>` | Extract all with hierarchy |
| `body_text` | Main content region | Clean text, whitespace normalized |
| `body_markdown` | Main content region | Converted to markdown (preserving structure) |
| `images` | `<img>` in content region | `src`, `alt`, `title` attributes |
| `links` | `<a>` in content region | `href`, anchor text, internal/external flag |
| `word_count` | Computed from body_text | Split + count |
| `reading_time_minutes` | Computed from word_count | word_count / 200 |
| `language` | `<html lang="">`, content analysis | Detect from tag or text |
| `published_date` | `<time>`, Schema.org, meta tags, URL patterns | Multiple sources |
| `author` | Schema.org, `<meta name="author">`, byline patterns | Multiple sources |
| `categories` | Schema.org, meta tags, breadcrumb, URL path | Multiple sources |
| `tags` | Schema.org, meta `keywords`, tag cloud | Multiple sources |

#### Product page extraction

| Field | Source | Method |
|-------|--------|--------|
| `product_name` | `<h1>`, Schema.org `name`, `og:title` | Priority chain |
| `price` | Schema.org `offers.price`, `class*="price"`, `itemprop="price"` | Regex + Schema.org |
| `currency` | Schema.org `priceCurrency`, currency symbols | Detect from context |
| `sale_price` | `class*="sale"`, `class*="discount"`, Schema.org | Secondary price element |
| `description` | Schema.org `description`, product detail section | Main text block |
| `sku` | Schema.org `sku`, `data-sku`, product ID patterns | Attribute extraction |
| `brand` | Schema.org `brand`, breadcrumb, meta tags | Multiple sources |
| `availability` | Schema.org `availability`, stock status text | Keyword matching |
| `rating` | Schema.org `aggregateRating`, star elements | Structured data + DOM |
| `review_count` | Schema.org `reviewCount`, review section | Structured data + DOM |
| `images` | Product gallery, Schema.org `image` | Gallery container extraction |
| `variants` | Size/color selectors, option dropdowns | Form element analysis |
| `breadcrumb_category` | Breadcrumb navigation | Path extraction |

#### Job listing extraction

| Field | Source | Method |
|-------|--------|--------|
| `job_title` | `<h1>`, Schema.org `title` | Priority chain |
| `company` | Schema.org `hiringOrganization`, company name element | Structured data + DOM |
| `location` | Schema.org `jobLocation`, location element | Address extraction |
| `remote_type` | "Remote", "Hybrid", "On-site" keywords | Keyword matching |
| `salary_min` | Schema.org `baseSalary`, salary text | Regex extraction |
| `salary_max` | Schema.org `baseSalary`, salary range text | Regex extraction |
| `salary_currency` | Context from salary field | Currency detection |
| `salary_period` | "per year", "per hour", "annual" | Keyword matching |
| `employment_type` | Schema.org `employmentType`, "Full-time"/"Part-time" | Keyword matching |
| `description` | Job description section | Main text block |
| `requirements` | "Requirements", "Qualifications" section | Section extraction |
| `benefits` | "Benefits", "Perks" section | Section extraction |
| `posted_date` | Schema.org `datePosted`, date element | Date extraction |
| `apply_url` | "Apply" button/link href | Link extraction |

#### Article extraction

| Field | Source | Method |
|-------|--------|--------|
| `headline` | `<h1>`, Schema.org `headline` | Priority chain |
| `author` | Schema.org `author`, byline element, `<meta name="author">` | Multiple sources |
| `published_date` | Schema.org `datePublished`, `<time>`, meta tags | Date extraction |
| `modified_date` | Schema.org `dateModified`, meta tags | Date extraction |
| `body_html` | `<article>` content, main content region | Cleaned HTML |
| `body_markdown` | Converted from body_html | HTML → Markdown |
| `body_text` | Plain text from body_html | Tag stripping |
| `featured_image` | Schema.org `image`, `og:image`, first large image | Priority chain |
| `category` | Breadcrumb, Schema.org, URL path | Multiple sources |
| `tags` | Tag list, Schema.org `keywords` | List extraction |
| `word_count` | Computed | word_count / 200 |
| `excerpt` | First paragraph, `og:description`, Schema.org `description` | Priority chain |

**Output**: Structured data per page, fields depend on detected page type

### Step D: Enrich with Metadata

**Input**: Extracted content + original HTML

**Process**: Extract additional metadata that exists across all page types:

| Metadata Source | What it provides |
|-----------------|-----------------|
| **JSON-LD / Schema.org** | Structured data embedded by the site (most authoritative source) |
| **Open Graph (`og:*`)** | Title, description, image, type, URL (used by social media) |
| **Twitter Cards (`twitter:*`)** | Similar to OG, specific to Twitter/X |
| **Dublin Core (`dc.*`)** | Academic/publishing metadata |
| **Microdata (`itemprop`)** | Inline structured data attributes |
| **HTML meta tags** | Description, keywords, author, robots, viewport |
| **Canonical URL** | `<link rel="canonical">` — the preferred URL for this content |
| **Hreflang** | `<link rel="alternate" hreflang="...">` — language variants |
| **Favicon** | `<link rel="icon">` — site icon |

**Output**: Each page enriched with all available metadata

### Step E: Export

**Input**: Extracted + enriched content

**Process**: Generate output files in configured format(s).

See Section 7 (Output Formats) for details.

---

## 7. Output Formats

### Option A: JSON Lines (JSONL)

One JSON object per line, one file per extraction type:

```
data/{domain}/extracted/
├── content.jsonl          # All pages — clean text + metadata
├── products.jsonl         # Product pages only — structured fields
├── jobs.jsonl             # Job listings only — structured fields
├── articles.jsonl         # Articles/blog posts only — structured fields
└── extraction_summary.json  # Stats: pages processed, types detected, etc.
```

**content.jsonl** (one line per page):
```json
{"url": "https://example.com/about", "title": "About Us", "page_type": "generic", "body_text": "We are a company...", "body_markdown": "# About Us\n\nWe are...", "word_count": 450, "language": "en", "metadata": {"og_title": "...", "description": "..."}, "extracted_at": "2026-05-29T12:00:00Z"}
```

**Pros**: Streamable, appendable, easy to load into Elasticsearch (`_bulk` API), works with UNIX tools (`jq`, `wc -l`), standard format for AI training datasets.

### Option B: CSV Files

```
data/{domain}/extracted/
├── content.csv            # All pages — flat fields
├── products.csv           # Product data
├── jobs.csv               # Job listings
├── articles.csv           # Article data
└── extraction_summary.csv
```

**Pros**: Easy to open in Excel, works with existing analysis download/ZIP features, familiar format.

**Cons**: Can't represent nested data (headings list, images list) well. Long text fields make CSVs unwieldy.

### Option C: Markdown Files

```
data/{domain}/extracted/markdown/
├── about.md
├── blog/
│   ├── post-1.md
│   └── post-2.md
├── products/
│   ├── widget-a.md
│   └── widget-b.md
└── _index.json            # Mapping of URL → markdown file
```

Each markdown file includes YAML frontmatter:
```markdown
---
url: https://example.com/blog/post-1
title: How to Build Widgets
author: Jane Smith
date: 2026-05-15
category: Engineering
tags: [widgets, manufacturing]
word_count: 1200
---

# How to Build Widgets

Widgets are essential components...
```

**Pros**: Best for AI training (LLM fine-tuning). Human-readable. Can be fed directly into RAG pipelines (LangChain, LlamaIndex). Preserves document structure.

### Option D: Elasticsearch Bulk Format

```
data/{domain}/extracted/
└── elasticsearch_bulk.jsonl
```

Format (alternating action + document lines):
```json
{"index": {"_index": "site_content", "_id": "sha256_of_url"}}
{"url": "...", "title": "...", "body": "...", "headings": ["h1...", "h2..."], "word_count": 450, "page_type": "article", "crawled_at": "..."}
```

**Pros**: Can be directly loaded via `curl -X POST /_bulk --data-binary @elasticsearch_bulk.jsonl`. Zero transformation needed.

### Option E: SQLite Database

```
data/{domain}/extracted/
└── content.db
```

Tables: `pages`, `products`, `jobs`, `articles`, `metadata`, `links`, `images`

**Pros**: Queryable (`SELECT * FROM products WHERE price < 50`). Single file, portable. No external database needed.

### Recommendation

Implement **JSONL (Option A) + Markdown (Option C)** first:
- JSONL for structured consumption (Elasticsearch, APIs, data pipelines)
- Markdown for AI training and human review

Add CSV (Option B) and Elasticsearch bulk (Option D) as secondary formats.

---

## 8. Extraction Approaches

### Approach A: Rule-Based (Heuristics + Schema.org)

```
HTML → BS4 parsing → Schema.org/JSON-LD extraction → 
Rule-based boilerplate removal → Page type detection → 
Type-specific field extraction → Output
```

| Aspect | Details |
|--------|---------|
| **Speed** | Very fast — processes 100 pages in <5 seconds |
| **Cost** | Zero |
| **Accuracy (articles)** | ~85-90% (well-solved problem) |
| **Accuracy (products)** | ~70% with Schema.org, ~40% without |
| **Accuracy (generic)** | ~75% |
| **Dependencies** | BS4 (existing), optionally `trafilatura`, `python-readability` |
| **Offline** | Yes |

**Best for**: Sites with Schema.org markup, article/blog sites, well-structured HTML.

### Approach B: Trafilatura + Schema.org

```
HTML → Trafilatura (main content + metadata) → 
Schema.org/JSON-LD extraction → Merge → Output
```

| Aspect | Details |
|--------|---------|
| **Speed** | Fast — ~50ms per page |
| **Cost** | Zero |
| **Accuracy (articles)** | ~95% (trafilatura's sweet spot) |
| **Accuracy (products)** | ~60% (trafilatura is article-focused) |
| **Accuracy (generic)** | ~85% |
| **Dependencies** | `trafilatura` pip package (~5MB) |
| **Offline** | Yes |

**Best for**: Article/blog extraction, AI training data, corpus building.

### Approach C: LLM-Assisted Extraction

```
HTML → Basic cleaning → Send to LLM with extraction prompt →
LLM returns structured JSON → Validate → Output
```

| Aspect | Details |
|--------|---------|
| **Speed** | Slow — ~2-5 seconds per page |
| **Cost** | ~$0.01-0.10 per page (depends on page size + model) |
| **Accuracy (all types)** | ~95%+ |
| **Dependencies** | `anthropic` or `openai` SDK |
| **Offline** | No |

**How it works**: Send cleaned HTML (or truncated version) to the LLM with a prompt:

```
Extract structured content from this HTML page.
Return JSON with these fields:
- page_type: (article|product|job|listing|faq|contact|generic)
- title, description, body_text
- If product: name, price, currency, sku, availability
- If job: title, company, location, salary, requirements
- If article: author, date, body, category, tags

HTML:
<div>...</div>
```

**Best for**: High-accuracy extraction from any page type. Handles messy/non-standard HTML well.

### Approach D: Hybrid (Recommended)

```
Step 1: Check for Schema.org/JSON-LD (free, authoritative)
Step 2: Run Trafilatura for main content extraction (free, fast)
Step 3: Apply rule-based type-specific extraction (free, fast)
Step 4: For low-confidence results, optionally send to LLM (paid, accurate)
```

This gets 80%+ accuracy for free, with LLM as an optional enhancement for the remaining 20%.

### Approach E: User-Configured Schemas

For precision extraction on known sites:

```yaml
# extraction_schema.yaml
site: shop.example.com
page_type: product
url_pattern: "/products/*"
fields:
  name: "h1.product-title"
  price: "span.price-current"
  sale_price: "span.price-sale"
  description: "div.product-description"
  sku: "span[data-sku]"
  images: "div.product-gallery img @src"
  availability: "div.stock-status"
```

The user defines CSS selectors for each field. Guaranteed accuracy for configured sites.

**This can coexist with auto-detection**: Try auto-detection first; if a user-defined schema matches the site/URL, use that instead.

### Decision needed

Which approach to start with. Recommendation: **Approach D (Hybrid)** — Schema.org + Trafilatura + heuristics, with LLM and user schemas as optional enhancements.

---

## 9. Boilerplate Removal Strategies

Boilerplate removal is the hardest part of content extraction. Here are the major approaches:

### Strategy 1: Tag-based removal

Remove known non-content tags: `<header>`, `<footer>`, `<nav>`, `<aside>`, elements with ARIA landmark roles.

**Accuracy**: ~60%. Misses boilerplate in `<div>` elements without semantic tags.

### Strategy 2: Text-density analysis

For each DOM node, calculate:
- **Link density**: ratio of anchor text to total text (navigation has high link density)
- **Text density**: ratio of text characters to HTML characters
- **Block size**: number of words in the block

Content blocks have high text density + low link density. Navigation has the opposite.

**Accuracy**: ~80%. The core algorithm used by Trafilatura and Readability.

### Strategy 3: Repetition-based removal

Across all crawled pages, identify blocks that appear on every (or most) pages — these are boilerplate (header, footer, sidebar). Blocks unique to a page are content.

**Accuracy**: ~85%. Requires multiple pages from the same site. Our crawler provides this naturally.

**Unique advantage**: Since we crawl multiple pages from the same site, we can use cross-page repetition analysis that standalone extractors (Trafilatura, Readability) cannot. This is a differentiator.

### Strategy 4: DOM structure analysis

Identify the "main content" container by:
1. Finding the deepest node with the most text
2. Walking up to find the nearest structural ancestor
3. Treating that ancestor as the content region

**Accuracy**: ~75%. Works well on well-structured sites.

### Recommendation

Combine strategies: **Tag-based (baseline) → Text-density (Trafilatura) → Repetition-based (cross-page, our unique advantage)**.

---

## 10. Schema.org / JSON-LD Extraction

Many modern websites embed structured data in JSON-LD format. This is the **most reliable extraction source** when present.

### How to extract

```python
import json
from bs4 import BeautifulSoup

def extract_jsonld(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return results
```

### Common Schema.org types and field mapping

| Schema.org Type | Maps to | Key Fields |
|-----------------|---------|------------|
| `Article`, `BlogPosting`, `NewsArticle` | Article | headline, author, datePublished, articleBody, image |
| `Product` | Product | name, offers.price, description, sku, brand, image |
| `JobPosting` | Job | title, hiringOrganization, jobLocation, baseSalary, datePosted |
| `FAQPage` | FAQ | mainEntity[].name, mainEntity[].acceptedAnswer.text |
| `Organization` | Company info | name, url, logo, address, telephone |
| `BreadcrumbList` | Breadcrumb | itemListElement[].name, itemListElement[].item |
| `WebPage` | Page metadata | name, description, url |
| `Event` | Event | name, startDate, location, offers |
| `Recipe` | Recipe | name, ingredients, instructions, cookTime |
| `Review` | Review | reviewBody, reviewRating, author, datePublished |

### Prevalence

~30-40% of websites include Schema.org/JSON-LD markup. E-commerce sites are higher (~60-70%). News sites are very high (~80%+). Small business sites are lower (~15-20%).

---

## 11. Technical Implementation Plan

### New files to create

| File | Purpose | Est. Lines |
|------|---------|-----------|
| `src/crawler/processors/content_extractor.py` | Main extractor class with 5-step pipeline | ~400-500 |
| `src/crawler/processors/content_models.py` | Data classes: ExtractedPage, Product, Job, Article | ~200 |
| `src/crawler/processors/boilerplate_remover.py` | Boilerplate removal strategies | ~250 |
| `src/crawler/processors/schema_extractor.py` | Schema.org / JSON-LD / Open Graph extraction | ~200 |
| `src/crawler/processors/page_type_detector.py` | Page type classification | ~150 |
| `src/crawler/processors/content_reporter.py` | JSONL, Markdown, CSV export | ~200 |

### Existing files to modify

| File | Change |
|------|--------|
| `src/core/sync_crawl_manager.py` | Add Phase 1.7 call to `ContentExtractor.extract()` |
| `src/core/models.py` | Add `JobStage.EXTRACTING_CONTENT` enum value |
| `requirements.txt` | Add `trafilatura` (optional but recommended) |

### Dependencies

| Package | Required? | Purpose |
|---------|-----------|---------|
| `beautifulsoup4` | Already installed | HTML parsing |
| `trafilatura` | Optional (recommended) | Main content extraction |
| `python-readability` | Optional | Alternative content extraction |
| `markdownify` or `html2text` | Optional | HTML → Markdown conversion |
| `anthropic` / `openai` | Optional | LLM-assisted extraction |

### Data models

```python
@dataclass
class ExtractedPage:
    """Base extraction result for any page."""
    url: str
    title: str
    description: str
    page_type: str                    # "article", "product", "job", "generic"
    page_type_confidence: float
    body_text: str                    # Clean plain text
    body_markdown: str                # Markdown-formatted content
    body_html: str                    # Cleaned HTML (boilerplate removed)
    headings: list[dict]              # [{"level": 1, "text": "..."}]
    images: list[dict]                # [{"src": "...", "alt": "..."}]
    links: list[dict]                 # [{"href": "...", "text": "...", "internal": bool}]
    word_count: int
    reading_time_minutes: float
    language: str
    published_date: str | None
    modified_date: str | None
    author: str | None
    categories: list[str]
    tags: list[str]
    metadata: dict                    # og:*, twitter:*, meta tags, etc.
    schema_org: list[dict]            # Raw JSON-LD data
    canonical_url: str | None
    extracted_at: str                 # ISO timestamp

@dataclass
class ExtractedProduct(ExtractedPage):
    """Product-specific fields."""
    product_name: str
    price: float | None
    currency: str | None
    sale_price: float | None
    sku: str | None
    brand: str | None
    availability: str | None
    rating: float | None
    review_count: int | None
    product_images: list[str]
    variants: list[dict]              # [{"type": "size", "options": ["S","M","L"]}]
    breadcrumb_category: str | None

@dataclass
class ExtractedJob(ExtractedPage):
    """Job listing-specific fields."""
    job_title: str
    company: str | None
    location: str | None
    remote_type: str | None           # "remote", "hybrid", "onsite"
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None         # "annual", "hourly", "monthly"
    employment_type: str | None       # "full-time", "part-time", "contract"
    requirements: list[str]
    benefits: list[str]
    posted_date: str | None
    closing_date: str | None
    apply_url: str | None

@dataclass
class ExtractedArticle(ExtractedPage):
    """Article/blog post-specific fields."""
    headline: str
    excerpt: str | None
    featured_image: str | None
    section: str | None               # "Technology", "Business", etc.
```

---

## 12. Configuration Options

New fields in `CrawlJobConfig`:

```python
# Content extraction settings
extract_content: bool = False                      # Enable/disable content extraction
extraction_output_formats: list[str] = ["jsonl", "markdown"]  # Output format(s)
extraction_use_trafilatura: bool = True            # Use trafilatura for boilerplate removal
extraction_use_llm: bool = False                   # Enable LLM-assisted extraction
extraction_llm_model: str = "claude-sonnet"
extraction_detect_page_types: bool = True          # Auto-detect page types
extraction_page_types: list[str] = []              # Limit to specific types: ["product", "job"]
extraction_custom_schema: str | None = None        # Path to custom extraction schema YAML
extraction_include_html: bool = False              # Include cleaned HTML in output (larger files)
extraction_max_text_length: int | None = None      # Truncate body text (for AI training)
```

---

## 13. Cross-Page Deduplication

### Problem

Boilerplate removal isn't perfect. Some common text leaks through:
- "Subscribe to our newsletter" blocks inside `<main>`
- "Related articles" sections
- Social share button text
- Author bio blocks repeated on every article

### Solution: Cross-page fingerprinting

1. After extracting content from all pages, fingerprint each paragraph/block
2. Blocks that appear on 80%+ of pages are likely boilerplate → remove
3. Blocks that appear on <20% of pages are likely unique content → keep
4. Blocks in between → flag for review

This is a unique advantage of our approach — we have all pages from a site, so we can do cross-page analysis that standalone extractors cannot.

---

## 14. Future Integration Possibilities

### 14.1 Elasticsearch / OpenSearch Integration

```python
# Direct indexing (future feature)
from elasticsearch import Elasticsearch

es = Elasticsearch("http://localhost:9200")
for page in extracted_pages:
    es.index(index="site_content", id=hash(page.url), body=page.to_dict())
```

### 14.2 RAG Pipeline (LangChain / LlamaIndex)

```python
# LangChain integration (future feature)
from langchain.document_loaders import DirectoryLoader

loader = DirectoryLoader("data/example_com/extracted/markdown/", glob="**/*.md")
documents = loader.load()
# → Ready for embedding + vector store
```

### 14.3 Vector Embeddings

```python
# Generate embeddings for semantic search (future feature)
from openai import OpenAI

client = OpenAI()
for page in extracted_pages:
    chunks = chunk_text(page.body_text, max_tokens=500)
    for chunk in chunks:
        embedding = client.embeddings.create(input=chunk, model="text-embedding-3-small")
        # Store in Pinecone / Weaviate / ChromaDB / pgvector
```

### 14.4 Automated Data Pipelines

```
Crawl → Extract → Transform → Load

Examples:
- E-commerce: Crawl competitor → Extract products → Load into price comparison DB
- Recruitment: Crawl job boards → Extract jobs → Load into aggregator
- News: Crawl news sites → Extract articles → Load into content archive
- Research: Crawl academic sites → Extract papers → Load into citation DB
```

---

## 15. Open Questions & Decisions Needed

### Before implementation

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Integration model? | Crawl phase only, standalone tool, or both | **Both** |
| 2 | Which extraction approach? | A (rules), B (trafilatura), C (LLM), D (hybrid), E (user schemas) | **D (hybrid) + E** |
| 3 | Which output formats first? | JSONL, CSV, Markdown, Elasticsearch, SQLite | **JSONL + Markdown** |
| 4 | Which page types to support first? | Generic only, +articles, +products, +jobs | **Generic + articles first** |
| 5 | Should trafilatura be a required dependency? | Required, optional, bundled | **Optional (recommended)** |
| 6 | Should extraction run by default in HTML-only mode? | Always, opt-in toggle, separate command | **Opt-in toggle** |
| 7 | How to handle non-English content? | Language detection + multilingual support | **Detect language, extract regardless** |
| 8 | Maximum page size for LLM extraction? | Truncate large pages or chunk them | **Chunk into 4K token windows** |

### During implementation

| # | Question | When to decide |
|---|----------|---------------|
| 9 | Text chunking strategy for AI training output? | After testing with real content |
| 10 | How to handle dynamically loaded content (infinite scroll, lazy load)? | This is a crawl-time issue, not extraction-time |
| 11 | Should extracted content be stored in MongoDB alongside crawl metadata? | After seeing output sizes |
| 12 | Custom schema format — YAML? JSON? Python dict? | When implementing user schemas |

---

## 16. Success Metrics

| Metric | Target |
|--------|--------|
| Boilerplate removal accuracy | >90% of boilerplate removed |
| Content preservation accuracy | >95% of actual content preserved |
| Article extraction accuracy (with trafilatura) | >90% |
| Product extraction accuracy (with Schema.org) | >85% |
| Product extraction accuracy (without Schema.org) | >60% |
| Job extraction accuracy (with Schema.org) | >85% |
| Processing speed (100 pages) | <10 seconds |
| Processing speed (1000 pages) | <2 minutes |

---

## 17. Relationship to Component Analyzer

The Content Extractor and Component Analyzer are **complementary but independent** features:

| Aspect | Component Analyzer | Content Extractor |
|--------|-------------------|-------------------|
| **Purpose** | Detect UI structure for CMS migration | Extract content for data consumption |
| **What it looks at** | DOM structure, CSS classes, ARIA roles | Text content, metadata, structured data |
| **Output** | Component catalog, page templates | Clean text, structured records |
| **Use case** | "What components do I need to build?" | "What content does this site contain?" |
| **Crawl mode** | Full mirror (needs structure) | HTML-only (needs content) |
| **Pipeline phase** | Phase 1.6 | Phase 1.7 |

They can run independently or together. Running both gives you a complete migration toolkit: component architecture + content inventory.

---

## 18. References

### Libraries to evaluate

- **Trafilatura**: https://github.com/adbar/trafilatura — Main content extraction
- **python-readability**: https://github.com/buriy/python-readability — Reader view extraction
- **Newspaper4k**: https://github.com/AndyTheFactory/newspaper4k — Article extraction
- **html2text**: https://github.com/Alir3z4/html2text — HTML → Markdown
- **markdownify**: https://github.com/matthewwithanm/python-markdownify — HTML → Markdown
- **extruct**: https://github.com/scrapinghub/extruct — Schema.org/JSON-LD/Microdata extraction
- **Unstructured**: https://github.com/Unstructured-IO/unstructured — Document parsing

### Standards

- **Schema.org**: https://schema.org — Structured data vocabulary
- **JSON-LD**: https://json-ld.org — Linked data format for Schema.org
- **Open Graph**: https://ogp.me — Facebook/social media metadata
- **Dublin Core**: https://dublincore.org — Metadata standard
