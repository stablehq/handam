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
    section: Optional[str] = None  # 'room', 'unassigned', 'party', 'unstable'

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
    gender_manual: Optional[bool] = None  # True: 수동 편집 보호, False: 동기화 재계산 허용
    party_size: Optional[int] = None
    party_type: Optional[str] = None
    naver_room_type: Optional[str] = None  # Original reservation room type
    section: Optional[str] = None  # 'room', 'unassigned', 'party', 'unstable'
    highlight_color: Optional[str] = None


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
    section: Optional[str] = None  # 'room', 'unassigned', 'party', 'unstable'
    stay_group_id: Optional[str] = None
    stay_group_order: Optional[int] = None
    is_long_stay: bool = False
    bed_order: int = 0
    unstable_party: bool = False
    has_unstable_booking: bool = False
    highlight_color: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sms_assignments: List[SmsAssignmentResponse] = []

    class Config:
        from_attributes = True


def _to_response(res: Reservation, override_room: Optional[str] = None, override_password: Optional[str] = None, override_assigned_by: Optional[str] = None, override_party_type: Optional[str] = None, override_room_id: Optional[int] = None, override_bed_order: Optional[int] = None, db: Session = None, filter_date: Optional[str] = None, daily_keys: Optional[set] = None, override_notes: Optional[str] = None, override_unstable_party: Optional[bool] = None, override_has_unstable_booking: bool = False) -> ReservationResponse:
    assignments = []
    if db is not None and hasattr(res, 'sms_assignments'):
        source = [a for a in res.sms_assignments if a.assigned_by != 'excluded']
        if filter_date is not None:
            # [Phase 6: 칩 날짜 필터링] — 조회 날짜 기준으로 어떤 칩을 UI에 보여줄지 결정
            # (1) date == 조회일: 정확히 그 날 칩
            # (2) date < 조회일 AND 발송완료 AND !daily: 과거 발송 완료 칩 (예: 어제 보낸 객실안내)
            # (3) date > 조회일 AND 미발송 AND !daily: 미래 미발송 칩 (예: 내일 보낼 후킹SMS)
            # daily 스케줄은 그 날만 표시 (연박자 각 날에 같은 칩 중복 방지)
            if daily_keys is None:
                from app.db.models import TemplateSchedule
                daily_keys = {
                    s.template.template_key
                    for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode == 'daily').all()
                    if s.template
                }
            source = [a for a in source if (a.date or '') == filter_date or ((a.date or '') < filter_date and a.sent_at is not None and a.template_key not in daily_keys) or ((a.date or '') > filter_date and a.sent_at is None and a.template_key not in daily_keys)]
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
        notes=override_notes if override_notes is not None else res.notes,
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
        bed_order=override_bed_order if override_bed_order is not None else 0,
        unstable_party=override_unstable_party if override_unstable_party is not None else False,
        has_unstable_booking=override_has_unstable_booking,
        highlight_color=res.highlight_color,
        created_at=res.created_at,
        updated_at=res.updated_at,
        sms_assignments=assignments,
    )


@router.get("")
async def get_reservations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get reservations with pagination and filtering"""
    query = db.query(Reservation)

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            query = query.filter(Reservation.status == statuses[0])
        else:
            query = query.filter(Reservation.status.in_(statuses))

    if search:
        query = query.filter(
            or_(
                Reservation.customer_name.contains(search),
                Reservation.phone.contains(search),
            )
        )

    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if len(sources) == 1:
            query = query.filter(Reservation.booking_source == sources[0])
        else:
            query = query.filter(Reservation.booking_source.in_(sources))

    if date:
        # Single date: check-in <= date < check-out (used by RoomAssignment)
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
    elif date_from or date_to:
        # Date range: reservations overlapping with [date_from, date_to]
        if date_from:
            query = query.filter(
                or_(
                    Reservation.check_out_date >= date_from,
                    Reservation.check_out_date.is_(None),
                )
            )
        if date_to:
            query = query.filter(Reservation.check_in_date <= date_to)

    # Total count before pagination (for server-side pagination)
    total_count = query.count()

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
            room_map = {res_id: (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"], info.get("bed_order", 0)) for res_id, info in _rl.items()}

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
            daily_notes_map = {di.reservation_id: di.notes for di in daily_infos if di.notes is not None}
            daily_unstable_map = {di.reservation_id: di.unstable_party for di in daily_infos if di.unstable_party}
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
                    room_map[ra.reservation_id] = (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"], info.get("bed_order", 0))
            daily_party_map = {}
            daily_notes_map = {}
            daily_unstable_map = {}
    else:
        room_map = {}
        daily_party_map = {}
        daily_notes_map = {}

    # daily_keys를 한 번만 조회 (N+1 방지)
    _daily_keys = None
    if date:
        from app.db.models import TemplateSchedule
        _daily_keys = {
            s.template.template_key
            for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode == 'daily').all()
            if s.template
        }

    # 언스테이블 예약 전화번호 매칭: 같은 날짜에 숙박 중인 스테이블 예약자 중 언스테이블도 예약한 사람 감지
    unstable_phone_set: set = set()
    if date:
        unstable_phones = [r.phone for r in reservations if r.section == 'unstable' and r.phone]
        unstable_phone_set = set(unstable_phones)

    results = []
    for res in reservations:
        if res.id in room_map:
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = room_map[res.id]
        elif date:
            # 해당 날짜에 배정 없음 — denormalized field 무시하고 빈 값 반환
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = None, '', '', None, 0
        else:
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = None, None, None, None, 0

        # Resolve per-date party_type: daily info overrides reservation-level value when date is provided
        if date and res.id in daily_party_map:
            override_party_type = daily_party_map[res.id]
        else:
            override_party_type = None  # Fall back to reservation.party_type in _to_response

        # Resolve per-date notes
        if date and res.id in daily_notes_map:
            override_notes = daily_notes_map[res.id]
        else:
            override_notes = None

        # Resolve per-date unstable_party
        override_unstable = daily_unstable_map.get(res.id) if date else None

        # 언스테이블 예약 매칭 (스테이블 예약자 중 언스테이블도 예약한 사람)
        has_unstable = res.section != 'unstable' and bool(res.phone) and res.phone in unstable_phone_set

        results.append(_to_response(res, override_room=override_room, override_password=override_password, override_assigned_by=override_assigned_by, override_party_type=override_party_type, override_room_id=override_room_id, override_bed_order=override_bed_order, db=db, filter_date=date, daily_keys=_daily_keys, override_notes=override_notes, override_unstable_party=override_unstable, override_has_unstable_booking=has_unstable))
    return {"items": results, "total": total_count}


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

    db.flush()
    # Auto-generate chips for new reservation
    from app.services.room_assignment import sync_sms_tags
    sync_sms_tags(db, db_reservation.id)

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
    _SMS_TAG_FIELDS = {"section", "party_type", "gender", "naver_room_type", "notes", "check_in_date", "check_out_date"}
    sms_fields_changed = section_changed or bool(_SMS_TAG_FIELDS & update_data.keys())

    # Log section change for debugging (room_move 로그와 연계)
    if section_changed:
        old_section = db_reservation.section or "unassigned"
        new_section = update_data["section"]
        section_labels = {"room": "객실", "unassigned": "미배정", "party": "파티만", "unstable": "언스테이블"}
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

    # 수동으로 성별 인원 편집 시 gender_manual 플래그 자동 세팅
    # (명시적으로 gender_manual을 전달한 경우는 그 값을 존중)
    if ("male_count" in update_data or "female_count" in update_data) and "gender_manual" not in update_data:
        update_data["gender_manual"] = True

    # 날짜 변경 감지 (orphan RoomAssignment 정리용)
    old_dates = (db_reservation.check_in_date, db_reservation.check_out_date)

    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    # 날짜 변경 시 orphan RoomAssignment 정리 (네이버 동기화와 동일)
    new_dates = (db_reservation.check_in_date, db_reservation.check_out_date)
    if old_dates != new_dates:
        from app.services.consecutive_stay import compute_is_long_stay
        db_reservation.is_long_stay = compute_is_long_stay(db_reservation)
        db.flush()
        room_assignment.reconcile_dates(db, db_reservation)

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

    # 연박 그룹 정리 (삭제 전에 unlink해야 남은 멤버의 is_long_stay가 복원됨)
    if db_reservation.stay_group_id:
        from app.services.consecutive_stay import unlink_from_group
        unlink_from_group(db, reservation_id)

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
        # Reconcile chips after unassign (building/room filter changes)
        room_assignment.sync_sms_tags(db, reservation_id)
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
    notes: Optional[str] = None
    unstable_party: Optional[bool] = None


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

    # section="unstable" 예약에 unstable_party 설정 방지 (이미 언스테이블이므로 복사 불필요)
    sent_fields_check = request.dict(exclude_unset=True)
    if "unstable_party" in sent_fields_check and sent_fields_check["unstable_party"] and db_reservation.section == "unstable":
        raise HTTPException(status_code=400, detail="언스테이블 예약에는 unstable_party를 설정할 수 없습니다")

    existing = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date == request.date,
    ).first()

    sent_fields = request.dict(exclude_unset=True)
    if existing:
        if "party_type" in sent_fields:
            existing.party_type = request.party_type
        if "notes" in sent_fields:
            existing.notes = request.notes
        if "unstable_party" in sent_fields:
            existing.unstable_party = request.unstable_party
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(ReservationDailyInfo(
            reservation_id=reservation_id,
            date=request.date,
            party_type=request.party_type,
            notes=request.notes,
            unstable_party=request.unstable_party or False,
        ))

    db.flush()

    # party_type 또는 notes 변경 시 칩 재계산 (column_match 필터 매칭이 달라질 수 있음)
    if "party_type" in sent_fields or "notes" in sent_fields:
        from app.services.room_assignment import sync_sms_tags
        sync_sms_tags(db, reservation_id)
    db.commit()

    db.refresh(db_reservation)

    # Return with the daily override applied
    override_party_type = request.party_type if "party_type" in sent_fields else None
    override_notes = request.notes if "notes" in sent_fields else None
    return _to_response(db_reservation, override_party_type=override_party_type, override_notes=override_notes, db=db)


@router.post("/sync/naver")
@limiter.limit("5/minute")
async def sync_from_naver(request: Request, from_date: Optional[str] = None, reconcile_date: Optional[str] = None, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Sync reservations from Naver Smart Place API.

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
        reconcile_date: Optional check-in date (YYYY-MM-DD) for STARTDATE-based reconciliation.
    """
    from app.services.naver_sync import sync_naver_to_db

    reservation_provider = get_reservation_provider_for_tenant(tenant)
    result = await sync_naver_to_db(reservation_provider, db, from_date=from_date, reconcile_date=reconcile_date)

    log_activity(
        db,
        type="naver_sync",
        title=f"[스테이블] 네이버 예약 동기화 : 수동 실행{f' ({from_date}~)' if from_date else ''}",
        detail=result,
        target_count=result.get("total", 0),
        success_count=result.get("synced", 0),
        created_by=current_user.username,
    )

    # 언스테이블 동기화도 같이 실행
    unstable_result = None
    if tenant.unstable_business_id and tenant.unstable_cookie:
        from app.real.reservation import RealReservationProvider
        unstable_provider = RealReservationProvider(
            business_id=tenant.unstable_business_id,
            cookie=tenant.unstable_cookie,
        )
        try:
            unstable_result = await sync_naver_to_db(unstable_provider, db, from_date=from_date, source="unstable")
            log_activity(
                db,
                type="naver_sync",
                title=f"[언스테이블] 네이버 예약 동기화 : 수동 실행{f' ({from_date}~)' if from_date else ''}",
                detail=unstable_result,
                target_count=unstable_result.get("total", 0),
                success_count=unstable_result.get("synced", 0),
                created_by=current_user.username,
            )
        except Exception as e:
            logger.warning(f"Unstable sync failed during manual sync: {e}")

    db.commit()

    # 응답에 언스테이블 결과도 포함
    if unstable_result:
        result["unstable"] = unstable_result
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


class ExtendStayRequest(BaseModel):
    """연박추가: create next-day reservation, link stay group, assign room"""
    room_id: Optional[int] = None  # Room to assign on next day (None = no assignment)


class ExtendStayResponse(BaseModel):
    success: bool
    new_reservation_id: int
    stay_group_id: str
    conflict_guests: List[str] = []  # Names of guests already in the room on next day


class ExtendStayAssignRequest(BaseModel):
    new_reservation_id: int
    room_id: int
    date: str  # YYYY-MM-DD
    move_existing_to_unassigned: bool = False  # True = move existing guests to unassigned


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


@router.post("/{reservation_id}/extend-stay", response_model=ExtendStayResponse)
async def extend_stay(
    reservation_id: int,
    request: ExtendStayRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가: 다음날 예약 생성 + 연박 그룹 연결 + 방 배정 (단일 트랜잭션)"""
    from app.services.consecutive_stay import link_reservations
    from app.services.room_assignment import sync_sms_tags, assign_room
    from app.db.models import TemplateSchedule
    from datetime import timedelta, date as date_type

    # 1. 원본 예약 조회
    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # 2. 다음날 날짜 계산
    orig_date = date_type.fromisoformat(original.check_in_date)
    next_date = orig_date + timedelta(days=1)
    next_date_str = next_date.isoformat()
    next_checkout = (next_date + timedelta(days=1)).isoformat()

    # 3. 다음날 예약 생성 (이름, 전화, 인원만 복사)
    new_res = Reservation(
        customer_name=original.customer_name,
        phone=original.phone,
        check_in_date=next_date_str,
        check_in_time=original.check_in_time or "15:00",
        check_out_date=next_checkout,
        male_count=original.male_count,
        female_count=original.female_count,
        party_size=original.party_size,
        gender=original.gender,
        booking_source="extend",
        naver_room_type="수동연박",
        section="room" if request.room_id else "unassigned",
        status=ReservationStatus.CONFIRMED,
    )
    db.add(new_res)
    db.flush()  # Get new_res.id

    # 4. 연박 그룹 연결
    all_ids = [reservation_id, new_res.id]
    if original.stay_group_id:
        group_members = db.query(Reservation.id).filter(
            Reservation.stay_group_id == original.stay_group_id
        ).all()
        all_ids = list(set([m[0] for m in group_members] + [new_res.id]))

    group_id = link_reservations(db, all_ids)
    if not group_id:
        raise HTTPException(status_code=400, detail="연박 그룹 생성 실패")

    # 5. SMS 태그 동기화
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in all_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    from app.db.tenant_context import current_tenant_id
    tid = current_tenant_id.get()

    # 6. 방 배정 + 충돌 확인
    conflict_guests = []
    if request.room_id:
        existing = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == next_date_str,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        if existing:
            conflict_guests = [
                db.query(Reservation.customer_name)
                .filter(Reservation.id == ra.reservation_id, Reservation.tenant_id == tid)
                .scalar() or "Unknown"
                for ra in existing
            ]
        if not conflict_guests:
            assign_room(
                db, new_res.id, request.room_id, next_date_str,
                assigned_by=current_user.username,
            )

    db.commit()

    return ExtendStayResponse(
        success=True,
        new_reservation_id=new_res.id,
        stay_group_id=group_id,
        conflict_guests=conflict_guests,
    )


@router.post("/{reservation_id}/extend-stay/assign-room", response_model=ActionResponse)
async def extend_stay_assign_room(
    reservation_id: int,
    request: ExtendStayAssignRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가 충돌 해결: 방 배정 확정"""
    from app.services.room_assignment import assign_room
    from app.db.tenant_context import current_tenant_id
    tid = current_tenant_id.get()

    if request.move_existing_to_unassigned:
        existing = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == request.date,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.reservation_id != request.new_reservation_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        for ra in existing:
            res = db.query(Reservation).filter(Reservation.id == ra.reservation_id, Reservation.tenant_id == tid).first()
            if res:
                res.section = "unassigned"
            db.delete(ra)
        db.flush()

    assign_room(
        db, request.new_reservation_id, request.room_id, request.date,
        assigned_by=current_user.username,
    )

    db.commit()
    return {"success": True, "message": "방 배정 완료"}


@router.delete("/{reservation_id}/extend-stay", response_model=ActionResponse)
async def cancel_extend_stay(
    reservation_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박취소: 수동연박 예약 삭제 + 연박 그룹 해제 + 원본 복원"""
    from app.services.consecutive_stay import unlink_from_group
    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule

    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    if not original.stay_group_id:
        raise HTTPException(status_code=400, detail="연박 그룹이 없습니다")

    # Find the extended reservation in the same stay group (booking_source='extend', next day)
    extended = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id == original.stay_group_id,
            Reservation.booking_source == "extend",
            Reservation.id != reservation_id,
        )
        .order_by(Reservation.check_in_date.desc())
        .first()
    )

    if not extended:
        raise HTTPException(status_code=400, detail="수동연박 예약을 찾을 수 없습니다 (수동연박만 취소 가능)")

    from app.db.tenant_context import current_tenant_id
    tid = current_tenant_id.get()

    # 1. Delete room assignments for the extended reservation
    db.query(RoomAssignment).filter(RoomAssignment.reservation_id == extended.id, RoomAssignment.tenant_id == tid).delete()

    # 2. Delete SMS assignments for the extended reservation
    db.query(ReservationSmsAssignment).filter(ReservationSmsAssignment.reservation_id == extended.id, ReservationSmsAssignment.tenant_id == tid).delete()

    # 3. Delete daily info for the extended reservation
    db.query(ReservationDailyInfo).filter(ReservationDailyInfo.reservation_id == extended.id, ReservationDailyInfo.tenant_id == tid).delete()

    # 4. Unlink the extended reservation from stay group (this also fixes remaining members)
    unlink_from_group(db, extended.id)

    # 5. Delete the extended reservation
    db.delete(extended)
    db.flush()

    # 6. Sync SMS tags for remaining group members
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    # Get remaining group members (if any)
    if original.stay_group_id:
        remaining = db.query(Reservation.id).filter(
            Reservation.stay_group_id == original.stay_group_id
        ).all()
        for (rid,) in remaining:
            sync_sms_tags(db, rid, schedules=schedules)
    # Also sync the original (it may have been unlinked if group dissolved)
    sync_sms_tags(db, original.id, schedules=schedules)

    db.commit()

    return {"success": True, "message": f"수동연박 취소 완료 ({extended.customer_name})"}
