"""
Template Schedules API
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.db.database import get_db
from app.db.models import TemplateSchedule, MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.scheduler.schedule_manager import ScheduleManager
from app.scheduler.jobs import scheduler

router = APIRouter()


# Pydantic models
class TemplateScheduleCreate(BaseModel):
    template_id: int
    schedule_name: str
    schedule_type: str  # 'daily', 'weekly', 'hourly', 'interval'
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    timezone: str = "Asia/Seoul"
    target_type: str  # 'all', 'tag', 'room_assigned', 'party_only'
    target_value: Optional[str] = None
    date_filter: Optional[str] = None
    sms_type: str = 'room'
    exclude_sent: bool = True
    active: bool = True


class TemplateScheduleUpdate(BaseModel):
    template_id: Optional[int] = None
    schedule_name: Optional[str] = None
    schedule_type: Optional[str] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    timezone: Optional[str] = None
    target_type: Optional[str] = None
    target_value: Optional[str] = None
    date_filter: Optional[str] = None
    sms_type: Optional[str] = None
    exclude_sent: Optional[bool] = None
    active: Optional[bool] = None


class TemplateScheduleResponse(BaseModel):
    id: int
    template_id: int
    template_name: str
    template_key: str
    schedule_name: str
    schedule_type: str
    hour: Optional[int]
    minute: Optional[int]
    day_of_week: Optional[str]
    interval_minutes: Optional[int]
    timezone: str
    target_type: str
    target_value: Optional[str]
    date_filter: Optional[str]
    sms_type: str
    exclude_sent: bool
    active: bool
    created_at: datetime
    updated_at: datetime
    last_run: Optional[datetime]
    next_run: Optional[datetime]

    class Config:
        from_attributes = True


class ScheduleExecutionResponse(BaseModel):
    success: bool
    sent_count: int = 0
    failed_count: int = 0
    target_count: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


class TargetPreview(BaseModel):
    id: int
    customer_name: str
    phone: str
    date: str
    time: str
    room_number: Optional[str]
    tags: Optional[str]
    room_sms_sent: bool
    party_sms_sent: bool


@router.get("/api/template-schedules", response_model=List[TemplateScheduleResponse])
def get_schedules(
    active: Optional[bool] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all template schedules"""
    query = db.query(TemplateSchedule)

    if active is not None:
        query = query.filter(TemplateSchedule.active == active)
    if template_id:
        query = query.filter(TemplateSchedule.template_id == template_id)

    schedules = query.order_by(TemplateSchedule.created_at.desc()).all()

    result = []
    for schedule in schedules:
        result.append({
            "id": schedule.id,
            "template_id": schedule.template_id,
            "template_name": schedule.template.name if schedule.template else "",
            "template_key": schedule.template.key if schedule.template else "",
            "schedule_name": schedule.schedule_name,
            "schedule_type": schedule.schedule_type,
            "hour": schedule.hour,
            "minute": schedule.minute,
            "day_of_week": schedule.day_of_week,
            "interval_minutes": schedule.interval_minutes,
            "timezone": schedule.timezone,
            "target_type": schedule.target_type,
            "target_value": schedule.target_value,
            "date_filter": schedule.date_filter,
            "sms_type": schedule.sms_type,
            "exclude_sent": schedule.exclude_sent,
            "active": schedule.active,
            "created_at": schedule.created_at,
            "updated_at": schedule.updated_at,
            "last_run": schedule.last_run,
            "next_run": schedule.next_run
        })

    return result


@router.get("/api/template-schedules/{schedule_id}", response_model=TemplateScheduleResponse)
def get_schedule(schedule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a specific template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return {
        "id": schedule.id,
        "template_id": schedule.template_id,
        "template_name": schedule.template.name if schedule.template else "",
        "template_key": schedule.template.key if schedule.template else "",
        "schedule_name": schedule.schedule_name,
        "schedule_type": schedule.schedule_type,
        "hour": schedule.hour,
        "minute": schedule.minute,
        "day_of_week": schedule.day_of_week,
        "interval_minutes": schedule.interval_minutes,
        "timezone": schedule.timezone,
        "target_type": schedule.target_type,
        "target_value": schedule.target_value,
        "date_filter": schedule.date_filter,
        "sms_type": schedule.sms_type,
        "exclude_sent": schedule.exclude_sent,
        "active": schedule.active,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
        "last_run": schedule.last_run,
        "next_run": schedule.next_run
    }


@router.post("/api/template-schedules", response_model=TemplateScheduleResponse)
def create_schedule(schedule: TemplateScheduleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new template schedule"""
    # Verify template exists
    template = db.query(MessageTemplate).filter(MessageTemplate.id == schedule.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate schedule configuration
    if schedule.schedule_type == 'daily' and (schedule.hour is None or schedule.minute is None):
        raise HTTPException(status_code=400, detail="Daily schedule requires hour and minute")
    elif schedule.schedule_type == 'weekly' and (schedule.hour is None or schedule.minute is None or not schedule.day_of_week):
        raise HTTPException(status_code=400, detail="Weekly schedule requires hour, minute, and day_of_week")
    elif schedule.schedule_type == 'hourly' and schedule.minute is None:
        raise HTTPException(status_code=400, detail="Hourly schedule requires minute")
    elif schedule.schedule_type == 'interval' and not schedule.interval_minutes:
        raise HTTPException(status_code=400, detail="Interval schedule requires interval_minutes")

    # Create schedule
    db_schedule = TemplateSchedule(
        template_id=schedule.template_id,
        schedule_name=schedule.schedule_name,
        schedule_type=schedule.schedule_type,
        hour=schedule.hour,
        minute=schedule.minute,
        day_of_week=schedule.day_of_week,
        interval_minutes=schedule.interval_minutes,
        timezone=schedule.timezone,
        target_type=schedule.target_type,
        target_value=schedule.target_value,
        date_filter=schedule.date_filter,
        sms_type=schedule.sms_type,
        exclude_sent=schedule.exclude_sent,
        active=schedule.active
    )

    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)

    # Add to scheduler if active
    if db_schedule.active:
        try:
            schedule_manager = ScheduleManager(scheduler)
            schedule_manager.add_schedule_job(db_schedule, db)
        except Exception as e:
            # Log error but don't fail the creation
            print(f"Warning: Failed to add schedule to APScheduler: {e}")

    return {
        "id": db_schedule.id,
        "template_id": db_schedule.template_id,
        "template_name": db_schedule.template.name,
        "template_key": db_schedule.template.key,
        "schedule_name": db_schedule.schedule_name,
        "schedule_type": db_schedule.schedule_type,
        "hour": db_schedule.hour,
        "minute": db_schedule.minute,
        "day_of_week": db_schedule.day_of_week,
        "interval_minutes": db_schedule.interval_minutes,
        "timezone": db_schedule.timezone,
        "target_type": db_schedule.target_type,
        "target_value": db_schedule.target_value,
        "date_filter": db_schedule.date_filter,
        "sms_type": db_schedule.sms_type,
        "exclude_sent": db_schedule.exclude_sent,
        "active": db_schedule.active,
        "created_at": db_schedule.created_at,
        "updated_at": db_schedule.updated_at,
        "last_run": db_schedule.last_run,
        "next_run": db_schedule.next_run
    }


@router.put("/api/template-schedules/{schedule_id}", response_model=TemplateScheduleResponse)
def update_schedule(schedule_id: int, schedule: TemplateScheduleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Update a template schedule"""
    db_schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not db_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Update fields
    update_data = schedule.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_schedule, field, value)

    db_schedule.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_schedule)

    # Update scheduler
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.update_schedule_job(db_schedule, db)
    except Exception as e:
        print(f"Warning: Failed to update schedule in APScheduler: {e}")

    return {
        "id": db_schedule.id,
        "template_id": db_schedule.template_id,
        "template_name": db_schedule.template.name,
        "template_key": db_schedule.template.key,
        "schedule_name": db_schedule.schedule_name,
        "schedule_type": db_schedule.schedule_type,
        "hour": db_schedule.hour,
        "minute": db_schedule.minute,
        "day_of_week": db_schedule.day_of_week,
        "interval_minutes": db_schedule.interval_minutes,
        "timezone": db_schedule.timezone,
        "target_type": db_schedule.target_type,
        "target_value": db_schedule.target_value,
        "date_filter": db_schedule.date_filter,
        "sms_type": db_schedule.sms_type,
        "exclude_sent": db_schedule.exclude_sent,
        "active": db_schedule.active,
        "created_at": db_schedule.created_at,
        "updated_at": db_schedule.updated_at,
        "last_run": db_schedule.last_run,
        "next_run": db_schedule.next_run
    }


@router.delete("/api/template-schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Remove from scheduler
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.remove_schedule_job(schedule_id)
    except Exception as e:
        print(f"Warning: Failed to remove schedule from APScheduler: {e}")

    db.delete(schedule)
    db.commit()

    return {"success": True, "message": "Schedule deleted"}


@router.post("/api/template-schedules/{schedule_id}/run", response_model=ScheduleExecutionResponse)
async def run_schedule(schedule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Manually execute a template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Execute schedule
    executor = TemplateScheduleExecutor(db)
    result = await executor.execute_schedule(schedule_id)

    return result


@router.get("/api/template-schedules/{schedule_id}/preview", response_model=List[TargetPreview])
def preview_targets(schedule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Preview targets for a schedule without sending messages"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    executor = TemplateScheduleExecutor(db)
    targets = executor.preview_targets(schedule)

    return targets


@router.post("/api/template-schedules/sync")
def sync_schedules(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Sync all active schedules to APScheduler"""
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.sync_all_schedules(db)

        # Get updated schedule info
        schedules = db.query(TemplateSchedule).filter(TemplateSchedule.active == True).all()

        return {
            "success": True,
            "message": f"Synced {len(schedules)} active schedules",
            "count": len(schedules)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync schedules: {str(e)}")
