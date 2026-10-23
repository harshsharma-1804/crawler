"""FastAPI routes for reports."""
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse

from src.core.models import CrawlReport
from src.reporting.report_builder import ReportBuilder, AssetStatistics, FailureReport
from src.storage.csv_writer import CSVWriter
from src.storage.filesystem_storage import FilesystemStorage


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{job_id}/summary")
async def get_report_summary(job_id: str):
    """Get crawl report summary."""
    report_builder = ReportBuilder()
    
    try:
        report = await report_builder.generate_full_report(job_id)
        return {
            "job_id": report.job_id,
            "domain": report.domain,
            "status": report.status.value,
            "stage": report.stage.value,
            "created_at": report.created_at.isoformat(),
            "completed_at": report.completed_at.isoformat() if report.completed_at else None,
            "duration_seconds": report.duration_seconds,
            "total_urls": report.total_urls,
            "successful_urls": report.successful_urls,
            "failed_urls": report.failed_urls,
            "external_urls": report.external_urls,
            "assets_by_type": report.assets_by_type,
            "assets_downloaded": report.assets_downloaded,
            "assets_failed": report.assets_failed,
            "html_files_count": report.html_files_count,
            "total_storage_mb": report.total_storage_mb,
            "reports_available": report.reports_available
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{job_id}/generate")
async def generate_reports(job_id: str):
    """Generate all CSV reports for job."""
    report_builder = ReportBuilder()
    
    try:
        reports = await report_builder.generate_csv_reports(job_id)
        
        return {
            "job_id": job_id,
            "reports_generated": {
                name: str(path) for name, path in reports.items()
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{job_id}/download/{report_type}")
async def download_report(job_id: str, report_type: str):
    """Download specific report CSV."""
    valid_types = ["combined", "urls", "failed_urls", "assets"]
    
    if report_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid report type. Valid types: {', '.join(valid_types)}"
        )
    
    report_builder = ReportBuilder()
    
    try:
        report_path = await report_builder.get_report_path(job_id, report_type)
        
        if not report_path:
            raise HTTPException(status_code=404, detail="Report not found")
        
        return FileResponse(
            path=report_path,
            media_type="text/csv",
            filename=f"{job_id}_{report_type}.csv"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{job_id}/assets")
async def get_asset_statistics(job_id: str):
    """Get asset download statistics."""
    asset_stats = AssetStatistics()
    
    stats = await asset_stats.generate(job_id)
    return stats


@router.get("/{job_id}/failures")
async def get_failure_report(job_id: str):
    """Get failure analysis report."""
    failure_report = FailureReport()
    
    report = await failure_report.generate(job_id)
    return report


@router.get("/{job_id}/storage")
async def get_storage_stats(job_id: str):
    """Get storage statistics for job."""
    from src.database.job_repository import JobRepository
    
    job_repo = JobRepository()
    job = await job_repo.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    storage = FilesystemStorage()
    stats = await storage.get_storage_stats(job.domain)
    
    return {
        "job_id": job_id,
        "domain": job.domain,
        **stats
    }


@router.get("/{job_id}/urls")
async def get_crawled_urls(
    job_id: str,
    success_only: bool = Query(False, description="Only return successfully crawled URLs"),
    limit: int = Query(1000, ge=1, le=10000)
):
    """Get list of crawled URLs."""
    from src.database.content_indexer import ContentIndexer
    
    indexer = ContentIndexer()
    urls = await indexer.get_urls_by_job(job_id, success_only)
    
    # Apply limit
    urls = urls[:limit]
    
    return {
        "job_id": job_id,
        "total": len(urls),
        "urls": [
            {
                "url": u.url,
                "status": u.http_status,
                "title": u.title,
                "depth": u.depth,
                "discovery_type": u.discovery_type.value if hasattr(u.discovery_type, 'value') else str(u.discovery_type),
                "crawl_success": u.crawl_success,
                "file_size": u.file_size,
                "local_path": u.local_path
            }
            for u in urls
        ]
    }


@router.get("/{job_id}/content/{content_type}")
async def get_content_by_type(
    job_id: str,
    content_type: str = Query(..., description="Type: html, images, links"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get extracted content by type."""
    from src.database.content_indexer import ContentIndexer
    
    indexer = ContentIndexer()
    
    if content_type == "html":
        content = await indexer.get_html_content_by_job(job_id, limit)
        return {
            "job_id": job_id,
            "content_type": content_type,
            "total": len(content),
            "content": [
                {
                    "url": c.url,
                    "title": c.title,
                    "headings": c.headings,
                    "content_length": len(c.content)
                }
                for c in content
            ]
        }
    
    elif content_type == "images":
        assets = await indexer.get_assets_by_job(job_id, "image")
        return {
            "job_id": job_id,
            "content_type": content_type,
            "total": len(assets),
            "images": [
                {
                    "url": a.url,
                    "source_url": a.source_url,
                    "file_size": a.file_size,
                    "download_success": a.download_success,
                    "local_path": a.local_path
                }
                for a in assets[:limit]
            ]
        }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {content_type}")
