from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.models import JobStatus
from src.ui.dependencies import get_crawl_manager, templates

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, message: Optional[str] = None, error: Optional[str] = None):
    """Main page with configuration form."""
    manager = get_crawl_manager()
    try:
        recent_jobs = await manager.list_jobs(limit=10)
    except Exception:
        recent_jobs = []
    
    capacity = manager.get_capacity()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "message": message,
        "error": error,
        "recent_jobs": recent_jobs,
        "capacity": capacity,
    })


@router.get("/jobs", response_class=HTMLResponse)
async def list_jobs(
    request: Request,
    page: int = 1,
    per_page: int = 25,
    domain: str = "",
    month: str = "",
    status: str = ""
):
    """List all crawl jobs with pagination and filtering."""
    manager = get_crawl_manager()
    valid_per_page = [25, 50, 75, 100]
    if per_page not in valid_per_page:
        per_page = 25
    skip = (page - 1) * per_page
    status_filter = None
    if status:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            status_filter = None

    try:
        jobs = await manager.list_jobs(
            status=status_filter, limit=per_page, skip=skip,
            domain=domain if domain else None, month=month if month else None
        )
        total = await manager.count_jobs(
            status=status_filter, domain=domain if domain else None,
            month=month if month else None
        )
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    except Exception as exc:
        return templates.TemplateResponse("index.html", {"request": request, "error": str(exc), "recent_jobs": []})

    available_months = []
    try:
        all_jobs = await manager.list_jobs(limit=1000)
        months_set = set()
        for job in all_jobs:
            if job.created_at:
                month_key = job.created_at.strftime("%Y-%m")
                months_set.add((month_key, job.created_at.strftime("%B %Y")))
        available_months = sorted(list(months_set), reverse=True)
    except Exception:
        pass

    return templates.TemplateResponse("jobs.html", {
        "request": request, "jobs": jobs, "page": page, "per_page": per_page,
        "total": total, "total_pages": total_pages, "domain": domain,
        "month": month, "status": status, "available_months": available_months,
    })


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    """Show job details and progress."""
    manager = get_crawl_manager()
    try:
        job = await manager.get_job(job_id)
        progress = await manager.get_job_progress(job_id)
    except Exception as exc:
        return templates.TemplateResponse("index.html", {"request": request, "error": str(exc), "recent_jobs": []})
    
    if not job:
        return RedirectResponse(url="/?error=Job not found", status_code=303)
    
    return templates.TemplateResponse("job_detail.html", {"request": request, "job": job, "progress": progress})


@router.get("/job/{job_id}/browse", response_class=HTMLResponse)
async def job_browse_view(request: Request, job_id: str):
    """Render the folder-tree browser for a job's htmls and assets folders."""
    manager = get_crawl_manager()
    try:
        job = await manager.get_job(job_id)
    except Exception as exc:
        return templates.TemplateResponse("index.html", {"request": request, "error": str(exc), "recent_jobs": []})
    if not job:
        return RedirectResponse(url="/?error=Job not found", status_code=303)
    return templates.TemplateResponse("browse.html", {"request": request, "job": job})


@router.get("/job/{job_id}/analysis", response_class=HTMLResponse)
async def job_analysis_view(request: Request, job_id: str, file: str = ""):
    """View the analysis CSV data rendered as an HTML table."""
    manager = get_crawl_manager()
    try:
        job = await manager.get_job(job_id)
        if not job:
            return RedirectResponse(url="/?error=Job not found", status_code=303)

        # Use project-specific directory (flat structure)
        project_name = job.config.project_name or job.domain
        project_safe_name = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
        analysis_dir = manager.settings.analyses_dir / project_safe_name

        available_files = []
        if analysis_dir.exists():
            available_files = sorted([f.name for f in analysis_dir.glob("*.csv") if f.is_file()])

        if not file or file not in available_files:
            file = available_files[0] if available_files else ""

        csv_path = analysis_dir / file if file else None
        if csv_path and not csv_path.resolve().is_relative_to(analysis_dir.resolve()):
            error = "Invalid file path"
            csv_path = None
        else:
            error = None

        headers = []
        rows = []

        if csv_path and not csv_path.exists():
            error = f"Analysis file '{file}' has not been generated yet."
        elif csv_path:
            import csv
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                rows = list(reader)

        return templates.TemplateResponse("analysis.html", {
            "request": request, "job": job, "headers": headers, "rows": rows,
            "error": error, "current_file": file, "available_files": available_files
        })
        
    except Exception as exc:
        return templates.TemplateResponse("analysis.html", {
            "request": request, "job": {"job_id": job_id, "domain": "Unknown"},
            "error": str(exc), "rows": [], "headers": [], "current_file": file, "available_files": []
        })
