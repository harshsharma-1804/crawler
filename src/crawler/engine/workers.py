import asyncio
import time
from src.core.models import JobStatus, JobStage, URLRecord, AssetRecord, DiscoveryType, QueueItem
from src.utils.url_normalizer import normalize_url, is_external_link

async def html_crawl_worker(engine, worker_id: int):
    """HTML crawl worker decoupled from CrawlerEngine."""
    while engine.is_running and not engine.stop_requested:
        if engine.is_paused:
            await asyncio.sleep(1)
            continue
        
        item = await engine.queue_manager.get_next_url(timeout=1.0)
        if not item:
            if engine.queue_manager.get_remaining() == 0:
                await asyncio.sleep(2)
                if engine.queue_manager.get_remaining() == 0:
                    break
            continue
        
        if not engine.depth_manager.is_allowed(item.url, item.depth):
            continue
        
        await engine.rate_limiter.acquire(engine.config.domain)
        
        try:
            start_time = time.time()
            result = await engine.html_downloader.download(item.url)
            crawl_time = int((time.time() - start_time) * 1000)
            
            if result.success:
                engine.queue_manager.mark_visited(item.url)
                engine.depth_manager.record_depth(item.url, item.depth)
                
                links = engine.link_extractor.extract(result.content, item.url)
                
                for link_data in links:
                    link_url = link_data.get("url")
                    if not link_url:
                        continue
                    
                    normalized = normalize_url(link_url, item.url)
                    if not normalized:
                        continue
                    
                    if is_external_link(normalized, engine.config.domain):
                        if not engine.config.follow_external_links:
                            continue
                        link_type = "external"
                    else:
                        link_type = "internal"
                    
                    if link_type == "internal" and engine.url_filter.should_crawl(normalized):
                        disc_type = DiscoveryType.HTML_LINK
                        if link_data.get("is_canonical"):
                            disc_type = DiscoveryType.CANONICAL
                        elif link_data.get("is_redirect"):
                            disc_type = DiscoveryType.REDIRECT
                        elif link_data.get("is_js"):
                            disc_type = DiscoveryType.JS_NAVIGATION
                        
                        await engine.queue_manager.add_url(QueueItem(
                            url=normalized,
                            depth=item.depth + 1,
                            source_url=item.url,
                            discovery_type=disc_type
                        ))
                
                assets = engine.asset_extractor.extract(result.content, item.url)
                for asset in assets:
                    asset_url = normalize_url(asset.get("url"), item.url)
                    if asset_url:
                        await engine.queue_manager.add_asset(
                            asset_url,
                            asset.get("type", "other"),
                            item.url
                        )
                
                from src.storage.filesystem_storage import FilesystemStorage
                storage = FilesystemStorage()
                local_path = await storage.save_html(
                    engine.job.job_id,
                    engine.config.domain,
                    item.url,
                    result.content
                )
                
                url_record = URLRecord(
                    url=item.url,
                    domain=engine.config.domain,
                    job_id=engine.job.job_id,
                    link_type="page",
                    source_url=item.source_url,
                    discovery_type=item.discovery_type,
                    depth=item.depth,
                    http_status=result.status_code,
                    content_type=result.content_type,
                    file_size=len(result.content),
                    title=result.title,
                    crawl_success=True,
                    crawl_time_ms=crawl_time,
                    local_path=str(local_path) if local_path else None
                )
                await engine.content_indexer.index_url(url_record)
                
                if engine.config.save_options == "html_content_only":
                    from src.crawler.extractors.html_extractor import HTMLExtractor
                    extractor = HTMLExtractor()
                    html_content = extractor.extract(result.content, item.url)
                    if html_content:
                        await engine.content_indexer.index_html_content(html_content)
                
            else:
                engine.queue_manager.mark_failed(item.url)
                
                url_record = URLRecord(
                    url=item.url,
                    domain=engine.config.domain,
                    job_id=engine.job.job_id,
                    source_url=item.source_url,
                    discovery_type=item.discovery_type,
                    depth=item.depth,
                    crawl_success=False,
                    error_message=result.error_message
                )
                await engine.content_indexer.index_url(url_record)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            error_msg = str(e).lower()
            if engine.stop_requested and ("browser has been closed" in error_msg or "context" in error_msg):
                break
            
            engine.queue_manager.mark_failed(item.url)
            if engine.on_error:
                engine.on_error(item.url, e)


async def asset_download_worker(engine, worker_id: int):
    """Asset download worker decoupled from CrawlerEngine."""
    while engine.is_running and not engine.stop_requested:
        if engine.is_paused:
            await asyncio.sleep(1)
            continue
        
        asset = await engine.queue_manager.get_next_asset(timeout=2.0)
        if not asset:
            continue
        
        asset_url = asset.get("url")
        asset_type = asset.get("type", "other")
        parent_url = asset.get("parent")
        
        await engine.rate_limiter.acquire(engine.config.domain)
        
        try:
            result = await engine.asset_downloader.download(asset_url)
            
            if result.success:
                engine.assets_downloaded += 1

                from src.storage.filesystem_storage import FilesystemStorage
                storage = FilesystemStorage()
                local_path = await storage.save_asset(
                    engine.job.job_id,
                    engine.config.domain,
                    asset_url,
                    result.content,
                    asset_type
                )

                asset_record = AssetRecord(
                    url=asset_url,
                    domain=engine.config.domain,
                    job_id=engine.job.job_id,
                    link_type="asset",
                    source_url=parent_url,
                    asset_type=asset_type,
                    http_status=result.status_code,
                    content_type=result.content_type,
                    file_size=len(result.content),
                    crawl_success=True,
                    download_success=True,
                    local_path=str(local_path) if local_path else None
                )
                await engine.content_indexer.index_asset(asset_record)
            else:
                asset_record = AssetRecord(
                    url=asset_url,
                    domain=engine.config.domain,
                    job_id=engine.job.job_id,
                    link_type="asset",
                    source_url=parent_url,
                    asset_type=asset_type,
                    crawl_success=False,
                    download_success=False,
                    error_message=result.error_message
                )
                await engine.content_indexer.index_asset(asset_record)
            
        except Exception as e:
            if engine.on_error:
                engine.on_error(asset_url, e)


async def progress_reporter(engine):
    """Report progress periodically decoupled from CrawlerEngine."""
    while engine.is_running and not engine.stop_requested:
        await asyncio.sleep(5)
        stats = engine._get_stats()
        await engine.job_repo.update_job_progress(
            engine.job.job_id,
            pages_crawled=stats["visited_urls"],
            assets_downloaded=engine.assets_downloaded,
            queue_remaining=stats["crawl_queue_remaining"],
            failed_urls=stats["failed_urls"]
        )
        if engine.on_progress:
            engine.on_progress(stats)
