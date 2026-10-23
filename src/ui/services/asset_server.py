import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from src.core.settings import get_settings
from src.ui.dependencies import get_crawl_manager

router = APIRouter()

def _job_id_from_referer(referer: str) -> Optional[str]:
    """Extract job_id from a Referer URL of the form http(s)://host/api/sync/job/<job_id>/serve/..."""
    if not referer:
        return None
    try:
        parsed = urlparse(referer)
        path_parts = parsed.path.strip("/").split("/")
        if "job" in path_parts and "serve" in path_parts:
            job_idx = path_parts.index("job")
            if len(path_parts) > job_idx + 1:
                return path_parts[job_idx + 1]
    except Exception:
        pass
    return None


@router.get("/{file_path:path}")
async def serve_mirrored_assets_via_referer(request: Request, file_path: str):
    """
    Catch-all endpoint that serves assets and HTML pages for the offline mirror.
    Uses Referer header or active_job_id cookie to determine which job's files to serve.
    """
    job_id = None

    # Try to get job_id from Referer header first
    referer = request.headers.get("referer")
    if referer:
        job_id = _job_id_from_referer(referer)

    # Fallback to cookie if referer didn't work
    if not job_id:
        job_id = request.cookies.get("active_job_id")

    if not job_id:
        raise HTTPException(status_code=404, detail="Not Found - Unable to determine job_id from referer or cookie")

    manager = get_crawl_manager()
    job = await manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Not Found - Job not found")

    # Use project-specific directories (flat structure)
    project_name = job.config.project_name or job.domain
    project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
    settings = get_settings()

    # Try server folder first (priority for mirrored site assets)
    server_base = settings.server_dir / project_safe_name
    target_path = server_base / file_path
    
    found_path = None
    
    if target_path.is_file():
        found_path = target_path
    elif target_path.is_dir() and (target_path / "index.html").is_file():
        found_path = target_path / "index.html"
    
    if found_path:
        response = FileResponse(found_path)
        # Always refresh the cookie on HTML responses to maintain session
        if found_path.suffix == '.html' or found_path.name.endswith('.htm'):
            response.set_cookie(
                key="active_job_id",
                value=job_id,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response

    # Fallback to the raw assets folder if it hasn't been copied to the server folder yet
    assets_base = settings.assets_dir / project_safe_name
    asset_target_path = assets_base / file_path
    
    if asset_target_path.is_file():
        return FileResponse(asset_target_path)
    
    # Final fallback: try adding .html extension for HTML pages
    if not target_path.suffix:
        html_path = target_path.with_suffix('.html')
        if html_path.is_file():
            response = FileResponse(html_path)
            response.set_cookie(
                key="active_job_id",
                value=job_id,
                httponly=True,
                samesite="lax",
                path="/",
            )
            return response

    raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
