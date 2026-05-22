"""
Reservations API — shared schemas and helpers
"""
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.db.models import Reservation


def _validate_dates(check_in: Optional[str], check_out: Optional[str]) -> None:
    """check_out_date 가 check_in_date 보다 이전이면 거부.
    같은 날짜(co == ci)는 허용 — 읽기 측에서 NULL 과 동일하게 취급한다.
    """
    if check_in and check_out and check_out < check_in:
        raise ValueError("체크아웃은 체크인보다 이전일 수 없습니다")


class ReservationCreate(BaseModel):
    customer_name: str
    phone: str
    check_in_date: str  # YYYY-MM-DD
    check_in_time: str  # HH:MM
    check_out_date: Optional[str] = None  # YYYY-MM-DD (연박 시). co == ci 는 NULL 과 동일 취급.
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

    @model_validator(mode='after')
    def _check_date_order(self):
        _validate_dates(self.check_in_date, self.check_out_date)
        return self


class ReservationUpdate(BaseModel):
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    check_in_date: Optional[str] = None
    check_in_time: Optional[str] = None
    check_out_date: Optional[str] = None
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

    @model_validator(mode='after')
    def _check_date_order(self):
        # payload 안에 둘 다 들어왔을 때만 비교 (단독 변경은 DB 기존 값 모르므로 통과).
        _validate_dates(self.check_in_date, self.check_out_date)
        return self


_SURCHARGE_TEMPLATE_KEYS = {'add_standard', 'add_double'}


def _compute_surcharge_text(db, reservation, chip):
    """surcharge 칩 ('add_standard'/'add_double') 의 툴팁용 총액 텍스트.

    예: "추가요금 8만원" (2인×2박×2만원). excess=0 이거나 surcharge 류 아니면 None.
    variables._inject_surcharge_vars 와 동일 로직 재사용.
    """
    if chip.template_key not in _SURCHARGE_TEMPLATE_KEYS:
        return None
    try:
        from app.db.models import RoomAssignment
        from app.templates.variables import _inject_surcharge_vars
        ra = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.date == (chip.date or ''),
        ).first()
        if not ra:
            return None
        ctx: dict = {}
        _inject_surcharge_vars(ctx, reservation, ra, db)
        if (ctx.get('excess') or 0) <= 0:
            return None
        total = ctx.get('total_surcharge')
        if total in (None, '', '0'):
            return None
        return f'추가요금 {total}만원'
    except Exception:
        return None


class SmsAssignmentResponse(BaseModel):
    template_key: str
    assigned_at: datetime
    sent_at: Optional[datetime] = None
    assigned_by: str = "auto"
    date: str = ''
    send_status: Optional[str] = None
    send_error: Optional[str] = None
    # surcharge 류 칩 ('add_standard'/'add_double') 만 채움 — 툴팁용 총액 텍스트
    # 예: "추가요금 8만원" (2인×2박×2만원). excess=0 이거나 surcharge 류 아니면 None.
    surcharge_total_text: Optional[str] = None

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
    age_group: Optional[str] = None
    visit_count: Optional[int] = None
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
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    section: Optional[str] = None  # 'room', 'unassigned', 'party', 'unstable'
    stay_group_id: Optional[str] = None
    stay_group_order: Optional[int] = None
    stay_group_total_nights: Optional[int] = None  # 그룹 전체 박수 합 (경로 B: 1박×N split 케이스 지원)
    stay_group_night_offset: Optional[int] = None  # 이 record 시작 전까지 누적된 박수 (cumulative)
    is_long_stay: bool = False
    manually_extended_until: Optional[str] = None
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
        # 같은 stay_group sibling reservation의 sent chip 포함 (UI dedup 위함)
        # 별도 booking 2건이 stay_group으로 묶인 경우(김광원 케이스) 어제 보낸 chip이
        # 오늘 record의 응답에도 포함되어 SmsCell가 ✓발송완료로 표시할 수 있게 함.
        if res.stay_group_id:
            from app.db.models import ReservationSmsAssignment
            sibling_chips = (
                db.query(ReservationSmsAssignment)
                .join(Reservation, Reservation.id == ReservationSmsAssignment.reservation_id)
                .filter(
                    Reservation.stay_group_id == res.stay_group_id,
                    Reservation.id != res.id,
                    ReservationSmsAssignment.sent_at.isnot(None),
                    ReservationSmsAssignment.assigned_by != 'excluded',
                )
                .all()
            )
            source = source + sibling_chips
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
                    for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode.is_(None)).all()
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
                send_status=a.send_status,
                send_error=a.send_error,
                surcharge_total_text=_compute_surcharge_text(db, res, a),
            )
            for a in source
        ]

    # 연박 그룹 총 박수 + 이 record 시작 전까지 누적 박수 계산.
    # 경로 A (한 record 다박) 는 stay_group_id 없음 → 프론트가 date diff 로 계산 (현 동작 유지).
    # 경로 B (1박씩 split → stay_group 묶음) 만 backend 가 계산해서 노출.
    stay_group_total_nights: Optional[int] = None
    stay_group_night_offset: Optional[int] = None
    if res.stay_group_id and db is not None:
        from datetime import date as _date
        members = (
            db.query(Reservation)
            .filter(Reservation.stay_group_id == res.stay_group_id)
            .order_by(Reservation.stay_group_order.asc().nullslast(), Reservation.check_in_date.asc())
            .all()
        )
        cumulative = 0
        total = 0
        for m in members:
            try:
                ci = _date.fromisoformat(str(m.check_in_date)) if m.check_in_date else None
                co = _date.fromisoformat(str(m.check_out_date)) if m.check_out_date else None
                m_nights = (co - ci).days if (ci and co) else 1
                if m_nights < 1:
                    m_nights = 1
            except (ValueError, TypeError):
                m_nights = 1
            if m.id == res.id:
                stay_group_night_offset = cumulative
            cumulative += m_nights
            total += m_nights
        stay_group_total_nights = total

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
        room_number=override_room if override_room is not None else None,
        room_password=override_password if override_password is not None else None,
        room_assigned_by=override_assigned_by,
        naver_room_type=res.naver_room_type,
        gender=res.gender,
        age_group=res.age_group,
        visit_count=res.visit_count,
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
        stay_group_total_nights=stay_group_total_nights,
        stay_group_night_offset=stay_group_night_offset,
        is_long_stay=bool(res.is_long_stay),
        manually_extended_until=res.manually_extended_until,
        bed_order=override_bed_order if override_bed_order is not None else 0,
        unstable_party=override_unstable_party if override_unstable_party is not None else False,
        has_unstable_booking=override_has_unstable_booking,
        highlight_color=res.highlight_color,
        created_at=res.created_at,
        updated_at=res.updated_at,
        sms_assignments=assignments,
    )
