# Component Analyzer — Requirements & Design Document

> **Created:** 2026-05-29
> **Status:** Draft — awaiting decision on approach & scope before implementation
> **Author:** Auto-generated from design session
> **Related:** `CONTEXT.md`, `src/crawler/processors/sync_analysis_generator.py`

---

## 1. Executive Summary

**Goal**: After crawling a website's HTML pages, automatically detect and catalog the UI components used across the site (headers, footers, navigation, cards, buttons, tables, forms, etc.), identify variants, and produce a migration-ready component inventory.

**Why**: Site migrations to CMS platforms (Adobe AEM, Jahia, Strapi, WordPress, etc.) require a manual audit of every page to identify what components are needed. For large sites (100+ pages), this audit takes weeks. Our crawler already downloads all the HTML — the missing step is automated analysis to extract a component catalog.

**Value**: Reduces migration audit from weeks to minutes. Produces a structured, repeatable output that can feed directly into CMS template creation.

---

## 2. Problem Statement

### Current migration workflow (manual)

```
1. Open each page in a browser
2. Visually identify recurring UI patterns (hero, cards, nav, etc.)
3. Document them in a spreadsheet
4. Identify variants (primary button vs secondary button, etc.)
5. Map components to CMS templates/blocks
6. Build CMS components from the spreadsheet
```

Steps 1-4 are tedious, error-prone, and don't scale. A developer might miss components that appear on only a few pages, or fail to notice subtle variants.

### Proposed automated workflow

```
1. Crawl website (existing feature)
2. Run component analyzer on crawled HTML (NEW)
3. Review generated component catalog
4. Map to CMS templates (partially automatable)
5. Build CMS components (future: code generation)
```

---

## 3. Scope

### In scope (this feature)

- Parse crawled HTML files from the `data/{domain}/html/` directory
- Detect structural and atomic UI components across all pages
- Identify recurring patterns (components that appear on 2+ pages)
- Classify components by type (header, footer, card, button, etc.)
- Detect variants within each component type
- Extract page templates (which components each page uses)
- Generate component catalog reports (CSV, JSON, HTML)
- Integrate into the existing crawl pipeline as a new processing phase

### Out of scope (future work)

- Automated CMS template/block code generation
- Visual screenshot capture of each component
- CSS/styling extraction (only structural HTML analysis)
- JavaScript behavior analysis
- Automated content migration (moving text/images into CMS)
- Design token extraction (colors, fonts, spacing)

### Future vision (not this phase)

- Automated React/Vue component stub generation from detected patterns
- CMS-specific template generation (AEM components, WordPress Gutenberg blocks, Strapi content types)
- Visual diff between source site and migrated CMS site
- Content model generation for headless CMS platforms

---

## 4. Pipeline Architecture

### Where it fits in the crawl lifecycle

```
Phase 1:   HTML Crawl (SyncHTMLDownloader)          ← existing
Phase 1.5: Analysis Reports (SyncAnalysisGenerator)  ← existing (10 CSVs)
Phase 1.6: Component Analysis (ComponentAnalyzer)     ← NEW
Phase 2:   Server Mirror Build (SyncServerBuilder)    ← existing
```

### Integration point

In `src/core/sync_crawl_manager.py`, after `SyncAnalysisGenerator` and before `SyncServerBuilder`:

```python
# ── Phase 1.6: Component Analysis ────────────────────
await self._update_job(job_id, {"stage": "analyzing_components"})
analyzer = ComponentAnalyzer()
await loop.run_in_executor(
    self._executor,
    lambda: analyzer.analyze(
        domain=project_safe_name,
        html_root=self.settings.html_dir,
        output_root=self.settings.analyses_dir,
    )
)
```

### New file location

```
src/crawler/processors/
├── sync_analysis_generator.py     # Existing — 10 CSV reports
├── sync_server_builder.py         # Existing — offline mirror
└── component_analyzer.py          # NEW — component detection & catalog
```

---

## 5. Component Detection Pipeline

Six-step pipeline, each step feeding into the next:

```
Step A: Parse       → Clean DOM trees from raw HTML
Step B: Segment     → Break each page into structural blocks
Step C: Fingerprint → Create structural signatures for each block
Step D: Cluster     → Group similar blocks across all pages
Step E: Classify    → Label each cluster as a component type
Step F: Report      → Generate component catalog + migration report
```

### Step A: Parse HTML → Clean DOM Trees

**Input**: Raw HTML files from `data/{domain}/html/`

**Process**:
- Parse each HTML file with BeautifulSoup (already a project dependency)
- Strip non-visual elements: `<script>`, `<style>`, `<link>`, `<meta>`, comments, tracking pixels
- Normalize whitespace
- Extract the `<body>` content (ignore `<head>`)

**Output**: Clean DOM tree per page

### Step B: Segment Pages into Structural Blocks

**Input**: Clean DOM trees

**Process**: Extract meaningful blocks using multiple signals:

| Signal | How it works | Example |
|--------|-------------|---------|
| **Semantic HTML5 tags** | Direct mapping to component types | `<header>`, `<footer>`, `<nav>`, `<main>`, `<aside>`, `<section>`, `<article>` |
| **ARIA landmarks** | Role-based identification | `role="banner"`, `role="navigation"`, `role="contentinfo"`, `role="complementary"` |
| **CSS class patterns** | Match common naming conventions (BEM, utility, framework) | `.header`, `.footer`, `.card`, `.btn`, `.nav-*`, `.sidebar`, `.hero`, `.modal` |
| **DOM depth heuristics** | Top-level children of `<body>` or `<main>` are major sections | First-level `<div>` children |
| **Repetition detection** | Sibling elements with identical structure = list/grid of components | 5 `<div class="card">` siblings inside a `<div class="card-grid">` |

**Output**: List of `Block` objects per page, each with:
- `html`: raw HTML snippet
- `tag_path`: e.g., `body > main > section > div.card-grid > div.card`
- `depth`: nesting level
- `page_url`: which page it came from
- `parent_block_id`: for hierarchy tracking

### Step C: Fingerprint Blocks

**Input**: Block objects

**Process**: Generate two types of fingerprints for each block:

1. **Structural fingerprint** (tag-only):
   - Strip all text content and attribute values
   - Keep only tag names, nesting structure, and attribute presence
   - Hash the result
   - Example: `<div><h3>...</h3><p>...</p><a class="btn">...</a></div>` → `div>h3+p+a.btn` → hash `A3F2...`

2. **Class fingerprint** (CSS classes):
   - Extract all CSS class names used in the block and its children
   - Sort and hash
   - Example: `card card-body card-title btn btn-primary` → hash `B7E1...`

**Why two fingerprints**: Structural catches blocks that look the same regardless of class naming. Class-based catches framework-specific patterns (Bootstrap `.card`, Tailwind patterns, etc.).

**Output**: Each block annotated with `structural_hash` and `class_hash`

### Step D: Cluster Similar Blocks

**Input**: All blocks from all pages with fingerprints

**Process**:
1. Group blocks by `structural_hash`
2. Within each group, sub-group by `class_hash` (to identify variants)
3. Filter: keep only clusters with 2+ blocks (appears on multiple pages = reusable component)
4. For single-occurrence blocks: flag as "page-specific" (not a reusable component)
5. Calculate frequency: how many pages each component appears on

**Output**: Component clusters, each containing:
- `component_id`: unique identifier
- `structural_hash`: the shared structure
- `frequency`: number of pages it appears on
- `pages`: list of page URLs where it appears
- `blocks`: list of actual block instances (with their HTML)
- `variants`: sub-clusters based on class fingerprint differences

### Step E: Classify Component Types

**Input**: Component clusters

**Process**: Apply heuristic rules to label each cluster:

| Component Type | Detection Rules |
|----------------|----------------|
| **Header** | `<header>` tag, OR `role="banner"`, OR class matches `header/hdr/masthead`, OR appears as first major block on 80%+ pages |
| **Footer** | `<footer>` tag, OR `role="contentinfo"`, OR class matches `footer/ftr`, OR appears as last major block on 80%+ pages |
| **Navigation** | `<nav>` tag, OR `role="navigation"`, OR class matches `nav/menu/navbar`, OR `<ul>` containing 3+ `<a>` children |
| **Hero / Banner** | First `<section>` after header, contains `<h1>` + large image/background, class matches `hero/banner/jumbotron` |
| **Card** | Repeated sibling blocks containing image + heading + text + link, class matches `card/tile/feature` |
| **Button** | `<button>` tag, OR `<a>` with class matching `btn/button/cta`, OR `role="button"` |
| **Table** | `<table>` tag, OR class matches `table/data-grid/datagrid` |
| **Form** | `<form>` tag, contains `<input>` + `<label>` pairs |
| **Sidebar** | `<aside>` tag, OR `role="complementary"`, OR class matches `sidebar/aside/rail` |
| **Breadcrumb** | `<nav>` with `<ol>` or `<ul>` containing `>` separators, OR class matches `breadcrumb`, OR `aria-label="breadcrumb"` |
| **Pagination** | Class matches `pagination/pager`, contains sequential number links |
| **Accordion** | Class matches `accordion/collapsible/expandable`, contains toggle triggers + hidden panels |
| **Tab** | Class matches `tab/tabs`, contains tab buttons + tab panels |
| **Modal / Dialog** | `role="dialog"`, OR class matches `modal/dialog/popup/overlay`, OR has `aria-modal="true"` |
| **Alert / Toast** | `role="alert"`, OR class matches `alert/toast/notification/banner-message` |
| **Search** | `<form>` with `role="search"`, OR `<input type="search">`, OR class matches `search` |
| **Media** | `<figure>`, `<video>`, `<audio>`, OR class matches `media/player/embed` |
| **List** | `<ul>` or `<ol>` with structured `<li>` children (not navigation), class matches `list/listing` |
| **Icon** | `<svg>`, `<i class="icon...">`, `<span class="icon...">`, font-icon patterns |
| **Badge / Tag** | Small inline elements with class matching `badge/tag/label/chip/pill` |
| **Image** | `<img>` with specific layout patterns (gallery, carousel, thumbnail grid) |
| **Carousel / Slider** | Class matches `carousel/slider/swiper/slick`, contains multiple slides |
| **CTA Block** | Section with prominent heading + button(s), class matches `cta/call-to-action` |
| **Testimonial** | Repeated blocks with quote/text + author/attribution, class matches `testimonial/review/quote` |
| **Pricing Table** | Repeated column blocks with price + features + CTA, class matches `pricing/plan` |
| **FAQ** | Accordion-like pattern with question + answer pairs, class matches `faq` |
| **Timeline** | Ordered items with date/time markers, class matches `timeline/history` |
| **Stat / Counter** | Block with large number + label, class matches `stat/counter/metric/kpi` |
| **Unknown** | Fallback — doesn't match any known type. Flagged for manual review. |

**Confidence scoring**: Each classification gets a confidence level:
- **High** (0.8-1.0): Multiple signals agree (tag + class + ARIA + position)
- **Medium** (0.5-0.79): Some signals match
- **Low** (0.3-0.49): Weak signals, likely needs manual verification

**Output**: Each cluster labeled with `component_type`, `confidence`, and `classification_reasons`

### Step F: Generate Reports

See Section 8 (Output Formats) for details.

---

## 6. Variant Detection

Within each component type, detect structural or stylistic variants:

### How variants are identified

1. **Same structural hash, different class hash** → styling variant
   - Example: `btn btn-primary` vs `btn btn-secondary` vs `btn btn-outline`

2. **Similar but not identical structure** → structural variant
   - Example: Card with image vs Card without image vs Card with icon
   - Use tree-edit-distance or subtree matching with a similarity threshold (e.g., 80%+)

3. **Same structure, different content pattern** → content variant
   - Example: Blog post card (has date) vs Product card (has price)

### Variant output schema

```json
{
  "component_type": "button",
  "variant_id": "btn-primary",
  "variant_label": "Primary Button",
  "frequency": 47,
  "pages": ["page1.html", "page2.html", ...],
  "css_classes": ["btn", "btn-primary"],
  "representative_html": "<a class=\"btn btn-primary\" href=\"#\">Learn More</a>",
  "differs_from_base": ["class: btn-primary vs btn-secondary"]
}
```

---

## 7. Page Template Extraction

Each crawled page is mapped to the set of components it uses:

### Template fingerprint

```json
{
  "page_url": "/products/widget-a",
  "template_fingerprint": "header+nav+breadcrumb+hero+card-grid+cta+footer",
  "components_used": [
    {"type": "header", "variant": "default", "position": "top"},
    {"type": "navigation", "variant": "main-nav", "position": "top"},
    {"type": "breadcrumb", "variant": "default", "position": "below-nav"},
    {"type": "hero", "variant": "with-image", "position": "main-first"},
    {"type": "card", "variant": "product-card", "count": 6, "position": "main"},
    {"type": "cta", "variant": "full-width", "position": "main-last"},
    {"type": "footer", "variant": "default", "position": "bottom"}
  ]
}
```

### Template clustering

Pages with identical `template_fingerprint` use the same template:

```
Template A: "Standard Product Page"
  → /products/widget-a, /products/widget-b, /products/widget-c  (15 pages)
  → Components: header + nav + breadcrumb + hero + card-grid + cta + footer

Template B: "Blog Post Page"
  → /blog/post-1, /blog/post-2  (42 pages)
  → Components: header + nav + breadcrumb + article + sidebar + footer

Template C: "Homepage"
  → /  (1 page)
  → Components: header + nav + hero-large + card-grid + testimonials + cta + footer
```

This tells the migration team: "You need 3 page templates and 8 unique components."

---

## 8. Output Formats

Three output formats are proposed. The decision on which to implement first is deferred.

### Option A: CSV Files (consistent with existing reports)

Added to the existing `data/{domain}/analyses/` directory alongside the 10 existing CSV reports:

| File | Contents |
|------|----------|
| `component_catalog.csv` | One row per unique component: type, variant, frequency, pages, representative HTML snippet, confidence score |
| `component_instances.csv` | One row per component instance: page URL, component type, variant, position, HTML snippet |
| `page_templates.csv` | One row per page: URL, template name, list of components used |
| `template_summary.csv` | One row per unique template: template name, page count, component list |
| `variant_matrix.csv` | Matrix of component types × variants with frequency counts |
| `migration_checklist.csv` | Prioritized list of components to build, ordered by frequency |

**Pros**: Consistent with existing reports, easy to open in Excel, works with existing download/ZIP features.

### Option B: JSON File

Single comprehensive JSON file at `data/{domain}/analyses/component_analysis.json`:

```json
{
  "metadata": {
    "domain": "example.com",
    "pages_analyzed": 47,
    "generated_at": "2026-05-29T12:00:00Z",
    "analyzer_version": "1.0"
  },
  "components": [
    {
      "component_id": "comp_001",
      "type": "header",
      "confidence": 0.95,
      "frequency": 47,
      "pages": ["page1.html", "page2.html"],
      "variants": [
        {
          "variant_id": "header-default",
          "frequency": 45,
          "css_classes": ["site-header", "header-main"],
          "representative_html": "<header class=\"site-header\">...</header>"
        }
      ],
      "classification_reasons": ["<header> tag", "role=banner", "appears on 100% of pages"]
    }
  ],
  "templates": [...],
  "migration_summary": {
    "total_components": 12,
    "total_variants": 28,
    "total_templates": 3,
    "estimated_build_effort": "12 components × ~4 hrs avg = ~48 hrs"
  }
}
```

**Pros**: Machine-readable, can feed into future automation (CMS template generation, code stubs), rich nested structure.

### Option C: HTML Visual Report

Interactive HTML report at `data/{domain}/analyses/component_report.html`:

- Component gallery with collapsible HTML snippets
- Visual hierarchy tree
- Page template breakdown
- Clickable navigation between components and the pages they appear on
- Embeddable in project documentation

**Pros**: Easy to share with stakeholders who don't want to look at CSV/JSON. Visual review of detected components.

### Recommendation

Implement **Option A (CSV) + Option B (JSON)** first. CSV for human review, JSON for programmatic consumption. Option C (HTML report) can be added later as a nice-to-have.

---

## 9. Detection Approaches

### Approach A: Pure Heuristics (no AI)

```
HTML files → BeautifulSoup parsing → Rule-based segmentation → 
Structural fingerprinting → Clustering → Heuristic classification → Reports
```

| Aspect | Details |
|--------|---------|
| **Speed** | Fast — processes 100 pages in seconds |
| **Cost** | Zero — no API calls |
| **Accuracy** | ~80% on well-structured sites (semantic HTML, BEM/utility classes) |
| **Accuracy** | ~50-60% on legacy sites (div soup, no semantic HTML) |
| **Dependencies** | BeautifulSoup (already installed) |
| **Offline** | Yes — no internet required |

**Best for**: Sites built with modern frameworks (React, Vue, Angular), Bootstrap, Tailwind, or semantic HTML5.

**Struggles with**: Legacy sites where everything is nested `<div>` with non-descriptive classes like `<div class="a1 b2 c3">`.

### Approach B: LLM-Assisted Classification

```
HTML files → BeautifulSoup parsing → Block extraction →
Send blocks to LLM (Claude/GPT) → LLM classifies component types →
Clustering + deduplication → Reports
```

| Aspect | Details |
|--------|---------|
| **Speed** | Slower — ~1-2 seconds per block, rate-limited by API |
| **Cost** | ~$0.01-0.05 per page (depending on HTML size and model) |
| **Accuracy** | ~90-95% even on legacy/messy HTML |
| **Dependencies** | API key for Claude or OpenAI |
| **Offline** | No — requires API access |

**How it works**: Each extracted HTML block is sent to the LLM with a prompt like:

```
Analyze this HTML block and classify it:
1. Component type (header, footer, card, button, etc.)
2. Component variants (primary/secondary, with/without image, etc.)
3. Confidence level (high/medium/low)
4. Child components contained within

HTML:
<div class="xyz">...</div>
```

**Best for**: Legacy sites, sites with non-standard class names, ambiguous structures.

### Approach C: Hybrid (Recommended)

```
Step 1: Heuristic analysis (fast, free) → produces initial catalog
Step 2: Flag low-confidence classifications
Step 3: Send ONLY low-confidence blocks to LLM for re-classification
Step 4: Merge results
```

This gets 80% of components classified for free (heuristics), then uses LLM only for the remaining 20% that need help. Cost is ~80% lower than full LLM analysis.

### Decision needed

Which approach to implement first. Recommendation: **Start with Approach A (pure heuristics)**, get it working end-to-end, then add LLM as an optional enhancement (Approach C).

---

## 10. Component Granularity Levels

Three levels of granularity are possible. The decision on which to implement is deferred.

### Level 1: Structural Components Only

Major page-level building blocks:

- Header, Footer, Navigation, Sidebar
- Hero / Banner, Card Grid, CTA Block
- Content Section, Article, Form
- Table, Modal / Dialog

**~15 component types.** Fastest to implement. Sufficient for basic migration planning.

### Level 2: Structural + Atomic Components

Everything in Level 1, plus:

- Buttons (and variants: primary, secondary, outline, icon, sizes)
- Form inputs (text, select, checkbox, radio, textarea, date picker)
- Badges, Tags, Pills
- Icons, Avatars
- Links (text link, button link, icon link)
- Typography patterns (heading hierarchy, paragraph styles, blockquotes)
- Images (standalone, gallery, thumbnail, avatar)
- Lists (ordered, unordered, definition, icon list)

**~30 component types.** Full design system scope. Needed for complete CMS migration.

### Level 3: Structural + Atomic + Content Patterns

Everything in Level 2, plus domain-specific content patterns:

- Blog post layout, Product listing, Pricing table
- Testimonial block, FAQ accordion, Team member grid
- Timeline, Stats/counters, Feature comparison
- Event listing, Job posting, Portfolio/gallery
- Contact info block, Map embed, Social media links

**~50 component types.** Maximum coverage. Useful when migrating content-heavy marketing sites.

### Recommendation

Start with **Level 2 (Structural + Atomic)**. It covers the full component set needed for CMS migration without getting into domain-specific patterns that may be too specialized.

---

## 11. CMS Migration Mapping

The component catalog should be CMS-agnostic but include metadata that helps map to specific platforms.

### Target CMS Platforms (potential)

| CMS | Component Concept | What our output maps to |
|-----|-------------------|------------------------|
| **Adobe AEM** | Components (Sling models + HTL templates) | Each detected component → AEM component spec |
| **Jahia** | Templates + Views (JCR node types) | Each detected component → Jahia view definition |
| **Strapi** | Content Types + Components | Structural components → Content Types; Atomic → Components |
| **WordPress / Gutenberg** | Blocks (PHP + React) | Each detected component → Gutenberg block spec |
| **Contentful** | Content Models + Components | Each detected component → Content Model definition |
| **Next.js / React** | React components (`.tsx` files) | Each detected component → React component stub with props |

### Migration metadata per component

```json
{
  "component_type": "card",
  "variant": "product-card",
  "cms_mapping": {
    "content_fields": [
      {"name": "title", "type": "text", "source": "h3"},
      {"name": "description", "type": "rich_text", "source": "p"},
      {"name": "image", "type": "media", "source": "img"},
      {"name": "link", "type": "url", "source": "a.btn"},
      {"name": "price", "type": "text", "source": "span.price"}
    ],
    "is_repeatable": true,
    "typical_count_per_page": 6,
    "container_component": "card-grid"
  }
}
```

This metadata is CMS-agnostic but contains everything needed to create a content model in any CMS.

### Decision needed

Whether to generate CMS-specific output files (e.g., Strapi JSON schema, WordPress block.json) or keep it generic. Recommendation: **Keep it CMS-agnostic in Phase 1**, add CMS-specific exporters as separate modules later.

---

## 12. Technical Implementation Plan

### New files to create

| File | Purpose | Est. Lines |
|------|---------|-----------|
| `src/crawler/processors/component_analyzer.py` | Main analyzer class with the 6-step pipeline | ~500-700 |
| `src/crawler/processors/component_models.py` | Data classes: Block, Component, Variant, Template, Cluster | ~150 |
| `src/crawler/processors/component_classifiers.py` | Heuristic classification rules (Step E) | ~300 |
| `src/crawler/processors/component_fingerprint.py` | Structural and class fingerprinting (Step C) | ~150 |
| `src/crawler/processors/component_reporter.py` | CSV + JSON report generation (Step F) | ~200 |

### Existing files to modify

| File | Change |
|------|--------|
| `src/core/sync_crawl_manager.py` | Add Phase 1.6 call to `ComponentAnalyzer.analyze()` |
| `src/core/models.py` | Add `JobStage.ANALYZING_COMPONENTS` enum value |
| `src/ui/templates/job_detail.html` | Show component analysis status in job detail view |

### Dependencies

- **BeautifulSoup4** — already installed (used by `sync_analysis_generator.py`)
- **No new dependencies required** for Approach A (heuristics)
- For Approach B (LLM): `anthropic` or `openai` Python SDK (add to `requirements.txt`)

### Data models

```python
@dataclass
class Block:
    """A structural block extracted from a page."""
    block_id: str
    page_url: str
    html: str
    tag: str                          # e.g., "header", "div", "section"
    tag_path: str                     # e.g., "body > main > section.hero"
    depth: int
    css_classes: list[str]
    aria_role: str | None
    structural_hash: str
    class_hash: str
    children_count: int
    parent_block_id: str | None

@dataclass
class Component:
    """A detected reusable component (cluster of similar blocks)."""
    component_id: str
    component_type: str               # "header", "card", "button", etc.
    confidence: float                 # 0.0 - 1.0
    classification_reasons: list[str]
    frequency: int                    # number of pages it appears on
    pages: list[str]
    structural_hash: str
    representative_html: str          # cleanest/shortest example
    variants: list['Variant']
    children_components: list[str]    # component_ids of nested components

@dataclass
class Variant:
    """A variant of a component (same structure, different styling/content)."""
    variant_id: str
    variant_label: str                # e.g., "Primary Button", "Card with Image"
    frequency: int
    css_classes: list[str]
    representative_html: str
    diff_from_base: list[str]         # what makes this variant different

@dataclass
class PageTemplate:
    """A page template — the set of components a page uses."""
    template_id: str
    template_name: str                # e.g., "Product Page", "Blog Post"
    template_fingerprint: str         # hash of component list
    page_count: int
    pages: list[str]
    components: list[dict]            # [{type, variant, position, count}]
```

---

## 13. Configuration Options

New fields in `CrawlJobConfig` (or a separate config):

```python
# Component analysis settings
analyze_components: bool = True                    # Enable/disable component analysis
component_min_frequency: int = 2                   # Min pages a block must appear on to be considered a component
component_confidence_threshold: float = 0.3        # Min confidence to include in catalog
component_granularity: str = "structural_atomic"   # "structural", "structural_atomic", "full"
component_use_llm: bool = False                    # Enable LLM-assisted classification
component_llm_model: str = "claude-sonnet"         # Which LLM model to use
component_llm_api_key: str | None = None           # API key (or use env var)
```

---

## 14. Future Automation Vision

### Phase 1 (this document): Component Detection
- Analyze crawled HTML → produce component catalog
- Manual review of catalog → refine classifications
- Output: "You need these N components to migrate this site"

### Phase 2: CMS-Specific Export
- Take the component catalog → generate CMS-specific schemas
- Strapi content types, WordPress block.json, AEM component specs
- Output: "Here are the CMS definitions, ready to import"

### Phase 3: Component Code Generation
- Take detected components → generate starter code
- React components with props derived from content fields
- CSS/Tailwind classes derived from source styling
- Output: "Here are your component stubs, ready to customize"

### Phase 4: Content Migration
- Take crawled content + component catalog → extract structured content
- Map content into CMS content models
- Populate CMS via API (Strapi REST, WordPress REST, Contentful Management API)
- Output: "Your site is migrated — review and publish"

### Phase 5: Visual Validation
- Render migrated CMS pages
- Screenshot comparison with original crawled pages
- Diff report highlighting visual discrepancies
- Output: "These 3 pages have layout differences — review them"

---

## 15. Open Questions & Decisions Needed

### Before implementation

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Which detection approach to start with? | A (heuristics), B (LLM), C (hybrid) | **A — heuristics first** |
| 2 | Which output formats? | CSV, JSON, HTML report, all | **CSV + JSON first** |
| 3 | Which granularity level? | L1 (structural), L2 (+atomic), L3 (+content patterns) | **L2 — structural + atomic** |
| 4 | CMS-specific output in Phase 1? | Generic only, or include CMS exporters | **Generic only** |
| 5 | Should it run automatically after every crawl? | Always, opt-in toggle, separate manual trigger | **Opt-in toggle** in `CrawlJobConfig` |
| 6 | How to handle very large sites (1000+ pages)? | Process all, sample N pages, process in batches | **Process all** (fingerprinting is fast) |
| 7 | Should the UI show component results? | New UI page, add to existing job detail, separate tool | **Add to existing job detail** page |

### During implementation

| # | Question | When to decide |
|---|----------|---------------|
| 8 | Similarity threshold for variant detection (80%? 90%?) | After testing with real crawled sites |
| 9 | Should components be nested (card inside card-grid) or flat? | After prototyping Step B segmentation |
| 10 | How to handle framework-specific patterns (Bootstrap vs Tailwind vs custom)? | After testing with multiple sites |
| 11 | Maximum HTML snippet size to store per component? | After seeing real output sizes |

---

## 16. Success Metrics

| Metric | Target |
|--------|--------|
| Component detection accuracy (well-structured sites) | >80% |
| Component detection accuracy (legacy sites, heuristics only) | >50% |
| Component detection accuracy (legacy sites, with LLM) | >90% |
| Processing time (100 pages) | <30 seconds |
| Processing time (1000 pages) | <5 minutes |
| False positive rate (blocks classified as components that aren't) | <15% |
| Coverage (% of page content captured by detected components) | >85% |

---

## 17. References

### Existing code to reuse/reference

- `src/crawler/processors/sync_analysis_generator.py` — Pattern for parsing HTML files and generating CSV reports
- `src/crawler/extractors/link_extractor.py` — Pattern for DOM traversal with BeautifulSoup
- `src/crawler/extractors/asset_extractor.py` — Pattern for extracting structured data from HTML

### Academic / research references

- **VIPS (Vision-based Page Segmentation)** — Microsoft Research, 2003. Segments web pages into semantic blocks using visual cues.
- **DOM-based page segmentation** — Various approaches using DOM tree analysis for block detection.
- **Web page clustering** — Using structural similarity for grouping similar pages.

### Industry tools (partial overlap)

- **Storybook** — Component catalog (manual, not auto-detected)
- **Pattern Lab** — Atomic design system builder (manual)
- **Fractal** — Component library tool (manual)
- **Bit.dev** — Component sharing platform (for existing codebases, not HTML analysis)
