"""
Scheduler API endpoints for managing automated jobs
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.scheduler.jobs import scheduler, get_job_info
from app.auth.dependencies import require_admin_or_above, require_superadmin
from app.api.deps import get_tenant_scoped_db
from app.db.models import User, TemplateSchedule

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


def _verify_job_tenant_ownership(db: Session, job_id: str):
    """Verify template_schedule jobs belong to current tenant. Raises 404 if not."""
    if job_id.startswith("template_schedule_"):
        schedule_id_str = job_id.rsplit("_", 1)[-1]
        if schedule_id_str.isdigit():
            # Auto-filtered by tenant context — returns None for other tenants
            schedule = db.query(TemplateSchedule).filter(
                TemplateSchedule.id == int(schedule_id_str)
            ).first()
            if not schedule:
                raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")


@router.get("/jobs")
async def get_jobs(
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_tenant_scoped_db),
):
    """
    Get list of scheduled jobs (filtered by tenant for ADMIN users)

    SUPERADMIN sees all jobs. ADMIN sees only their tenant's template schedules + system jobs.
    """
    from app.db.models import UserRole
    try:
        jobs = get_job_info()
        if current_user.role == UserRole.SUPERADMIN:
            return {"total": len(jobs), "jobs": jobs}

        # ADMIN: filter template_schedule jobs to own tenant only
        own_schedule_ids = {
            s.id for s in db.query(TemplateSchedule.id).all()
        }
        filtered = []
        for job in jobs:
            job_id = job.get("id", "")
            if job_id.startswith("template_schedule_"):
                schedule_id_str = job_id.rsplit("_", 1)[-1]
                if schedule_id_str.isdigit() and int(schedule_id_str) in own_schedule_ids:
                    filtered.append(job)
            else:
                # System jobs (sync, daily_assign) — show to all admins
                filtered.append(job)
        return {"total": len(filtered), "jobs": filtered}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Get specific job details"""
    _verify_job_tenant_ownership(db, job_id)

    job = scheduler.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return {
        "id": job.id,
        "name": job.name,
        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        "trigger": str(job.trigger)
    }


@router.post("/jobs/{job_id}/run")
async def run_job_manual(
    job_id: str,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_tenant_scoped_db),
):
    """
    Manually trigger a scheduled job

    Useful for testing or running jobs outside regular schedule
    """
    _verify_job_tenant_ownership(db, job_id)

    job = scheduler.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        # Run job immediately (non-blocking)
        job.modify(next_run_time=None)
        scheduler.add_job(
            job.func,
            id=f"{job_id}_manual",
            name=f"{job.name} (Manual)",
            replace_existing=True
        )

        return {
            "job_id": job_id,
            "status": "triggered",
            "message": f"Job '{job_id}' has been triggered manually"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Pause a scheduled job"""
    _verify_job_tenant_ownership(db, job_id)

    job = scheduler.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        scheduler.pause_job(job_id)
        return {
            "job_id": job_id,
            "status": "paused"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Resume a paused job"""
    _verify_job_tenant_ownership(db, job_id)

    job = scheduler.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        scheduler.resume_job(job_id)
        return {
            "job_id": job_id,
            "status": "resumed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_scheduler_status(current_user: User = Depends(require_admin_or_above)):
    """Get overall scheduler status"""
    return {
        "running": scheduler.running,
        "state": scheduler.state,
        "job_count": len(scheduler.get_jobs())
    }


@router.post("/shutdown")
async def shutdown_scheduler(current_user: User = Depends(require_superadmin)):
    """
    Shutdown the scheduler

    WARNING: This will stop all automated jobs
    """
    try:
        from app.scheduler.jobs import stop_scheduler
        stop_scheduler()
        return {
            "status": "shutdown",
            "message": "Scheduler has been stopped"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
