from src.core.models import JobStage, QueueItem, DiscoveryType
from src.utils.url_normalizer import normalize_url

async def seed_queue(engine):
    """Seed crawl queue with initial URLs based on crawl_mode decoupled from CrawlerEngine."""
    if engine.config.crawl_mode in ["queue_based", "queue_and_sitemap"]:
        entry_url = engine.config.entry_url or f"https://{engine.config.domain}"
        normalized = normalize_url(entry_url)
        
        if normalized:
            await engine.queue_manager.add_url(QueueItem(
                url=normalized,
                depth=0,
                discovery_type=DiscoveryType.ENTRY_POINT,
                priority=1
            ))
            
            await engine.job_repo.update_job(engine.job.job_id, {
                "entry_point": normalized,
                "stage": JobStage.CRAWLING_MAIN_SITE.value
            })
            
            if engine.on_stage_change:
                engine.on_stage_change(JobStage.CRAWLING_MAIN_SITE)
    
    if engine.config.crawl_mode in ["sitemap_only", "queue_and_sitemap"]:
        if engine.config.sitemap_urls:
            for sitemap_url in engine.config.sitemap_urls:
                await parse_sitemap(engine, sitemap_url)
        else:
            await discover_sitemap(engine)
    
    for orphan_url in engine.config.orphan_urls:
        normalized = normalize_url(orphan_url)
        if normalized:
            await engine.queue_manager.add_url(QueueItem(
                url=normalized,
                depth=0,
                source_url="admin",
                discovery_type=DiscoveryType.ORPHAN,
                priority=2
            ))

async def discover_sitemap(engine):
    """Discover and parse sitemap.xml."""
    sitemap_urls = [
        f"https://{engine.config.domain}/sitemap.xml",
        f"https://{engine.config.domain}/sitemap_index.xml",
        f"https://www.{engine.config.domain}/sitemap.xml",
    ]
    
    for sitemap_url in sitemap_urls:
        try:
            response = await engine.http_client.get(sitemap_url, timeout=10.0)
            if response.status_code == 200:
                await parse_sitemap(engine, sitemap_url, response.text)
                await engine.job_repo.update_job(engine.job.job_id, {"sitemap_found": True})
                break
        except Exception:
            continue

async def parse_sitemap(engine, sitemap_url: str, content: str = None):
    """Parse sitemap and add URLs to queue."""
    from src.crawler.discovery.sitemap_parser import SitemapParser
    
    try:
        if content is None:
            response = await engine.http_client.get(sitemap_url, timeout=10.0)
            content = response.text
        
        parser = SitemapParser()
        urls = parser.parse(content)
        
        for url_data in urls:
            url = url_data.get("loc", "")
            if url:
                normalized = normalize_url(url)
                if normalized and engine.url_filter.should_crawl(normalized):
                    await engine.queue_manager.add_url(QueueItem(
                        url=normalized,
                        depth=0,
                        source_url=sitemap_url,
                        discovery_type=DiscoveryType.SITEMAP,
                        priority=2
                    ))
    except Exception as e:
        if engine.on_error:
            engine.on_error(f"sitemap_parse_{sitemap_url}", e)
