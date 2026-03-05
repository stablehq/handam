"""
Scheduler API endpoints for managing automated jobs
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

from ..scheduler.jobs import scheduler, get_job_info
from ..auth.dependencies import require_admin_or_above
from ..db.models import User

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs")
async def get_jobs(current_user: User = Depends(require_admin_or_above)):
    """
    Get list of all scheduled jobs

    Returns job ID, name, next run time, and trigger info
    """
    try:
        jobs = get_job_info()
        return {
            "total": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, current_user: User = Depends(require_admin_or_above)):
    """Get specific job details"""
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
async def run_job_manual(job_id: str, current_user: User = Depends(require_admin_or_above)):
    """
    Manually trigger a scheduled job

    Useful for testing or running jobs outside regular schedule
    """
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
async def pause_job(job_id: str, current_user: User = Depends(require_admin_or_above)):
    """Pause a scheduled job"""
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
async def resume_job(job_id: str, current_user: User = Depends(require_admin_or_above)):
    """Resume a paused job"""
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
async def shutdown_scheduler(current_user: User = Depends(require_admin_or_above)):
    """
    Shutdown the scheduler

    WARNING: This will stop all automated jobs
    """
    try:
        from ..scheduler.jobs import stop_scheduler
        stop_scheduler()
        return {
            "status": "shutdown",
            "message": "Scheduler has been stopped"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
