import shutil
from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import ValidationError

from src.core.settings import get_settings
from src.ui.dependencies import get_crawl_manager, UISettings

router = APIRouter()

@router.post("/start")
async def start_crawl(
    request: Request,
    domain: str = Form(...),
    project_name: str = Form(""),
    entry_url: str = Form(""),
    max_depth: int = Form(3),
    max_pages: str = Form(""),
    concurrent_requests: int = Form(20),
    rate_limit_per_domain: int = Form(10),
    allow_subdomains: bool = Form(False),
    allowed_external_sites: str = Form(""),
    exclude_patterns: str = Form(""),
    include_patterns: str = Form(""),
    save_options: str = Form("full_mirror"),
    crawl_mode: str = Form("queue_and_sitemap"),
    save_images: bool = Form(False),
    save_videos: bool = Form(False),
    save_pdfs: bool = Form(False),
    save_css: bool = Form(False),
    save_js: bool = Form(False),
    save_icons: bool = Form(False),
    save_fonts: bool = Form(False),
    timeout_for_htmls: int = Form(30000),
    timeout_for_assets: int = Form(60000),
    fast_mode: bool = Form(False),
    verify_domain: bool = Form(False),
    verification_email: str = Form(""),
    verification_token: str = Form(""),
    sitemap_urls: str = Form(""),
    orphan_urls: str = Form(""),
    upload_urls: str = Form(""),
    upload_orphan_urls: str = Form(""),
    auth_login_url: str = Form(""),
    auth_username: str = Form(""),
    auth_password: str = Form(""),
    auth_interactive: bool = Form(False),
    auth_wait_seconds: int = Form(120),
    auth_post_login_url: str = Form(""),
    auth_trigger_selector: str = Form(""),
    auth_username_selector: str = Form(""),
    auth_password_selector: str = Form(""),
    auth_submit_selector: str = Form(""),
):
    """Start a new crawl job from form submission."""
    try:
        max_pages_int = int(max_pages) if max_pages.strip() else None
        
        # Validation: SITEMAP_ONLY mode requires sitemap_url or uploaded file
        if crawl_mode == "sitemap_only":
            has_sitemap = bool(sitemap_urls and sitemap_urls.strip())
            has_upload = bool(upload_urls and upload_urls.strip() and upload_urls != "[]")
            if not has_sitemap and not has_upload:
                return RedirectResponse(
                    url="/?error=SITEMAP_ONLY mode requires either a sitemap URL or an uploaded URL file",
                    status_code=303
                )
        
        settings = UISettings(
            domain=domain.strip(),
            project_name=project_name.strip() or None,
            entry_url=entry_url.strip() or None,
            max_depth=max_depth,
            max_pages=max_pages_int,
            concurrent_requests=concurrent_requests,
            rate_limit_per_domain=rate_limit_per_domain,
            allow_subdomains=allow_subdomains,
            allowed_external_sites=allowed_external_sites,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            save_options=save_options,
            crawl_mode=crawl_mode,
            save_images=save_images,
            save_videos=save_videos,
            save_pdfs=save_pdfs,
            save_css=save_css,
            save_js=save_js,
            save_icons=save_icons,
            save_fonts=save_fonts,
            timeout_for_htmls=timeout_for_htmls,
            timeout_for_assets=timeout_for_assets,
            fast_mode=fast_mode,
            verify_domain=verify_domain,
            verification_email=verification_email or None,
            verification_token=verification_token or None,
            sitemap_urls=sitemap_urls,
            orphan_urls=orphan_urls,
            upload_urls=upload_urls,
            upload_orphan_urls=upload_orphan_urls,
            auth_login_url=auth_login_url.strip() or None,
            auth_username=auth_username.strip() or None,
            auth_password=auth_password.strip() or None,
            auth_interactive=auth_interactive,
            auth_wait_seconds=auth_wait_seconds,
            auth_post_login_url=auth_post_login_url.strip() or None,
            auth_trigger_selector=auth_trigger_selector.strip() or None,
            auth_username_selector=auth_username_selector.strip() or None,
            auth_password_selector=auth_password_selector.strip() or None,
            auth_submit_selector=auth_submit_selector.strip() or None,
        )
    except ValidationError as exc:
        errors = ", ".join([f"{err['loc']}: {err['msg']}" for err in exc.errors()])
        return RedirectResponse(url=f"/?error={errors}", status_code=303)
    except Exception as exc:
        return RedirectResponse(url=f"/?error={str(exc)}", status_code=303)
    
    try:
        manager = get_crawl_manager()
        config = settings.to_crawl_config()
        job = await manager.create_and_start_job(config)
        
        message = f"Crawl job started for {domain}. Job ID: {job.job_id}"
        return RedirectResponse(url=f"/?message={message}", status_code=303)
    except Exception as exc:
        return RedirectResponse(url=f"/?error={str(exc)}", status_code=303)


@router.post("/job/{job_id}/stop")
async def stop_job(job_id: str):
    """Stop a running job."""
    manager = get_crawl_manager()
    try:
        success = await manager.stop_job(job_id)
        message = "Job stopped successfully" if success else "Job not found or not running"
    except Exception as exc:
        message = f"Error: {str(exc)}"
    return RedirectResponse(url=f"/job/{job_id}?message={message}", status_code=303)


@router.post("/job/{job_id}/pause")
async def pause_job(job_id: str):
    """Pause a running job."""
    manager = get_crawl_manager()
    try:
        success = await manager.pause_job(job_id)
        message = "Job paused" if success else "Job not found or not running"
    except Exception as exc:
        message = f"Error: {str(exc)}"
    return RedirectResponse(url=f"/job/{job_id}?message={message}", status_code=303)


@router.post("/job/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a paused job."""
    manager = get_crawl_manager()
    try:
        success = await manager.resume_job(job_id)
        message = "Job resumed" if success else "Job not found or not paused"
    except Exception as exc:
        message = f"Error: {str(exc)}"
    return RedirectResponse(url=f"/job/{job_id}?message={message}", status_code=303)


@router.post("/job/{job_id}/retry")
async def retry_job(job_id: str):
    """Retry a failed or stopped job with the same configuration."""
    manager = get_crawl_manager()
    try:
        old_job = await manager.get_job(job_id)
        if not old_job:
            return RedirectResponse(url=f"/job/{job_id}?error=Job not found", status_code=303)
        if old_job.status.value in ['running', 'pending']:
            return RedirectResponse(url=f"/job/{job_id}?error=Cannot retry a running or pending job", status_code=303)
        
        # Safety: don't delete data if another job for this domain is currently running
        if manager.is_domain_running(old_job.domain):
            return RedirectResponse(
                url=f"/job/{job_id}?error=Cannot retry: another crawl for {old_job.domain} is currently running",
                status_code=303,
            )

        # Use project_name for folder resolution (consistent with crawl manager)
        project_name = old_job.config.project_name or old_job.domain
        domain_folder = project_name.replace(".", "_").replace("/", "_").replace("\\", "_")
        settings = get_settings()
        for folder in [settings.analyses_dir, settings.server_dir]:
            target = folder / domain_folder
            if target.exists():
                shutil.rmtree(target)
                print(f"[Retry] Cleaned {target}")
        
        new_job = await manager.create_and_start_job(old_job.config)
        message = f"Job retried successfully. New Job ID: {new_job.job_id}"
        return RedirectResponse(url=f"/job/{new_job.job_id}?message={message}", status_code=303)
    except Exception as exc:
        return RedirectResponse(url=f"/job/{job_id}?error={str(exc)}", status_code=303)


@router.post("/job/{job_id}/rebuild-server")
async def rebuild_server_endpoint(job_id: str, background_tasks: BackgroundTasks):
    """Rebuild server folder from existing HTML files for a job."""
    manager = get_crawl_manager()
    try:
        async def do_rebuild():
            result = await manager.rebuild_server(job_id, force=True)
            print(f"[Rebuild Server] Job {job_id}: {result}")
        background_tasks.add_task(do_rebuild)
        return RedirectResponse(
            url=f"/job/{job_id}?message=Server rebuild started. This may take a few moments. Refresh the page to see results.",
            status_code=303
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/job/{job_id}?error=Failed to start server rebuild: {str(exc)}",
            status_code=303
        )


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job."""
    manager = get_crawl_manager()
    try:
        success = await manager.delete_job(job_id)
        if success:
            return JSONResponse({"message": "Job deleted"})
        else:
            return JSONResponse({"error": "Failed to delete job"}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
