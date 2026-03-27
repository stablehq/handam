"""
Template Schedules API
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Literal, Optional
from pydantic import BaseModel, model_validator
from datetime import datetime, timezone, timedelta

from app.api.deps import get_tenant_scoped_db, _remap_active_field
from app.db.models import TemplateSchedule, MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.scheduler.schedule_manager import ScheduleManager
from app.scheduler.jobs import scheduler
from app.api.shared_schemas import ActionResponse

router = APIRouter(prefix="/api/template-schedules", tags=["template-schedules"])


def _schedule_to_response(schedule: TemplateSchedule) -> dict:
    """Convert a TemplateSchedule ORM object to a response dict."""
    # Parse filters JSON for response
    filters = []
    if schedule.filters:
        try:
            filters = json.loads(schedule.filters)
        except (json.JSONDecodeError, TypeError):
            filters = []

    # Get real-time next_run from APScheduler (DB value can be stale)
    next_run = schedule.next_run_at
    try:
        job = scheduler.get_job(f"template_schedule_{schedule.id}")
        if job and job.next_run_time:
            next_run = job.next_run_time
    except Exception:
        pass

    return {
        "id": schedule.id,
        "template_id": schedule.template_id,
        "template_name": schedule.template.name if schedule.template else "",
        "template_key": schedule.template.template_key if schedule.template else "",
        "schedule_name": schedule.schedule_name,
        "schedule_type": schedule.schedule_type,
        "hour": schedule.hour,
        "minute": schedule.minute,
        "day_of_week": schedule.day_of_week,
        "interval_minutes": schedule.interval_minutes,
        "active_start_hour": schedule.active_start_hour,
        "active_end_hour": schedule.active_end_hour,
        "timezone": schedule.timezone,
        "filters": filters,
        "target_mode": schedule.target_mode or "once",
        "exclude_sent": schedule.exclude_sent,
        "active": schedule.is_active,
        "once_per_stay": schedule.once_per_stay or False,
        "date_target": schedule.date_target,
        "stay_filter": schedule.stay_filter,
        "send_condition_date": schedule.send_condition_date,
        "send_condition_ratio": schedule.send_condition_ratio,
        "send_condition_operator": schedule.send_condition_operator,
        "schedule_category": schedule.schedule_category or "standard",
        "hours_since_booking": schedule.hours_since_booking,
        "gender_filter": schedule.gender_filter,
        "max_checkin_days": schedule.max_checkin_days,
        "expires_after_days": schedule.expires_after_days,
        "expires_at": schedule.expires_at.isoformat() if schedule.expires_at else None,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
        "last_run": schedule.last_run_at,
        "next_run": next_run,
    }


# Pydantic models
class TemplateScheduleCreate(BaseModel):
    template_id: int
    schedule_name: str
    schedule_type: str  # 'daily', 'weekly', 'hourly', 'interval'
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    active_start_hour: Optional[int] = None
    active_end_hour: Optional[int] = None
    timezone: str = "Asia/Seoul"
    filters: Optional[List[dict]] = None  # [{"type": "tag", "value": "객후"}, ...]
    target_mode: Optional[Literal['once', 'daily', 'last_day']] = "once"
    exclude_sent: bool = True
    active: bool = True
    once_per_stay: Optional[bool] = False
    date_target: Optional[Literal['today', 'tomorrow', 'today_checkout', 'tomorrow_checkout']] = None
    stay_filter: Optional[Literal['exclude']] = None
    # Send condition fields
    send_condition_date: Optional[Literal['today', 'tomorrow']] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[Literal['gte', 'lte']] = None
    # Event schedule fields
    schedule_category: Optional[Literal['standard', 'event']] = 'standard'
    hours_since_booking: Optional[int] = None
    gender_filter: Optional[Literal['male', 'female']] = None
    max_checkin_days: Optional[int] = None
    expires_after_days: Optional[int] = None


class TemplateScheduleUpdate(BaseModel):
    template_id: Optional[int] = None
    schedule_name: Optional[str] = None
    schedule_type: Optional[str] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    active_start_hour: Optional[int] = None
    active_end_hour: Optional[int] = None
    timezone: Optional[str] = None
    filters: Optional[List[dict]] = None
    target_mode: Optional[Literal['once', 'daily', 'last_day']] = None
    exclude_sent: Optional[bool] = None
    active: Optional[bool] = None
    once_per_stay: Optional[bool] = None
    date_target: Optional[Literal['today', 'tomorrow', 'today_checkout', 'tomorrow_checkout']] = None
    stay_filter: Optional[Literal['exclude']] = None
    # Send condition fields
    send_condition_date: Optional[Literal['today', 'tomorrow']] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[Literal['gte', 'lte']] = None
    # Event schedule fields
    schedule_category: Optional[Literal['standard', 'event']] = None
    hours_since_booking: Optional[int] = None
    gender_filter: Optional[Literal['male', 'female']] = None
    max_checkin_days: Optional[int] = None
    expires_after_days: Optional[int] = None


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
    active_start_hour: Optional[int] = None
    active_end_hour: Optional[int] = None
    timezone: str
    filters: Optional[List[dict]] = None
    target_mode: Optional[str] = "once"
    exclude_sent: bool
    active: bool
    once_per_stay: Optional[bool] = False
    date_target: Optional[str] = None
    stay_filter: Optional[str] = None
    # Send condition fields
    send_condition_date: Optional[str] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[str] = None
    # Event schedule fields
    schedule_category: str = 'standard'
    hours_since_booking: Optional[int] = None
    gender_filter: Optional[str] = None
    max_checkin_days: Optional[int] = None
    expires_after_days: Optional[int] = None
    expires_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None

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
    check_in_date: str
    check_in_time: str
    room_number: Optional[str]


@router.get("", response_model=List[TemplateScheduleResponse])
def get_schedules(
    active: Optional[bool] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get all template schedules"""
    query = db.query(TemplateSchedule)

    if active is not None:
        query = query.filter(TemplateSchedule.is_active == active)
    if template_id:
        query = query.filter(TemplateSchedule.template_id == template_id)

    schedules = query.order_by(TemplateSchedule.created_at.desc()).all()

    return [_schedule_to_response(s) for s in schedules]


@router.get("/{schedule_id}", response_model=TemplateScheduleResponse)
def get_schedule(schedule_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get a specific template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    return _schedule_to_response(schedule)


@router.post("", response_model=TemplateScheduleResponse)
def create_schedule(schedule: TemplateScheduleCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Create a new template schedule"""
    # Verify template exists
    template = db.query(MessageTemplate).filter(MessageTemplate.id == schedule.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")

    # Validate schedule configuration
    if schedule.schedule_type == 'daily' and (schedule.hour is None or schedule.minute is None):
        raise HTTPException(status_code=400, detail="일간 스케줄은 시간과 분을 지정해야 합니다")
    elif schedule.schedule_type == 'weekly' and (schedule.hour is None or schedule.minute is None or not schedule.day_of_week):
        raise HTTPException(status_code=400, detail="주간 스케줄은 시간, 분, 요일을 지정해야 합니다")
    elif schedule.schedule_type == 'hourly' and schedule.minute is None:
        raise HTTPException(status_code=400, detail="시간별 스케줄은 분을 지정해야 합니다")
    elif schedule.schedule_type == 'interval' and not schedule.interval_minutes:
        raise HTTPException(status_code=400, detail="인터벌 스케줄은 간격(분)을 지정해야 합니다")

    # Event schedule validation
    if schedule.schedule_category == 'event' and not schedule.hours_since_booking:
        raise HTTPException(status_code=400, detail="이벤트 스케줄은 hours_since_booking을 지정해야 합니다")

    # Calculate expires_at from expires_after_days
    expires_at = None
    if schedule.expires_after_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=schedule.expires_after_days)

    # Create schedule
    filters_json = json.dumps(schedule.filters, ensure_ascii=False) if schedule.filters else None
    db_schedule = TemplateSchedule(
        template_id=schedule.template_id,
        schedule_name=schedule.schedule_name,
        schedule_type=schedule.schedule_type,
        hour=schedule.hour,
        minute=schedule.minute,
        day_of_week=schedule.day_of_week,
        interval_minutes=schedule.interval_minutes,
        active_start_hour=schedule.active_start_hour,
        active_end_hour=schedule.active_end_hour,
        timezone=schedule.timezone,
        filters=filters_json,
        target_mode=schedule.target_mode or "once",
        exclude_sent=schedule.exclude_sent,
        is_active=schedule.active,
        once_per_stay=schedule.once_per_stay or False,
        date_target=schedule.date_target,
        stay_filter=schedule.stay_filter,
        send_condition_date=schedule.send_condition_date,
        send_condition_ratio=schedule.send_condition_ratio,
        send_condition_operator=schedule.send_condition_operator,
        schedule_category=schedule.schedule_category or 'standard',
        hours_since_booking=schedule.hours_since_booking,
        gender_filter=schedule.gender_filter,
        max_checkin_days=schedule.max_checkin_days,
        expires_after_days=schedule.expires_after_days,
        expires_at=expires_at,
    )

    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)

    # Add to scheduler if active
    if db_schedule.is_active:
        try:
            schedule_manager = ScheduleManager(scheduler)
            schedule_manager.add_schedule_job(db_schedule, db)
        except Exception as e:
            # Log error but don't fail the creation
            print(f"Warning: Failed to add schedule to APScheduler: {e}")

    return _schedule_to_response(db_schedule)


@router.put("/{schedule_id}", response_model=TemplateScheduleResponse)
def update_schedule(schedule_id: int, schedule: TemplateScheduleUpdate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Update a template schedule"""
    db_schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not db_schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    # Event schedule validation
    effective_category = schedule.schedule_category if schedule.schedule_category is not None else db_schedule.schedule_category
    effective_hours = schedule.hours_since_booking if schedule.hours_since_booking is not None else db_schedule.hours_since_booking
    if effective_category == 'event' and not effective_hours:
        raise HTTPException(status_code=400, detail="이벤트 스케줄은 hours_since_booking을 지정해야 합니다")

    # Update fields
    update_data = schedule.dict(exclude_unset=True)
    # Serialize filters list to JSON string for DB storage
    if "filters" in update_data and update_data["filters"] is not None:
        update_data["filters"] = json.dumps(update_data["filters"], ensure_ascii=False)
    # Remap Pydantic 'active' field to ORM 'is_active' column
    _remap_active_field(update_data)
    # Recalculate expires_at when expires_after_days changes
    if "expires_after_days" in update_data:
        if update_data["expires_after_days"]:
            update_data["expires_at"] = datetime.now(timezone.utc) + timedelta(days=update_data["expires_after_days"])
        else:
            update_data["expires_at"] = None
    # exclude_sent: Pydantic과 ORM 속성명이 동일하므로 리매핑 불필요
    for field, value in update_data.items():
        setattr(db_schedule, field, value)

    db_schedule.updated_at = datetime.now(timezone.utc)

    # Reconcile chips when filter-affecting fields change
    _FILTER_FIELDS = {'filters', 'target_mode', 'date_target', 'schedule_category'}
    if _FILTER_FIELDS & set(update_data.keys()):
        from app.services.chip_reconciler import reconcile_chips_for_schedule
        db.flush()
        reconcile_chips_for_schedule(db, db_schedule)

    db.commit()
    db.refresh(db_schedule)

    # Update scheduler
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.update_schedule_job(db_schedule, db)
    except Exception as e:
        print(f"Warning: Failed to update schedule in APScheduler: {e}")

    return _schedule_to_response(db_schedule)


@router.delete("/{schedule_id}", response_model=ActionResponse)
def delete_schedule(schedule_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Delete a template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    # Remove from scheduler
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.remove_schedule_job(schedule_id)
    except Exception as e:
        print(f"Warning: Failed to remove schedule from APScheduler: {e}")

    db.delete(schedule)
    db.commit()

    return {"success": True, "message": "스케줄이 삭제되었습니다"}


@router.post("/{schedule_id}/run", response_model=ScheduleExecutionResponse)
async def run_schedule(schedule_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Manually execute a template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    # Execute schedule
    executor = TemplateScheduleExecutor(db)
    result = await executor.execute_schedule(schedule_id, manual=True)

    return result


@router.get("/{schedule_id}/preview", response_model=List[TargetPreview])
def preview_targets(schedule_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Preview targets for a schedule without sending messages"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    executor = TemplateScheduleExecutor(db)
    targets = executor.preview_targets(schedule)

    return targets


@router.post("/auto-assign")
def auto_assign(
    date: Optional[str] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-assign ReservationSmsAssignment records for all active schedules.
    Only creates records that don't yet exist (no duplicates).
    """
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()

    total_created = 0
    schedule_results = []

    executor = TemplateScheduleExecutor(db)

    for schedule in schedules:
        if not schedule.template or not schedule.template.is_active:
            continue
        # 이벤트 스케줄은 사전 태그 생성 불가
        if schedule.schedule_category == 'event':
            continue
        # If a date was provided and schedule has no date_target, temporarily override
        if date and not schedule.date_target:
            original = schedule.date_target
            schedule.date_target = date
            created = executor.auto_assign_for_schedule(schedule)
            schedule.date_target = original
        else:
            created = executor.auto_assign_for_schedule(schedule)

        total_created += created
        schedule_results.append({
            "schedule_id": schedule.id,
            "schedule_name": schedule.schedule_name,
            "template_key": schedule.template.template_key,
            "created": created,
        })

    db.commit()

    return {
        "success": True,
        "total_created": total_created,
        "schedules": schedule_results,
    }


@router.post("/sync")
def sync_schedules(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above)):
    """Sync all active schedules to APScheduler"""
    try:
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.sync_all_schedules(db)

        # Get updated schedule info
        schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()

        return {
            "success": True,
            "message": f"Synced {len(schedules)} active schedules",
            "count": len(schedules)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync schedules: {str(e)}")
