"""
Template Schedules API
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from typing import List, Literal, Optional
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from app.api.deps import get_tenant_scoped_db, get_current_tenant, _remap_active_field
from app.db.models import TemplateSchedule, MessageTemplate, User
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.scheduler.schedule_manager import ScheduleManager
from app.scheduler.jobs import scheduler
from app.api.shared_schemas import ActionResponse
from app.diag_logger import diag

router = APIRouter(prefix="/api/template-schedules", tags=["template-schedules"])


# filter type 화이트리스트 — _parse_filters 로 정규화된 v2 결과에서 허용하는 type 들
_ALLOWED_FILTER_TYPES = {"assignment", "column_match"}


def _validate_schedule_inputs(
    db: Session,
    *,
    effective_category: Optional[str],
    effective_custom_type: Optional[str],
    raw_filters,
    validate_custom_type: bool,
    validate_filters: bool,
    schedule_id: Optional[int] = None,
) -> None:
    """스케줄 create/update 공통 입력 검증.

    - `validate_custom_type=True` 이면 custom_schedule 인 경우 custom_type 필수 +
      레지스트리 등록 여부 + 같은 tenant·custom_type 활성 중복 방지 검사.
    - `validate_filters=True` 이면 filters 의 type 이 화이트리스트에 있는지 확인
      (raw_filters 는 List[dict] 또는 JSON 문자열 허용 — _parse_filters 가 처리).
    - update 경로에서는 해당 필드가 요청에 없으면 (`validate_*=False`) skip — 기존
      잘못된 DB 값으로 수정 불가 락 방지.

    실패 시 HTTPException(400).
    """
    # 1) custom_type 검증 (registry 등록 여부만 확인)
    # 주: 같은 custom_type 으로 여러 시간대 스케줄을 동시에 두는 것은 허용됨.
    #     스케줄러는 template_key 기준으로 칩을 찾으므로 하나가 sent 된 뒤엔 자동으로
    #     다른 스케줄들이 중복 발송하지 않음 (exclude_sent + unique 제약이 방어).
    if validate_custom_type and effective_category == 'custom_schedule':
        from app.services.custom_schedule_registry import CUSTOM_SCHEDULE_TYPES
        if not effective_custom_type:
            raise HTTPException(
                status_code=400,
                detail="커스텀 스케줄은 custom_type 을 지정해야 합니다",
            )
        if effective_custom_type not in CUSTOM_SCHEDULE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"등록되지 않은 custom_type: {effective_custom_type}",
            )

    # 2) filter type 화이트리스트 (정규화 후 v2 결과로 검사)
    if validate_filters and raw_filters:
        from app.services.filters import _parse_filters
        parsed = _parse_filters(raw_filters)
        unknown = [
            f.get("type") for f in parsed
            if f.get("type") not in _ALLOWED_FILTER_TYPES
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"알 수 없는 필터 타입: {', '.join(str(t) for t in unknown)}",
            )


def _schedule_to_response(schedule: TemplateSchedule) -> dict:
    """Convert a TemplateSchedule ORM object to a response dict."""
    from app.services.filters import _parse_filters
    # Parse filters JSON for response (normalises v1 → v2 automatically)
    filters = _parse_filters(schedule.filters)

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
        "target_mode": schedule.target_mode,
        "exclude_sent": schedule.exclude_sent,
        "active": schedule.is_active,
        "date_target": schedule.date_target,
        "stay_filter": schedule.stay_filter,
        "send_condition_date": schedule.send_condition_date,
        "send_condition_ratio": schedule.send_condition_ratio,
        "send_condition_operator": schedule.send_condition_operator,
        "schedule_category": schedule.schedule_category or "standard",
        "custom_type": schedule.custom_type,
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
    schedule_type: Literal['daily', 'weekly', 'hourly', 'interval']
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    active_start_hour: Optional[int] = None
    active_end_hour: Optional[int] = None
    timezone: str = "Asia/Seoul"
    filters: Optional[List[dict]] = None  # [{"type": "tag", "value": "객후"}, ...]
    target_mode: Optional[Literal['first_night', 'last_night']] = None
    exclude_sent: bool = True
    active: bool = True
    date_target: Optional[Literal['yesterday', 'today', 'tomorrow']] = None
    stay_filter: Optional[Literal['exclude']] = None
    # Send condition fields
    send_condition_date: Optional[Literal['today', 'tomorrow']] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[Literal['gte', 'lte']] = None
    # Event schedule fields
    schedule_category: Optional[Literal['standard', 'event', 'custom_schedule']] = 'standard'
    hours_since_booking: Optional[int] = None
    gender_filter: Optional[Literal['male', 'female']] = None
    max_checkin_days: Optional[int] = None
    expires_after_days: Optional[int] = None
    custom_type: Optional[str] = None


class TemplateScheduleUpdate(BaseModel):
    template_id: Optional[int] = None
    schedule_name: Optional[str] = None
    schedule_type: Optional[Literal['daily', 'weekly', 'hourly', 'interval']] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    day_of_week: Optional[str] = None
    interval_minutes: Optional[int] = None
    active_start_hour: Optional[int] = None
    active_end_hour: Optional[int] = None
    timezone: Optional[str] = None
    filters: Optional[List[dict]] = None
    target_mode: Optional[Literal['first_night', 'last_night']] = None
    exclude_sent: Optional[bool] = None
    active: Optional[bool] = None
    date_target: Optional[Literal['yesterday', 'today', 'tomorrow']] = None
    stay_filter: Optional[Literal['exclude']] = None
    # Send condition fields
    send_condition_date: Optional[Literal['today', 'tomorrow']] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[Literal['gte', 'lte']] = None
    # Event schedule fields
    schedule_category: Optional[Literal['standard', 'event', 'custom_schedule']] = None
    hours_since_booking: Optional[int] = None
    gender_filter: Optional[Literal['male', 'female']] = None
    max_checkin_days: Optional[int] = None
    expires_after_days: Optional[int] = None
    custom_type: Optional[str] = None


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
    target_mode: Optional[str] = None
    exclude_sent: bool
    active: bool
    date_target: Optional[str] = None
    stay_filter: Optional[str] = None
    # Send condition fields
    send_condition_date: Optional[str] = None
    send_condition_ratio: Optional[float] = None
    send_condition_operator: Optional[str] = None
    # Event schedule fields
    schedule_category: str = 'standard'
    custom_type: Optional[str] = None
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


@router.get("/custom-types")
def get_custom_types():
    """커스텀 스케줄 로직 타입 목록 반환 (프론트엔드 드롭다운용)."""
    from app.services.custom_schedule_registry import get_custom_types
    return get_custom_types()


@router.get("", response_model=List[TemplateScheduleResponse])
def get_schedules(
    active: Optional[bool] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get all template schedules"""
    query = db.query(TemplateSchedule).options(selectinload(TemplateSchedule.template))

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

    # Event schedule: hours_since_booking 은 선택 (NULL = 확정 시점 무관, 모든 confirmed 대상)

    # custom_schedule 검증 + filter type 화이트리스트 (create 는 두 검증 모두 활성)
    _validate_schedule_inputs(
        db,
        effective_category=schedule.schedule_category,
        effective_custom_type=schedule.custom_type,
        raw_filters=schedule.filters,
        validate_custom_type=True,
        validate_filters=True,
    )

    # stay option guard: room 배정 필터 없으면 stay_filter 자동 null화
    # 단, event 카테고리는 객실 배정 무관 (신규 예약자 대상) 이라 schedule.stay_filter
    # 컬럼을 단독 필드로 사용. UI 에서 직접 켜고 끔.
    if schedule.schedule_category != 'event':
        from app.services.filters import _parse_filters
        parsed = _parse_filters(schedule.filters) if schedule.filters else []
        has_room = any(f.get('type') == 'assignment' and f.get('value') == 'room' for f in parsed)
        if not has_room:
            schedule.stay_filter = None

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
        target_mode=schedule.target_mode,
        exclude_sent=schedule.exclude_sent,
        is_active=schedule.active,
        date_target=schedule.date_target,
        stay_filter=schedule.stay_filter,
        send_condition_date=schedule.send_condition_date,
        send_condition_ratio=schedule.send_condition_ratio,
        send_condition_operator=schedule.send_condition_operator,
        schedule_category=schedule.schedule_category or 'standard',
        custom_type=schedule.custom_type,
        hours_since_booking=schedule.hours_since_booking,
        gender_filter=schedule.gender_filter,
        max_checkin_days=schedule.max_checkin_days,
        expires_after_days=schedule.expires_after_days,
        expires_at=expires_at,
    )

    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)

    diag(
        "schedule.created",
        level="critical",
        schedule_id=db_schedule.id,
        template_id=db_schedule.template_id,
        name=db_schedule.schedule_name,
    )

    # Auto-generate chips for matching reservations
    if db_schedule.is_active:
        from app.services.chip_reconciler import reconcile_chips_for_schedule
        reconcile_chips_for_schedule(db, db_schedule)
        db.commit()

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

    # Event schedule: hours_since_booking 은 선택 (NULL = 확정 시점 무관)
    effective_category = schedule.schedule_category if schedule.schedule_category is not None else db_schedule.schedule_category

    # Update fields
    update_data = schedule.dict(exclude_unset=True)

    # custom_schedule / filter 검증: 요청에 해당 필드가 포함된 경우만 검증
    # (exclude_unset 가드 — 기존 DB 에 잘못된 값이 있어도 관련 필드 수정 안 하는 경우는 락 안 걸림)
    validate_custom = ('schedule_category' in update_data) or ('custom_type' in update_data)
    validate_filters = 'filters' in update_data
    if validate_custom or validate_filters:
        effective_custom_type = (
            update_data['custom_type'] if 'custom_type' in update_data
            else db_schedule.custom_type
        )
        _validate_schedule_inputs(
            db,
            effective_category=effective_category,
            effective_custom_type=effective_custom_type,
            raw_filters=update_data.get('filters'),
            validate_custom_type=validate_custom,
            validate_filters=validate_filters,
            schedule_id=schedule_id,
        )
    # Serialize filters list to JSON string for DB storage
    if "filters" in update_data and update_data["filters"] is not None:
        update_data["filters"] = json.dumps(update_data["filters"], ensure_ascii=False)
    # Remap Pydantic 'active' field to ORM 'is_active' column
    _remap_active_field(update_data)
    # stay option guard: filters 가 변경됐고 room 배정 없으면 stay_filter null화
    # 단, event 카테고리는 객실 배정 무관 (신규 예약자 대상) 이라 schedule.stay_filter
    # 컬럼을 단독 필드로 사용. UI 가 stay_filter 직접 PATCH.
    if 'filters' in update_data:
        effective_category_for_stay = (
            update_data.get('schedule_category')
            if 'schedule_category' in update_data
            else db_schedule.schedule_category
        )
        if effective_category_for_stay != 'event':
            from app.services.filters import _parse_filters
            parsed = _parse_filters(update_data['filters']) if update_data['filters'] else []
            has_room = any(f.get('type') == 'assignment' and f.get('value') == 'room' for f in parsed)
            if not has_room and 'stay_filter' not in update_data:
                update_data['stay_filter'] = None
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
    # (v2: stay_filter 가 filters JSON 안으로 이관되어 별도 트래킹 불필요)
    _FILTER_FIELDS = {'filters', 'target_mode', 'date_target', 'schedule_category', 'is_active', 'template_id'}
    if _FILTER_FIELDS & set(update_data.keys()):
        from app.services.chip_reconciler import reconcile_chips_for_schedule
        db.flush()
        reconcile_chips_for_schedule(db, db_schedule)

    db.commit()
    db.refresh(db_schedule)

    diag(
        "schedule.updated",
        level="critical",
        schedule_id=schedule_id,
        changed=list(update_data.keys()),
    )
    if "is_active" in update_data:
        diag(
            "schedule.toggled",
            level="critical",
            schedule_id=schedule_id,
            is_active=update_data["is_active"],
        )

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

    # Delete chips owned by this schedule (other schedules' chips are preserved).
    # chip_store 위임 (PR10 이주) — 기본 가드 (sent_at + manual/excluded/failed).
    from app.services.chip_store import delete_chips_for_schedule
    delete_chips_for_schedule(db, schedule_id=schedule_id)

    db.delete(schedule)
    db.flush()

    db.commit()

    diag("schedule.deleted", level="critical", schedule_id=schedule_id)

    return {"success": True, "message": "스케줄이 삭제되었습니다"}


@router.post("/{schedule_id}/run", response_model=ScheduleExecutionResponse)
async def run_schedule(schedule_id: int, db: Session = Depends(get_tenant_scoped_db), tenant=Depends(get_current_tenant), current_user: User = Depends(require_admin_or_above)):
    """Manually execute a template schedule"""
    schedule = db.query(TemplateSchedule).filter(TemplateSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

    diag("schedule.manual_execute", level="verbose", schedule_id=schedule_id)

    # Execute schedule
    executor = TemplateScheduleExecutor(db, tenant=tenant)
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
    """Sync all active schedules to APScheduler

    [사용 가이드 작성 시 포함할 내용]
    - 정상 운영 시 이 API를 수동 호출할 필요 없음
    - 스케줄 CRUD 시 개별 APScheduler 반영이 자동으로 됨
    - 서버 시작(startup) 시 전체 스케줄 일괄 로드됨 (load_template_schedules)
    - 이 API는 비상용: DB 직접 수정, APScheduler-DB 불일치 의심, 디버깅 시 사용
    """
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
