from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse

from src.core.settings import get_settings
from src.ui.dependencies import get_crawl_manager

router = APIRouter()

@router.get("/api/capacity")
async def api_capacity():
    """Return current parallel job capacity info."""
    manager = get_crawl_manager()
    return manager.get_capacity()


@router.get("/api/jobs")
async def api_list_jobs(
    page: int = 1,
    per_page: int = 100,
    domain: str = "",
    month: str = ""
):
    """API endpoint to list jobs with pagination and filtering."""
    manager = get_crawl_manager()
    skip = (page - 1) * per_page
    try:
        jobs = await manager.list_jobs(
            limit=per_page, skip=skip,
            domain=domain if domain else None, month=month if month else None
        )
        total = await manager.count_jobs(
            domain=domain if domain else None, month=month if month else None
        )
        return {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "domain": j.domain,
                    "status": j.status.value,
                    "stage": j.stage.value,
                    "pages_crawled": j.pages_crawled,
                    "assets_downloaded": j.assets_downloaded,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page if total > 0 else 1
            }
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/job/{job_id}/status")
async def api_job_status(job_id: str):
    """API endpoint to get job status."""
    manager = get_crawl_manager()
    try:
        progress = await manager.get_job_progress(job_id)
        if not progress:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        return {
            "job_id": progress.job_id,
            "status": progress.status.value,
            "stage": progress.stage.value,
            "progress_percent": progress.progress_percent,
            "pages_crawled": progress.pages_crawled,
            "assets_downloaded": progress.assets_downloaded,
            "queue_remaining": progress.queue_remaining,
            "failed_urls": progress.failed_urls,
            "elapsed_seconds": progress.elapsed_seconds,
            "message": progress.message,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/upload-url-list")
async def upload_url_list(file: UploadFile = File(...)):
    """Parse a CSV, Excel, or XML sitemap file and return the extracted URLs."""
    import pandas as pd

    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx", ".xls", ".xml")):
        return JSONResponse({"error": "Unsupported file type. Please upload a .csv, .xlsx, or .xml sitemap file."}, status_code=400)

    try:
        contents = await file.read()
        settings = get_settings()
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = settings.uploads_dir / file.filename
        tmp_path.write_bytes(contents)

        urls = []
        column_used = "url"

        if filename.endswith(".xml"):
            # Parse XML sitemap
            from src.crawler.discovery.sitemap_parser import SitemapParser
            parser = SitemapParser()
            xml_content = tmp_path.read_text(encoding="utf-8", errors="replace")
            entries = parser.parse(xml_content)
            
            for entry in entries:
                loc = entry.get("loc", "").strip()
                if loc and (loc.startswith("http://") or loc.startswith("https://")):
                    urls.append(loc)
            
            column_used = "sitemap_xml"
        elif filename.endswith(".csv"):
            df = pd.read_csv(tmp_path, dtype=str)
            
            if df.empty:
                return JSONResponse({"error": "The uploaded file is empty."}, status_code=400)

            url_column = None
            for col in df.columns:
                if col.strip().lower() in ("url", "urls", "link", "links", "href", "address", "page_url", "page url"):
                    url_column = col
                    break

            if url_column is None:
                url_column = df.columns[0]

            raw_urls = df[url_column].dropna().astype(str).str.strip().tolist()
            urls = [u for u in raw_urls if u.startswith("http://") or u.startswith("https://")]
            column_used = url_column
        else:
            # Excel file
            df = pd.read_excel(tmp_path, dtype=str, engine="openpyxl")
            
            if df.empty:
                return JSONResponse({"error": "The uploaded file is empty."}, status_code=400)

            url_column = None
            for col in df.columns:
                if col.strip().lower() in ("url", "urls", "link", "links", "href", "address", "page_url", "page url"):
                    url_column = col
                    break

            if url_column is None:
                url_column = df.columns[0]

            raw_urls = df[url_column].dropna().astype(str).str.strip().tolist()
            urls = [u for u in raw_urls if u.startswith("http://") or u.startswith("https://")]
            column_used = url_column

        try:
            tmp_path.unlink()
        except Exception:
            pass

        if not urls:
            return JSONResponse({"error": f"No valid URLs found. URLs must start with http:// or https://."}, status_code=400)

        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        return {"urls": unique_urls, "count": len(unique_urls), "column_used": column_used}
    except Exception as exc:
        return JSONResponse({"error": f"Failed to parse file: {str(exc)}"}, status_code=500)
