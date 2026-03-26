"""
Reservations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Reservation, ReservationStatus, User, Tenant, ReservationSmsAssignment, RoomAssignment, ReservationDailyInfo
from app.factory import get_reservation_provider_for_tenant, get_sms_provider_for_tenant
from app.auth.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import room_assignment
from app.services.activity_logger import log_activity
from app.api.shared_schemas import ActionResponse
from datetime import datetime, timezone
import logging

router = APIRouter(prefix="/api/reservations", tags=["reservations"])
logger = logging.getLogger(__name__)


class ReservationCreate(BaseModel):
    customer_name: str
    phone: str
    check_in_date: str  # YYYY-MM-DD
    check_in_time: str  # HH:MM
    check_out_date: Optional[str] = None  # YYYY-MM-DD (연박 시)
    status: str = "pending"
    notes: Optional[str] = None
    gender: Optional[str] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_size: Optional[int] = 1
    party_type: Optional[str] = None
    booking_source: str = "manual"
    naver_room_type: Optional[str] = None  # Original reservation room type
    section: Optional[str] = None  # 'room', 'unassigned', 'party'

class ReservationUpdate(BaseModel):
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    check_in_date: Optional[str] = None
    check_in_time: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    gender: Optional[str] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_size: Optional[int] = None
    party_type: Optional[str] = None
    naver_room_type: Optional[str] = None  # Original reservation room type
    section: Optional[str] = None  # 'room', 'unassigned', 'party'


class RoomAssignRequest(BaseModel):
    room_id: Optional[int] = None
    date: Optional[str] = None
    apply_subsequent: bool = True  # Apply to subsequent dates for multi-night stays
    apply_group: bool = False  # Apply to all reservations in the same stay_group


class SmsAssignRequest(BaseModel):
    template_key: str
    assigned_by: str = "manual"
    date: str = ''


class SmsAssignmentResponse(BaseModel):
    template_key: str
    assigned_at: datetime
    sent_at: Optional[datetime] = None
    assigned_by: str = "auto"
    date: str = ''

    class Config:
        from_attributes = True


class ReservationResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    customer_name: str
    phone: str
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    check_in_date: str
    check_in_time: str
    status: str
    notes: Optional[str] = None
    booking_source: str
    room_id: Optional[int] = None
    room_number: Optional[str] = None
    room_password: Optional[str] = None
    room_assigned_by: Optional[str] = None
    naver_room_type: Optional[str] = None
    gender: Optional[str] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_size: Optional[int] = None
    party_type: Optional[str] = None
    check_out_date: Optional[str] = None
    biz_item_name: Optional[str] = None
    booking_count: Optional[int] = 1
    booking_options: Optional[str] = None
    special_requests: Optional[str] = None
    total_price: Optional[int] = None
    confirmed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    section: Optional[str] = None  # 'room', 'unassigned', 'party'
    stay_group_id: Optional[str] = None
    stay_group_order: Optional[int] = None
    is_long_stay: bool = False
    created_at: datetime
    updated_at: datetime
    sms_assignments: List[SmsAssignmentResponse] = []

    class Config:
        from_attributes = True


def _to_response(res: Reservation, override_room: Optional[str] = None, override_password: Optional[str] = None, override_assigned_by: Optional[str] = None, override_party_type: Optional[str] = None, override_room_id: Optional[int] = None, db: Session = None, filter_date: Optional[str] = None, daily_keys: Optional[set] = None) -> ReservationResponse:
    assignments = []
    if db is not None and hasattr(res, 'sms_assignments'):
        source = [a for a in res.sms_assignments if a.assigned_by != 'excluded']
        if filter_date is not None:
            # daily_keys가 미전달이면 fallback 조회 (단건 호출 대응)
            if daily_keys is None:
                from app.db.models import TemplateSchedule
                daily_keys = {
                    s.template.template_key
                    for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode == 'daily').all()
                    if s.template
                }
            source = [a for a in source if (a.date or '') == filter_date or ((a.date or '') < filter_date and a.sent_at is not None and a.template_key not in daily_keys)]
        assignments = [
            SmsAssignmentResponse(
                template_key=a.template_key,
                assigned_at=a.assigned_at,
                sent_at=a.sent_at,
                assigned_by=a.assigned_by,
                date=a.date or '',
            )
            for a in source
        ]
    return ReservationResponse(
        id=res.id,
        external_id=res.external_id,
        customer_name=res.customer_name,
        phone=res.phone,
        visitor_name=res.visitor_name,
        visitor_phone=res.visitor_phone,
        check_in_date=res.check_in_date,
        check_in_time=res.check_in_time,
        status=res.status.value,
        notes=res.notes,
        booking_source=res.booking_source,
        room_id=override_room_id,
        room_number=override_room if override_room is not None else res.room_number,
        room_password=override_password if override_password is not None else res.room_password,
        room_assigned_by=override_assigned_by,
        naver_room_type=res.naver_room_type,
        gender=res.gender,
        male_count=res.male_count,
        female_count=res.female_count,
        party_size=res.party_size,
        party_type=override_party_type if override_party_type is not None else res.party_type,
        check_out_date=res.check_out_date,
        biz_item_name=res.biz_item_name,
        booking_count=res.booking_count,
        booking_options=res.booking_options,
        special_requests=res.special_requests,
        total_price=res.total_price,
        confirmed_at=res.confirmed_at,
        cancelled_at=res.cancelled_at,
        section=res.section or 'unassigned',
        stay_group_id=res.stay_group_id,
        stay_group_order=res.stay_group_order,
        is_long_stay=bool(res.is_long_stay),
        created_at=res.created_at,
        updated_at=res.updated_at,
        sms_assignments=assignments,
    )


@router.get("", response_model=List[ReservationResponse])
async def get_reservations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    date: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get reservations with pagination and filtering"""
    query = db.query(Reservation)

    if status:
        query = query.filter(Reservation.status == status)

    if search:
        query = query.filter(
            or_(
                Reservation.customer_name.contains(search),
                Reservation.phone.contains(search),
            )
        )

    if source:
        query = query.filter(Reservation.booking_source == source)

    if date:
        # check-in <= date < check-out (check_out_date)
        # If check_out_date is null, fall back to exact date match
        query = query.filter(
            or_(
                and_(
                    Reservation.check_in_date <= date,
                    Reservation.check_out_date > date,
                ),
                and_(
                    Reservation.check_in_date == date,
                    Reservation.check_out_date.is_(None),
                ),
            )
        )

    # Order by most recent confirmation or cancellation datetime
    from sqlalchemy.orm import selectinload
    reservations = query.options(
        selectinload(Reservation.sms_assignments)
    ).order_by(
        Reservation.confirmed_at.desc().nullslast(),
    ).offset(skip).limit(limit).all()

    # 항상 RoomAssignment에서 객실 정보 조회 (소스 오브 트루스) — 배치 조회로 N+1 제거
    res_ids = [r.id for r in reservations]
    if res_ids:
        # date 파라미터가 있으면 해당 날짜로 일괄 조회, 없으면 각 예약의 date를 키로 사용
        if date:
            from app.services.room_lookup import batch_room_lookup
            _rl = batch_room_lookup(db, res_ids, date)
            room_map = {res_id: (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"]) for res_id, info in _rl.items()}

            # Batch-query daily info for the target date
            daily_infos = (
                db.query(ReservationDailyInfo)
                .filter(
                    ReservationDailyInfo.reservation_id.in_(res_ids),
                    ReservationDailyInfo.date == date,
                )
                .all()
            )
            daily_party_map = {di.reservation_id: di.party_type for di in daily_infos}
        else:
            # date 없음: 각 예약의 check-in date 기준으로 조회
            # (reservation_id, date) 쌍을 한 번에 가져온 뒤 매핑
            res_date_map = {r.id: r.check_in_date for r in reservations}
            room_assignments = (
                db.query(RoomAssignment)
                .filter(RoomAssignment.reservation_id.in_(res_ids))
                .all()
            )
            from app.services.room_lookup import batch_room_lookup
            # Collect only assignments matching each reservation's check-in date
            matching_ids = [ra.reservation_id for ra in room_assignments if ra.date == res_date_map.get(ra.reservation_id)]
            _rl = batch_room_lookup(db, matching_ids) if matching_ids else {}
            # Merge with per-date filter: only keep if the assignment date matches check-in
            room_map = {}
            for ra in room_assignments:
                if ra.date == res_date_map.get(ra.reservation_id) and ra.reservation_id in _rl:
                    info = _rl[ra.reservation_id]
                    room_map[ra.reservation_id] = (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"])
            daily_party_map = {}
    else:
        room_map = {}
        daily_party_map = {}

    # daily_keys를 한 번만 조회 (N+1 방지)
    _daily_keys = None
    if date:
        from app.db.models import TemplateSchedule
        _daily_keys = {
            s.template.template_key
            for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode == 'daily').all()
            if s.template
        }

    results = []
    for res in reservations:
        if res.id in room_map:
            override_room_id, override_room, override_password, override_assigned_by = room_map[res.id]
        elif date:
            # 해당 날짜에 배정 없음 — denormalized field 무시하고 빈 값 반환
            override_room_id, override_room, override_password, override_assigned_by = None, '', '', None
        else:
            override_room_id, override_room, override_password, override_assigned_by = None, None, None, None

        # Resolve per-date party_type: daily info overrides reservation-level value when date is provided
        if date and res.id in daily_party_map:
            override_party_type = daily_party_map[res.id]
        else:
            override_party_type = None  # Fall back to reservation.party_type in _to_response

        results.append(_to_response(res, override_room=override_room, override_password=override_password, override_assigned_by=override_assigned_by, override_party_type=override_party_type, override_room_id=override_room_id, db=db, filter_date=date, daily_keys=_daily_keys))
    return results


@router.post("", response_model=ReservationResponse)
async def create_reservation(reservation: ReservationCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Create a new reservation"""
    # Convert status string to enum
    try:
        status_enum = ReservationStatus(reservation.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    db_reservation = Reservation(
        customer_name=reservation.customer_name,
        phone=reservation.phone,
        check_in_date=reservation.check_in_date,
        check_in_time=reservation.check_in_time,
        status=status_enum,
        notes=reservation.notes,
        booking_source=reservation.booking_source,
        gender=reservation.gender,
        male_count=reservation.male_count,
        female_count=reservation.female_count,
        party_size=reservation.party_size,
        party_type=reservation.party_type,
        check_out_date=reservation.check_out_date,
        naver_room_type=reservation.naver_room_type,  # Original reservation room type
        section=reservation.section or 'unassigned',
    )
    db.add(db_reservation)
    db.flush()

    # Compute is_long_stay for manual reservations
    from app.services.consecutive_stay import compute_is_long_stay
    db_reservation.is_long_stay = compute_is_long_stay(db_reservation)

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.put("/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: int, reservation: ReservationUpdate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)
):
    """Update a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    update_data = reservation.dict(exclude_unset=True)

    # Convert status string to enum if provided
    if "status" in update_data:
        try:
            update_data["status"] = ReservationStatus(update_data["status"])
        except ValueError:
            raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    section_changed = "section" in update_data and update_data["section"] != db_reservation.section
    # column_match 필터 대상 필드 변경 감지
    _SMS_TAG_FIELDS = {"section", "party_type", "gender", "naver_room_type", "notes"}
    sms_fields_changed = section_changed or bool(_SMS_TAG_FIELDS & update_data.keys())

    # Log section change for debugging (room_move 로그와 연계)
    if section_changed:
        old_section = db_reservation.section or "unassigned"
        new_section = update_data["section"]
        section_labels = {"room": "객실", "unassigned": "미배정", "party": "파티만"}
        log_activity(
            db, type="room_move",
            title=f"[{db_reservation.customer_name}] 섹션이동 {section_labels.get(old_section, old_section)} → {section_labels.get(new_section, new_section)}",
            detail={
                "reservation_id": reservation_id,
                "customer_name": db_reservation.customer_name,
                "old_section": old_section,
                "new_section": new_section,
                "move_type": "manual",
            },
            created_by=current_user.username,
        )

    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    # SMS 태그 재계산 (섹션 또는 필터 대상 필드 변경 시)
    if sms_fields_changed:
        db.flush()
        room_assignment.sync_sms_tags(db, reservation_id)

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.delete("/{reservation_id}", response_model=ActionResponse)
async def delete_reservation(reservation_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # 연관 레코드 먼저 삭제 (FK 제약, 현재 테넌트만)
    from app.db.models import PartyCheckin, ReservationDailyInfo
    from app.db.tenant_context import current_tenant_id
    tid = current_tenant_id.get()
    db.query(RoomAssignment).filter(RoomAssignment.reservation_id == reservation_id, RoomAssignment.tenant_id == tid).delete()
    db.query(ReservationSmsAssignment).filter(ReservationSmsAssignment.reservation_id == reservation_id, ReservationSmsAssignment.tenant_id == tid).delete()
    db.query(ReservationDailyInfo).filter(ReservationDailyInfo.reservation_id == reservation_id, ReservationDailyInfo.tenant_id == tid).delete()
    db.query(PartyCheckin).filter(PartyCheckin.reservation_id == reservation_id, PartyCheckin.tenant_id == tid).delete()

    db.delete(db_reservation)
    db.commit()
    return {"success": True, "message": "예약이 삭제되었습니다"}


class RoomAssignResponse(BaseModel):
    reservation: ReservationResponse
    warnings: Optional[List[str]] = None


@router.put("/{reservation_id}/room", response_model=RoomAssignResponse)
async def assign_room(
    reservation_id: int, request: RoomAssignRequest, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)
):
    """Assign or unassign a room to a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    room_id = request.room_id
    req_date = request.date
    apply_subsequent = request.apply_subsequent
    warnings: List[str] = []

    if room_id is None:
        # Unassign room
        end_date = db_reservation.check_out_date if (req_date and apply_subsequent) else None
        room_assignment.unassign_room(
            db,
            reservation_id,
            req_date,
            end_date,
        )
    else:
        # Manual assignment from UI
        from_date = req_date or db_reservation.check_in_date
        end_date = db_reservation.check_out_date if apply_subsequent else None
        room_assignment.assign_room(
            db,
            reservation_id,
            room_id,
            from_date,
            end_date,
            assigned_by="manual",
            created_by=current_user.username,
        )

        # 연장자 그룹 일괄 이동: 같은 stay_group의 다른 예약도 같은 방으로 배정
        if request.apply_group and db_reservation.stay_group_id:
            group_members = db.query(Reservation).filter(
                Reservation.stay_group_id == db_reservation.stay_group_id,
                Reservation.id != reservation_id,
            ).all()
            for member in group_members:
                member_from = member.check_in_date
                member_end = member.check_out_date
                try:
                    room_assignment.assign_room(
                        db,
                        member.id,
                        room_id,
                        member_from,
                        member_end,
                        assigned_by="manual",
                        created_by=current_user.username,
                        skip_logging=True,  # 그룹 이동은 대표 로그 1건만
                    )
                except ValueError as e:
                    warnings.append(f"{member.customer_name}: {e}")

    db.commit()
    db.refresh(db_reservation)

    return RoomAssignResponse(
        reservation=_to_response(db_reservation, db=db),
        warnings=warnings if warnings else None,
    )


class DailyInfoUpdate(BaseModel):
    date: str  # YYYY-MM-DD
    party_type: Optional[str] = None


@router.put("/{reservation_id}/daily-info", response_model=ReservationResponse)
async def update_daily_info(
    reservation_id: int,
    request: DailyInfoUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert per-date party_type for a reservation via ReservationDailyInfo."""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    existing = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date == request.date,
    ).first()

    if existing:
        existing.party_type = request.party_type
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(ReservationDailyInfo(
            reservation_id=reservation_id,
            date=request.date,
            party_type=request.party_type,
        ))

    db.flush()

    # 칩 재계산 (party_type 변경으로 필터 매칭이 달라질 수 있음)
    from app.services.room_assignment import sync_sms_tags
    sync_sms_tags(db, reservation_id)
    db.commit()

    db.refresh(db_reservation)

    # Return with the daily override applied
    override_party_type = request.party_type
    return _to_response(db_reservation, override_party_type=override_party_type, db=db)


@router.post("/sync/naver")
@limiter.limit("5/minute")
async def sync_from_naver(request: Request, from_date: Optional[str] = None, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Sync reservations from Naver Smart Place API.

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
    """
    from app.services.naver_sync import sync_naver_to_db

    reservation_provider = get_reservation_provider_for_tenant(tenant)
    result = await sync_naver_to_db(reservation_provider, db, from_date=from_date)

    log_activity(
        db,
        type="naver_sync",
        title=f"네이버 예약 동기화 : 수동 실행{f' ({from_date}~)' if from_date else ''}",
        detail=result,
        target_count=result.get("total", 0),
        success_count=result.get("synced", 0),
        created_by=current_user.username,
    )
    db.commit()

    return result



@router.post("/{reservation_id}/sms-assign")
async def assign_sms_template(
    reservation_id: int,
    request: SmsAssignRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Assign an SMS template to a reservation"""
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # Check if already assigned
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == request.template_key,
        ReservationSmsAssignment.date == (request.date or ''),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 배정된 템플릿입니다")

    assignment = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=request.template_key,
        assigned_by=request.assigned_by,
        date=request.date or '',
    )
    db.add(assignment)
    db.commit()
    return {"success": True, "template_key": request.template_key}


@router.delete("/{reservation_id}/sms-assign/{template_key}")
async def unassign_sms_template(
    reservation_id: int,
    template_key: str,
    date: str = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an SMS template assignment from a reservation"""
    query = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    )
    if date:
        query = query.filter(ReservationSmsAssignment.date == date)
    assignment = query.first()
    if not assignment:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다")

    # 삭제 대신 excluded로 표시 — sync_sms_tags가 재생성하지 않도록
    assignment.assigned_by = 'excluded'
    assignment.sent_at = None
    db.commit()
    return {"success": True}


@router.patch("/{reservation_id}/sms-toggle/{template_key}")
async def toggle_sms_sent(
    reservation_id: int,
    template_key: str,
    skip_send: bool = False,
    date: str = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Toggle the sent status of an SMS assignment.

    Args:
        skip_send: If True, mark as sent without actually sending SMS.
        date: Target date (YYYY-MM-DD) for date-specific assignment lookup.
    """
    query = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    )
    if date:
        query = query.filter(ReservationSmsAssignment.date == date)
    assignment = query.first()
    if not assignment:
        # Upsert: 레코드가 없으면 생성 (UI에서 태그가 보이는데 DB에 없는 타이밍 이슈 대응)
        assignment = ReservationSmsAssignment(
            reservation_id=reservation_id,
            template_key=template_key,
            date=date or '',
            assigned_by='manual',
            sent_at=None,
        )
        db.add(assignment)
        db.flush()

    if assignment.sent_at:
        assignment.sent_at = None  # Mark as unsent
        db.commit()
        return {"success": True, "sent_at": None}
    elif skip_send:
        # 발송 없이 상태만 변경
        assignment.sent_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True, "sent_at": assignment.sent_at}
    else:
        # 실제 SMS 발송
        reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not reservation or not reservation.phone:
            raise HTTPException(status_code=400, detail="전화번호가 없습니다")

        from app.services.sms_sender import send_single_sms

        sms_provider = get_sms_provider_for_tenant(tenant)
        try:
            # Look up template buffer for participant_count
            from app.db.models import MessageTemplate
            tpl = db.query(MessageTemplate).filter(MessageTemplate.template_key == template_key).first()
            custom_vars = tpl.get_buffer_vars() if tpl else None

            result = await send_single_sms(
                db=db,
                sms_provider=sms_provider,
                reservation=reservation,
                template_key=template_key,
                created_by=current_user.username,
                date=date,
                custom_vars=custom_vars,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SMS 발송 실패: {e}")

        if result.get("success"):
            assignment.sent_at = datetime.now(timezone.utc)
            db.commit()
            return {"success": True, "sent_at": assignment.sent_at}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "SMS 발송 실패"))


class SmsSendByTagRequest(BaseModel):
    template_key: str
    date: str


@router.post("/sms-send-by-tag")
@limiter.limit("10/minute")
async def send_sms_by_tag(
    request: Request,
    sms_data: SmsSendByTagRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Send SMS to all reservations with unsent assignment for a given template_key and date"""
    from app.services.sms_sender import SmsSender

    sms_provider = get_sms_provider_for_tenant(tenant)
    manager = SmsSender(db, sms_provider)
    try:
        result = await manager.send_by_assignment(
            template_key=sms_data.template_key,
            date=sms_data.date,
            sms_provider=sms_provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if result["target_count"] == 0:
        return {"success": True, "sent_count": 0, "message": "No unsent targets found"}

    db.commit()

    return {"success": True, **result}


# ---------------------------------------------------------------------------
# Consecutive stay (연박) endpoints
# ---------------------------------------------------------------------------

class StayGroupLinkRequest(BaseModel):
    reservation_ids: List[int]


@router.post("/detect-consecutive", response_model=ActionResponse)
async def detect_consecutive_stays(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger consecutive stay detection for the current tenant."""
    from app.services.consecutive_stay import detect_and_link_consecutive_stays

    result = detect_and_link_consecutive_stays(db)
    db.commit()

    return {
        "success": True,
        "message": f"연박 감지 완료: {result['groups']}개 그룹, {result['linked']}건 링크, {result['unlinked']}건 해제",
    }


@router.post("/{reservation_id}/stay-group/link", response_model=ActionResponse)
async def link_stay_group(
    reservation_id: int,
    request: StayGroupLinkRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Manually link reservations into a consecutive stay group."""
    from app.services.consecutive_stay import link_reservations

    all_ids = list(set([reservation_id] + request.reservation_ids))
    group_id = link_reservations(db, all_ids)
    if not group_id:
        raise HTTPException(status_code=400, detail="최소 2개 이상의 유효한 예약이 필요합니다")

    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in all_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    db.commit()
    return {"success": True, "message": f"연박 그룹 생성: {group_id}"}


@router.delete("/{reservation_id}/stay-group/unlink", response_model=ActionResponse)
async def unlink_stay_group(
    reservation_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a reservation from its consecutive stay group."""
    from app.services.consecutive_stay import unlink_from_group
    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule, Reservation

    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    affected_ids = []
    if res and res.stay_group_id:
        affected_ids = [r.id for r in db.query(Reservation).filter(
            Reservation.stay_group_id == res.stay_group_id
        ).all()]

    unlinked = unlink_from_group(db, reservation_id)
    if not unlinked:
        raise HTTPException(status_code=404, detail="연박 그룹에 속하지 않은 예약입니다")

    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in affected_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    db.commit()
    return {"success": True, "message": "연박 그룹에서 해제되었습니다"}
