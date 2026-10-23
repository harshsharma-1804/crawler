"""Report builder for generating crawl reports."""
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.core.models import CrawlJob, URLRecord, AssetRecord, CrawlReport
from src.core.settings import get_settings
from src.database.job_repository import JobRepository
from src.database.content_indexer import ContentIndexer
from src.storage.filesystem_storage import FilesystemStorage
from src.storage.csv_writer import CSVWriter


class ReportBuilder:
    """Build comprehensive crawl reports."""
    
    def __init__(self):
        self.settings = get_settings()
        self.job_repo = JobRepository()
        self.content_indexer = ContentIndexer()
        self.storage = FilesystemStorage()
        self.csv_writer = CSVWriter()
    
    async def generate_full_report(self, job_id: str) -> CrawlReport:
        """Generate full crawl report."""
        job = await self.job_repo.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        # Get all URLs
        urls = await self.content_indexer.get_urls_by_job(job_id)
        assets = await self.content_indexer.get_assets_by_job(job_id)
        
        # Calculate statistics
        successful_urls = [u for u in urls if u.crawl_success]
        failed_urls = [u for u in urls if not u.crawl_success]
        external_urls = [u for u in urls if u.link_type == "external"]
        
        # Assets by type
        assets_by_type = {}
        for asset in assets:
            asset_type = asset.asset_type.value if hasattr(asset.asset_type, 'value') else str(asset.asset_type)
            assets_by_type[asset_type] = assets_by_type.get(asset_type, 0) + 1
        
        downloaded_assets = [a for a in assets if a.download_success]
        failed_assets = [a for a in assets if not a.download_success]
        
        # Storage stats
        storage_stats = await self.storage.get_storage_stats(job.domain)
        
        # Calculate duration
        duration = None
        if job.completed_at and job.started_at:
            duration = int((job.completed_at - job.started_at).total_seconds())
        
        # Check which reports are available
        reports_available = self._check_available_reports(job.domain)
        
        return CrawlReport(
            job_id=job_id,
            domain=job.domain,
            status=job.status,
            stage=job.stage,
            created_at=job.created_at,
            completed_at=job.completed_at,
            duration_seconds=duration,
            total_urls=len(urls),
            successful_urls=len(successful_urls),
            failed_urls=len(failed_urls),
            external_urls=len(external_urls),
            assets_by_type=assets_by_type,
            assets_downloaded=len(downloaded_assets),
            assets_failed=len(failed_assets),
            html_files_count=storage_stats.get("html_files", 0),
            total_storage_mb=storage_stats.get("html_size_mb", 0) + storage_stats.get("total_asset_size_mb", 0),
            reports_available=reports_available
        )
    
    async def generate_csv_reports(self, job_id: str) -> Dict[str, Path]:
        """Generate all CSV reports."""
        job = await self.job_repo.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        domain = job.domain
        
        # Get data
        urls = await self.content_indexer.get_urls_by_job(job_id)
        assets = await self.content_indexer.get_assets_by_job(job_id)
        
        # Prepare records
        url_records = self._prepare_url_records(urls)
        failed_url_records = [r for r in url_records if r.get("http_status") and r.get("http_status") >= 400]
        asset_records = self._prepare_asset_records(assets)
        
        # Write CSVs
        reports = {}
        
        # Combined report
        combined = url_records + asset_records
        reports["combined"] = await self.csv_writer.write_combined_report(
            job_id, domain, combined
        )
        
        # URLs report
        reports["urls"] = await self.csv_writer.write_urls_csv(
            job_id, domain, url_records
        )
        
        # Failed URLs report
        reports["failed_urls"] = await self.csv_writer.write_failed_urls_csv(
            job_id, domain, failed_url_records
        )
        
        # Assets report
        reports["assets"] = await self.csv_writer.write_assets_csv(
            job_id, domain, asset_records
        )
        
        return reports
    
    def _prepare_url_records(self, urls: List[URLRecord]) -> List[Dict]:
        """Prepare URL records for CSV."""
        records = []
        for url in urls:
            records.append({
                "url": url.url,
                "link_type": url.link_type,
                "source_url": url.source_url or "",
                "redirect_url": url.redirect_url or "",
                "http_status": url.http_status or 0,
                "message": url.error_message or ("OK" if url.crawl_success else "Failed"),
                "file_size": url.file_size or 0,
                "file_type": url.file_type or "",
                "depth": url.depth,
                "discovery_type": url.discovery_type.value if hasattr(url.discovery_type, 'value') else str(url.discovery_type),
                "crawl_success": url.crawl_success,
                "local_path": url.local_path or ""
            })
        return records
    
    def _prepare_asset_records(self, assets: List[AssetRecord]) -> List[Dict]:
        """Prepare asset records for CSV."""
        records = []
        for asset in assets:
            records.append({
                "url": asset.url,
                "link_type": "asset",
                "source_url": asset.source_url or "",
                "redirect_url": asset.redirect_url or "",
                "http_status": asset.http_status or 0,
                "message": asset.error_message or ("Downloaded" if asset.download_success else "Failed"),
                "file_size": asset.file_size or 0,
                "file_type": asset.file_type or "",
                "asset_type": asset.asset_type.value if hasattr(asset.asset_type, 'value') else str(asset.asset_type),
                "download_success": asset.download_success,
                "local_path": asset.local_path or ""
            })
        return records
    
    def _check_available_reports(self, domain: str) -> List[str]:
        """Check which reports exist on disk."""
        reports = []
        domain_dir = self.settings.analyses_dir / domain
        
        if not domain_dir.exists():
            return reports
        
        report_files = {
            "combine_report.csv": "combined",
            "urls.csv": "urls",
            "failed_urls.csv": "failed_urls",
            "assets_status.csv": "assets"
        }
        
        for filename, report_name in report_files.items():
            if (domain_dir / filename).exists():
                reports.append(report_name)
        
        return reports
    
    async def get_report_path(self, job_id: str, report_type: str) -> Optional[Path]:
        """Get path to specific report."""
        job = await self.job_repo.get_job(job_id)
        if not job:
            return None
        
        domain = job.domain
        
        report_files = {
            "combined": "combine_report.csv",
            "urls": "urls.csv",
            "failed_urls": "failed_urls.csv",
            "assets": "assets_status.csv"
        }
        
        filename = report_files.get(report_type)
        if not filename:
            return None
        
        report_path = self.settings.analyses_dir / domain / filename
        
        if report_path.exists():
            return report_path
        
        return None


class AssetStatistics:
    """Generate asset statistics."""
    
    def __init__(self):
        self.content_indexer = ContentIndexer()
    
    async def generate(self, job_id: str) -> Dict:
        """Generate asset statistics."""
        assets = await self.content_indexer.get_assets_by_job(job_id)
        
        stats = {
            "total": len(assets),
            "downloaded": 0,
            "failed": 0,
            "by_type": {},
            "by_status": {},
            "size_distribution": {
                "0-10KB": 0,
                "10KB-100KB": 0,
                "100KB-1MB": 0,
                "1MB+": 0
            }
        }
        
        for asset in assets:
            # Count by type
            asset_type = asset.asset_type.value if hasattr(asset.asset_type, 'value') else str(asset.asset_type)
            stats["by_type"][asset_type] = stats["by_type"].get(asset_type, 0) + 1
            
            # Count by status
            status = "downloaded" if asset.download_success else "failed"
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            
            if asset.download_success:
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1
            
            # Size distribution
            size = asset.file_size or 0
            if size < 10 * 1024:
                stats["size_distribution"]["0-10KB"] += 1
            elif size < 100 * 1024:
                stats["size_distribution"]["10KB-100KB"] += 1
            elif size < 1024 * 1024:
                stats["size_distribution"]["100KB-1MB"] += 1
            else:
                stats["size_distribution"]["1MB+"] += 1
        
        return stats


class FailureReport:
    """Generate failure analysis report."""
    
    def __init__(self):
        self.content_indexer = ContentIndexer()
    
    async def generate(self, job_id: str) -> Dict:
        """Generate failure analysis."""
        urls = await self.content_indexer.get_urls_by_job(job_id)
        assets = await self.content_indexer.get_assets_by_job(job_id)
        
        failed_urls = [u for u in urls if not u.crawl_success]
        failed_assets = [a for a in assets if not a.download_success]
        
        report = {
            "total_failures": len(failed_urls) + len(failed_assets),
            "url_failures": {
                "count": len(failed_urls),
                "by_status_code": {},
                "by_error": {},
                "samples": []
            },
            "asset_failures": {
                "count": len(failed_assets),
                "by_type": {},
                "by_error": {},
                "samples": []
            }
        }
        
        # Analyze URL failures
        for url in failed_urls:
            status = url.http_status or 0
            report["url_failures"]["by_status_code"][status] = \
                report["url_failures"]["by_status_code"].get(status, 0) + 1
            
            error = url.error_message or "Unknown error"
            report["url_failures"]["by_error"][error] = \
                report["url_failures"]["by_error"].get(error, 0) + 1
        
        # Add URL failure samples (up to 10)
        for url in failed_urls[:10]:
            report["url_failures"]["samples"].append({
                "url": url.url,
                "error": url.error_message,
                "status_code": url.http_status
            })
        
        # Analyze asset failures
        for asset in failed_assets:
            asset_type = asset.asset_type.value if hasattr(asset.asset_type, 'value') else str(asset.asset_type)
            report["asset_failures"]["by_type"][asset_type] = \
                report["asset_failures"]["by_type"].get(asset_type, 0) + 1
            
            error = asset.error_message or "Unknown error"
            report["asset_failures"]["by_error"][error] = \
                report["asset_failures"]["by_error"].get(error, 0) + 1
        
        # Add asset failure samples (up to 10)
        for asset in failed_assets[:10]:
            report["asset_failures"]["samples"].append({
                "url": asset.url,
                "type": str(asset.asset_type),
                "error": asset.error_message
            })
        
        return report
