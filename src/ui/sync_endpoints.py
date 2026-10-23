"""Sync crawler API endpoints — FastAPI router mounted at /api/sync.

Endpoints:
  POST /api/sync/crawl                   — Start a sync crawl job
  GET  /api/sync/job/{job_id}/status     — Poll job status from MongoDB
  POST /api/sync/job/{job_id}/stop       — Signal the crawl thread to stop
  GET  /api/sync/job/{job_id}/server-info — Return server directory info
"""

from typing import Iterator, Optional
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from src.core.models import CrawlJobConfig, JobStatus
from src.core.sync_crawl_manager import SyncCrawlManager
from src.ui.services.file_utils import iter_folder_zip, summarise_folder

router = APIRouter(prefix="/api/sync", tags=["sync-crawl"])

# Shared manager instance (created once, reused across requests)
_manager: Optional[SyncCrawlManager] = None


def get_manager() -> SyncCrawlManager:
    global _manager
    if _manager is None:
        _manager = SyncCrawlManager()
    return _manager


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SyncCrawlRequest(BaseModel):
    """Minimal request body for starting a sync crawl."""
    domain: str
    entry_url: Optional[str] = None
    max_depth: int = 3
    max_pages: Optional[int] = None
    allow_subdomains: bool = True
    allowed_external_sites: list[str] = []
    exclude_patterns: list[str] = []
    save_options: str = "full_mirror"
    timeout_for_htmls: int = 30000
    timeout_for_assets: int = 60000
    fast_mode: bool = False
    user_agent: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# File upload — parse CSV / XLSX / XML sitemap into a URL list
# ---------------------------------------------------------------------------

_ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".xml"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB hard limit


@router.post("/upload-urls")
async def upload_url_file(file: UploadFile = File(...)):
    """Parse an uploaded CSV, XLSX, or XML sitemap file and return the URL list.

    The returned JSON can be passed directly as ``upload_urls`` when calling
    ``POST /api/sync/crawl`` or submitted with the UI form.

    Response
    --------
    ``{ "urls": [...], "count": N, "filename": "...", "column_used": "..." }``

    Errors
    ------
    400  — unsupported file type or empty result
    413  — file exceeds 10 MB
    """
    from pathlib import Path as _Path
    from src.crawler.discovery.sitemap_parser import UploadedFileParser

    filename = file.filename or "upload"
    ext = _Path(filename).suffix.lower()

    if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_UPLOAD_EXTENSIONS))}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data) / 1024 / 1024:.1f} MB). Max 10 MB.",
        )

    try:
        parser = UploadedFileParser()
        urls = parser.parse_bytes(data, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Parse error: {exc}")

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No valid URLs found in the uploaded file. "
                   "Ensure the file has a column containing HTTP/HTTPS URLs.",
        )

    return {
        "urls": urls,
        "count": len(urls),
        "filename": filename,
    }


# ---------------------------------------------------------------------------
# Sitemap URL fetch — fetch and parse a remote sitemap URL into a URL list
# ---------------------------------------------------------------------------

class SitemapFetchRequest(BaseModel):
    sitemap_url: str


@router.post("/fetch-sitemap")
async def fetch_sitemap_url(req: SitemapFetchRequest):
    """Fetch a remote sitemap URL and return the parsed page URLs.

    Useful for the UI "add sitemap URL" flow — the frontend can preview the
    discovered URLs before starting the crawl.

    Response
    --------
    ``{ "urls": [...], "count": N, "sitemap_url": "..." }``
    """
    import asyncio
    from src.crawler.discovery.sitemap_parser import SitemapParser

    sitemap_url = req.sitemap_url.strip()
    if not sitemap_url.startswith("http"):
        raise HTTPException(status_code=400, detail="sitemap_url must start with http(s)://")

    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(
                sitemap_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; crawler/3.0)"},
            )
        resp.raise_for_status()
        content = resp.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch sitemap: {exc}")

    try:
        parser = SitemapParser()
        entries = parser.parse(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Sitemap parse error: {exc}")

    urls = [
        e["loc"] for e in entries
        if e.get("loc") and e.get("type") != "sitemap"
        and e["loc"].startswith("http")
    ]

    return {
        "urls": urls,
        "count": len(urls),
        "sitemap_url": sitemap_url,
    }


@router.post("/crawl")
async def start_sync_crawl(req: SyncCrawlRequest):
    """Start a synchronous Playwright crawl job."""
    try:
        config = CrawlJobConfig(
            domain=req.domain,
            entry_url=req.entry_url,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
            allow_subdomains=req.allow_subdomains,
            allowed_external_sites=req.allowed_external_sites,
            exclude_patterns=req.exclude_patterns,
            save_options=req.save_options,
            timeout_for_htmls=req.timeout_for_htmls,
            timeout_for_assets=req.timeout_for_assets,
            fast_mode=req.fast_mode,
            user_agent=req.user_agent,
        )

        manager = get_manager()
        job = await manager.create_and_start_job(config)

        return {
            "job_id": job.job_id,
            "domain": job.domain,
            "status": job.status.value,
            "stage": job.stage.value,
            "message": f"Sync crawl started for {job.domain}",
        }

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/job/{job_id}/status")
async def get_sync_job_status(job_id: str):
    """Return current job status and counters from MongoDB."""
    try:
        manager = get_manager()
        job = await manager.get_job(job_id)

        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        elapsed = None
        if job.started_at:
            from datetime import datetime
            end = job.completed_at or datetime.utcnow()
            elapsed = int((end - job.started_at).total_seconds())

        is_active = job_id in manager._stop_events

        return {
            "job_id": job.job_id,
            "domain": job.domain,
            "status": job.status.value,
            "stage": job.stage.value,
            "pages_crawled": job.pages_crawled,
            "failed_urls": job.failed_urls,
            "elapsed_seconds": elapsed,
            "is_active": is_active,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/job/{job_id}/stop")
async def stop_sync_job(job_id: str):
    """Send a stop signal to the running crawl thread."""
    try:
        manager = get_manager()
        stopped = await manager.stop_job(job_id)

        if stopped:
            return {"message": "Stop signal sent", "job_id": job_id}
        else:
            return {"message": "Job not active or already finished", "job_id": job_id}

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/job/{job_id}/server-info")
async def get_sync_server_info(job_id: str):
    """Return the server directory path and file count for a completed job."""
    try:
        manager = get_manager()
        info = await manager.get_server_info(job_id)

        if "error" in info:
            return JSONResponse(info, status_code=404)

        return info

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/job/{job_id}/analysis/{filename}")
async def get_sync_analysis_file(job_id: str, filename: str):
    """Serve a generated analysis CSV file."""
    try:
        manager = get_manager()
        job = await manager.get_job(job_id)

        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        # Security checks: ensure filename is safe
        if not filename.endswith('.csv') or '..' in filename or '/' in filename or '\\' in filename:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        # Use project-specific directory
        project_name = job.config.project_name or job.domain
        project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
        analysis_dir = manager.settings.analyses_dir / project_safe_name
        file_path = analysis_dir / filename

        # Ensure file is within the analysis directory (prevent directory traversal)
        if not file_path.resolve().is_relative_to(analysis_dir.resolve()):
            return JSONResponse({"error": "Invalid file path"}, status_code=400)

        if not file_path.exists():
            return JSONResponse({"error": "Analysis file not found. Wait for the job to complete."}, status_code=404)

        return FileResponse(
            path=str(file_path),
            filename=f"{job.domain}_{filename}",
            media_type="text/csv"
        )

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/job/{job_id}/serve/{file_path:path}")
async def serve_mirrored_site(job_id: str, file_path: str):
    """Serve the static mirrored website through FastAPI natively."""
    try:
        manager = get_manager()
        info = await manager.get_server_info(job_id)

        if "error" in info:
            return JSONResponse(info, status_code=404)

        server_dir = info.get("server_dir")
        if not server_dir or not Path(server_dir).exists():
            return JSONResponse({"error": "Server directory not found"}, status_code=404)

        base_dir = Path(server_dir).resolve()

        if not file_path:
            file_path = "index.html"

        target_path = (base_dir / file_path).resolve()

        if not target_path.is_relative_to(base_dir):
            return JSONResponse({"error": "Access denied"}, status_code=403)

        if target_path.is_dir():
            target_path = target_path / "index.html"

        if not target_path.exists() and not target_path.suffix:
            html_path = target_path.with_suffix(".html")
            if html_path.exists():
                target_path = html_path

        if not target_path.exists():
            return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)

        response = FileResponse(path=str(target_path))
        response.set_cookie(
            key="active_job_id",
            value=job_id,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Folder download (streaming ZIP)
# ---------------------------------------------------------------------------

async def _download_job_folder(job_id: str, kind: str, sub_path: str):
    """Resolve the target path and return either a streaming ZIP (folder) or a
    direct file download (single file)."""
    if kind not in ("htmls", "assets"):
        return JSONResponse(
            {"error": "kind must be 'htmls' or 'assets'"}, status_code=400
        )

    manager = get_manager()
    try:
        job = await manager.get_job(job_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    # Use project-specific directories (flat structure)
    project_name = job.config.project_name or job.domain
    project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
    
    if kind == "htmls":
        root = manager.settings.html_dir / project_safe_name
    else:
        root = manager.settings.assets_dir / project_safe_name
    
    domain_root = root.resolve()
    if not domain_root.exists():
        return JSONResponse(
            {"error": f"No {kind} folder found for domain {job.domain}"},
            status_code=404,
        )

    target = (domain_root / sub_path).resolve() if sub_path else domain_root
    if not target.is_relative_to(domain_root):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    if not target.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)

    if target.is_file():
        return FileResponse(
            path=str(target),
            filename=target.name,
            headers={
                "Content-Disposition": f'attachment; filename="{target.name}"',
            },
        )

    if not target.is_dir():
        return JSONResponse({"error": "Unsupported target type"}, status_code=400)

    arc_root = target.name or project_safe_name
    if sub_path:
        zip_filename = f"{project_safe_name}-{kind}-{arc_root}.zip"
    else:
        zip_filename = f"{project_safe_name}-{kind}.zip"

    return StreamingResponse(
        iter_folder_zip(target, arc_root),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/job/{job_id}/download/{kind}")
async def download_job_folder_root(job_id: str, kind: str):
    """Download the whole htmls or assets folder for a job (ZIP stream)."""
    return await _download_job_folder(job_id, kind, "")


@router.get("/job/{job_id}/download/{kind}/{sub_path:path}")
async def download_job_subfolder(job_id: str, kind: str, sub_path: str):
    """Download any subfolder of htmls/<domain>/ or assets/<domain>/ (ZIP stream)."""
    return await _download_job_folder(job_id, kind, sub_path)


# ---------------------------------------------------------------------------
# Folder browsing (single-level tree listing for UI)
# ---------------------------------------------------------------------------

async def _browse_job_folder(job_id: str, kind: str, sub_path: str):
    """Return a single-level listing (folders + files) of a job's htmls/assets tree."""
    if kind not in ("htmls", "assets"):
        return JSONResponse(
            {"error": "kind must be 'htmls' or 'assets'"}, status_code=400
        )

    manager = get_manager()
    try:
        job = await manager.get_job(job_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    # Use project-specific directories (flat structure)
    project_name = job.config.project_name or job.domain
    project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
    
    if kind == "htmls":
        root = manager.settings.html_dir / project_safe_name
    else:
        root = manager.settings.assets_dir / project_safe_name
    
    domain_root = root.resolve()
    if not domain_root.exists():
        return JSONResponse(
            {"error": f"No {kind} folder found for domain {job.domain}"},
            status_code=404,
        )

    target = (domain_root / sub_path).resolve() if sub_path else domain_root
    if not target.is_relative_to(domain_root):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    if not target.exists() or not target.is_dir():
        return JSONResponse({"error": "Folder not found"}, status_code=404)

    folders = []
    files = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    rel_base = target.relative_to(domain_root).as_posix()
    rel_base = "" if rel_base == "." else rel_base

    for entry in entries:
        rel_path = f"{rel_base}/{entry.name}" if rel_base else entry.name
        if entry.is_dir():
            summary = summarise_folder(entry)
            folders.append(
                {
                    "name": entry.name,
                    "path": rel_path,
                    "file_count": summary["file_count"],
                    "total_size": summary["total_size"],
                }
            )
        elif entry.is_file():
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            files.append({"name": entry.name, "path": rel_path, "size": size})

    return {
        "job_id": job_id,
        "domain": job.domain,
        "kind": kind,
        "path": rel_base,
        "folders": folders,
        "files": files,
    }


@router.get("/job/{job_id}/browse/{kind}")
async def browse_job_folder_root(job_id: str, kind: str):
    """List top-level entries of the htmls or assets folder for a job."""
    return await _browse_job_folder(job_id, kind, "")


@router.get("/job/{job_id}/browse/{kind}/{sub_path:path}")
async def browse_job_subfolder(job_id: str, kind: str, sub_path: str):
    """List entries of any subfolder under htmls/<domain>/ or assets/<domain>/."""
    return await _browse_job_folder(job_id, kind, sub_path)
