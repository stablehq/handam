"""
Template Variable Definitions and Auto-calculation

Defines all available template variables and provides functions to calculate them.
"""
from typing import Dict, Any, Optional
from datetime import datetime
import math
import json as _json
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import KST
from app.db.models import Reservation, ReservationStatus, ParticipantSnapshot
from app.diag_logger import diag


# 사용 가능한 템플릿 변수 정의
AVAILABLE_VARIABLES = {
    "customer_name": {
        "description": "예약자명",
        "example": "김철수",
        "category": "reservation"
    },
    "phone": {
        "description": "전화번호",
        "example": "010-1234-5678",
        "category": "reservation"
    },
    "building": {
        "description": "건물 (A, B 등)",
        "example": "A",
        "category": "room"
    },
    "room_num": {
        "description": "호수 (101, 205 등)",
        "example": "101",
        "category": "room"
    },
    "room_type": {
        "description": "객실 타입 (실제 배정된 객실의 room_type)",
        "example": "더블룸",
        "category": "room"
    },
    "room_password": {
        "description": "객실 비밀번호",
        "example": "1234",
        "category": "room"
    },
    "prefix_room_password": {
        "description": "앞에 랜덤 prefix 가 붙은 객실 비밀번호 (동일 방 공유 손님들은 같은 번호)",
        "example": "701234",
        "category": "room"
    },
    "participant_count": {
        "description": "총 참여인원",
        "example": "25",
        "category": "party"
    },
    "male_count": {
        "description": "남성 참여인원",
        "example": "13",
        "category": "party"
    },
    "female_count": {
        "description": "여성 참여인원",
        "example": "12",
        "category": "party"
    },
    "tomorrow_male_count": {"description": "내일 남성 인원", "example": "15", "category": "party"},
    "tomorrow_female_count": {"description": "내일 여성 인원", "example": "14", "category": "party"},
    "tomorrow_total_count": {"description": "내일 총 인원", "example": "29", "category": "party"},
    "yesterday_male_count": {"description": "어제 남성 인원", "example": "10", "category": "party"},
    "yesterday_female_count": {"description": "어제 여성 인원", "example": "11", "category": "party"},
    "yesterday_total_count": {"description": "어제 총 인원", "example": "21", "category": "party"},
    # 인원 초과 추가요금 (add_standard / add_double 템플릿 전용)
    "base_capacity": {
        "description": "객실 기본 정원 (add_standard/add_double 전용)",
        "example": "4",
        "category": "surcharge",
    },
    "guest_count": {
        "description": "실제 예약 인원 (add_standard/add_double 전용)",
        "example": "6",
        "category": "surcharge",
    },
    "excess": {
        "description": "초과 인원 수 (add_standard/add_double 전용)",
        "example": "2",
        "category": "surcharge",
    },
    "nights": {
        "description": "체류 박수 — NULL checkout 은 1박 (add_standard/add_double 전용)",
        "example": "3",
        "category": "surcharge",
    },
    "surcharge_per_night": {
        "description": "1박당 추가 금액 (만원 단위, 정수면 정수 / 소수면 소수 표기)",
        "example": "2.5",
        "category": "surcharge",
    },
    "total_surcharge": {
        "description": "총 추가 금액 (만원 단위) = surcharge_per_night × nights",
        "example": "7.5",
        "category": "surcharge",
    },
}


def _apply_buffers(male: int, female: int, custom_vars: dict) -> tuple:
    """버퍼/반올림을 적용하여 (effective_male, effective_female, total) 반환.

    우선순위: gender_ratio_buffers > male/female_buffer > participant_buffer
    성비 동점(남 == 여) 시 female_high 적용.
    round_unit은 total에만 적용. round_mode: ceil(올림), round(반올림), floor(내림).
    """
    _participant_buffer = int(custom_vars.get('_participant_buffer', 0))
    _male_buffer = int(custom_vars.get('_male_buffer', 0))
    _female_buffer = int(custom_vars.get('_female_buffer', 0))
    _grb_raw = custom_vars.get('_gender_ratio_buffers')
    _round_unit = int(custom_vars.get('_round_unit', 0))
    _round_mode = custom_vars.get('_round_mode', 'ceil')

    eff_male = male
    eff_female = female

    if _grb_raw:
        try:
            grb = _json.loads(_grb_raw) if isinstance(_grb_raw, str) else _grb_raw
            if female >= male:  # 동점 시 female_high
                cfg = grb.get('female_high', {})
            else:
                cfg = grb.get('male_high', {})
            eff_male = male + int(cfg.get('m', 0))
            eff_female = female + int(cfg.get('f', 0))
        except (ValueError, TypeError, AttributeError, _json.JSONDecodeError):
            pass  # 파싱 실패 → fallback
    elif _male_buffer or _female_buffer:
        eff_male = male + _male_buffer
        eff_female = female + _female_buffer

    total = eff_male + eff_female + _participant_buffer

    if _round_unit > 0:
        if _round_mode == 'floor':
            total = math.floor(total / _round_unit) * _round_unit
        elif _round_mode == 'round':
            total = round(total / _round_unit) * _round_unit
        else:  # ceil (default)
            total = math.ceil(total / _round_unit) * _round_unit

    return eff_male, eff_female, total


def get_or_create_snapshot(db: Session, target_date: str) -> ParticipantSnapshot:
    """SMS 발송 시 호출 — 있으면 그대로 반환, 없으면 1회 생성."""
    from app.services.filters import stay_coverage_filter

    existing = db.query(ParticipantSnapshot).filter(
        ParticipantSnapshot.date == target_date
    ).first()
    if existing:
        return existing

    # target_date 에 투숙/방문 중인 예약 합계 (연박 중간일 + NULL/당일 포함)
    result = db.query(
        func.coalesce(func.sum(Reservation.male_count), 0).label("total_male"),
        func.coalesce(func.sum(Reservation.female_count), 0).label("total_female"),
    ).filter(
        stay_coverage_filter(target_date),
        Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
    ).first()

    snapshot = ParticipantSnapshot(
        date=target_date,
        male_count=int(result.total_male),
        female_count=int(result.total_female),
    )
    db.add(snapshot)
    try:
        db.begin_nested()  # SAVEPOINT: 실패 시 이 지점만 롤백, 외부 트랜잭션 유지
        db.flush()
    except Exception:
        # UniqueViolation 등 — SAVEPOINT만 롤백, 세션의 다른 변경사항은 보존
        db.rollback()
        existing = db.query(ParticipantSnapshot).filter(
            ParticipantSnapshot.date == target_date
        ).first()
        if existing:
            return existing
        # 여전히 없으면 빈 스냅샷 반환 (발송 중단 방지)
        return ParticipantSnapshot(date=target_date, male_count=0, female_count=0)
    return snapshot


def refresh_snapshot(db: Session, target_date: str) -> Optional[ParticipantSnapshot]:
    """스케줄러(08:50/11:50) 호출 — 있으면 갱신, 없으면 생성."""
    import logging
    from app.services.filters import stay_coverage_filter
    _logger = logging.getLogger(__name__)

    # target_date 에 투숙/방문 중인 예약 합계 (연박 중간일 + NULL/당일 포함)
    result = db.query(
        func.coalesce(func.sum(Reservation.male_count), 0).label("total_male"),
        func.coalesce(func.sum(Reservation.female_count), 0).label("total_female"),
    ).filter(
        stay_coverage_filter(target_date),
        Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
    ).first()

    new_male = int(result.total_male) if result else 0
    new_female = int(result.total_female) if result else 0

    existing = db.query(ParticipantSnapshot).filter(
        ParticipantSnapshot.date == target_date
    ).first()

    if existing:
        old_male, old_female = existing.male_count, existing.female_count
        existing.male_count = new_male
        existing.female_count = new_female
        if old_male != new_male or old_female != new_female:
            _logger.info(f"[Snapshot Refresh] {target_date}: M {old_male}→{new_male}, F {old_female}→{new_female}")
        else:
            _logger.info(f"[Snapshot Refresh] {target_date}: no change (M {new_male}, F {new_female})")
        return existing

    # 스냅샷이 없으면 새로 생성
    snapshot = ParticipantSnapshot(
        date=target_date,
        male_count=new_male,
        female_count=new_female,
    )
    db.add(snapshot)
    db.flush()
    _logger.info(f"[Snapshot Created] {target_date}: M {new_male}, F {new_female}")
    return snapshot


def _calculate_stay_nights(reservation) -> int:
    """체크인~체크아웃 박수. NULL 이면 1박."""
    if not reservation.check_out_date or not reservation.check_in_date:
        return 1
    try:
        ci = datetime.strptime(reservation.check_in_date, "%Y-%m-%d").date()
        co = datetime.strptime(reservation.check_out_date, "%Y-%m-%d").date()
        diff = (co - ci).days
        return max(1, diff)
    except (ValueError, TypeError):
        return 1


def _format_man_won(amount_won: int) -> str:
    """원 단위를 '만원' 표기로 변환. 정수면 정수(str), 소수면 소수(str).

    Examples:
        20000 → '2'
        25000 → '2.5'
        60000 → '6'
        75000 → '7.5'
        120000 → '12'
    """
    v = amount_won / 10000
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def _inject_surcharge_vars(context: Dict[str, Any], reservation, room_assignment, db: Session) -> None:
    """surcharge 템플릿용 변수 주입 — excess/nights/per_night/total."""
    from app.services.surcharge import (
        _is_double_room, compute_guest_count, compute_excess,
        _is_dormitory_reservation,
    )
    from app.db.models import Room, Tenant
    from app.db.tenant_context import get_session_tenant_id

    # Room / is_double 판단
    room = None
    is_double = False
    if room_assignment:
        room = db.query(Room).filter(Room.id == room_assignment.room_id).first()
        if room:
            is_double = _is_double_room(db, room)

    # 단가 조회 (Tenant 설정)
    # 더블룸 = 일반 인원 추가비(unit_standard × excess) + 객실 변경비(double_room_fee, 박수에만 곱함)
    tenant_id = get_session_tenant_id(db)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first() if tenant_id else None
    unit_standard = getattr(tenant, 'surcharge_unit_standard', 20000) if tenant else 20000
    double_room_fee = getattr(tenant, 'surcharge_double_room_fee', 5000) if tenant else 5000

    # guest_count / excess / nights 계산 (surcharge.py 와 공유 helper 사용)
    # 도미토리 상품은 1차 방어(reconcile 게이트) 우회 race 대비 excess=0 강제 — 부당 청구 방지.
    guest_count = compute_guest_count(reservation)
    base_capacity = room.base_capacity if room else 0
    excess = 0 if _is_dormitory_reservation(db, reservation) else compute_excess(reservation, room)
    nights = _calculate_stay_nights(reservation)

    excess_fee_per_night = unit_standard * excess
    per_night = excess_fee_per_night + (double_room_fee if is_double else 0)
    total = per_night * nights

    context['base_capacity'] = base_capacity
    context['guest_count'] = guest_count
    context['excess'] = excess
    context['nights'] = nights
    context['surcharge_per_night'] = _format_man_won(per_night)
    context['total_surcharge'] = _format_man_won(total)


def calculate_template_variables(
    reservation: Reservation,
    db: Session,
    date: Optional[str] = None,
    custom_vars: Optional[Dict[str, Any]] = None,
    room_assignment=None,
    template_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate all template variables for a reservation

    Args:
        reservation: Reservation object
        db: Database session
        date: Optional date for party statistics
        custom_vars: Custom variables to override defaults
        room_assignment: Optional RoomAssignment object
        template_key: Optional template key for template-specific variable injection

    Returns:
        Dictionary of all calculated variables
    """
    variables = {}

    # 직접 매핑 (모델 필드 = 변수명)
    variables['customer_name'] = reservation.customer_name or ''
    variables['phone'] = reservation.phone or ''

    # 객실 정보 - room_assignment 기반 (denormalized fallback 제거, Phase 3-1)
    effective_room_password = room_assignment.room_password if room_assignment else ""
    variables['room_password'] = effective_room_password or ''
    # prefix 붙은 버전 — room_assignment.room_password_prefixed 우선, 없으면 base 로 fallback
    prefixed = room_assignment.room_password_prefixed if room_assignment else None
    variables['prefix_room_password'] = prefixed or effective_room_password or ''

    from app.db.models import Room, Building
    room_obj = None
    if room_assignment and room_assignment.room_id:
        room_obj = db.query(Room).filter(Room.id == room_assignment.room_id).first()

    variables['room_type'] = room_obj.room_type if room_obj else ''

    effective_room_number = room_obj.room_number if room_obj else ""

    if effective_room_number:
        # Lookup Building name via Room → Building relationship
        if room_obj and room_obj.building_id:
            building_obj = db.query(Building).filter(Building.id == room_obj.building_id).first()
            building_name = building_obj.name if building_obj else ''
        else:
            building_name = ''
        # room_number 첫 글자가 A/B면 동 이름으로 치환 (본관 A동/B동 구분)
        if effective_room_number[0] in ('A', 'B'):
            building_name = f"{effective_room_number[0]}동"
        variables['building'] = building_name
        # Extract room number part: "본관 101호" → "101호", or just use as-is
        import re
        num_match = re.search(r'(\d[\d\-]*호?)', effective_room_number)
        variables['room_num'] = num_match.group(1) if num_match else effective_room_number
    else:
        variables['building'] = ''
        variables['room_num'] = ''

    # 참여자 통계 — use snapshot for consistency across the day
    target_date = date or reservation.check_in_date
    if target_date:
        snapshot = get_or_create_snapshot(db, target_date)
        total_male = snapshot.male_count
        total_female = snapshot.female_count

        # 버퍼 적용 (헬퍼 함수 사용)
        eff_m, eff_f, total = _apply_buffers(total_male, total_female, custom_vars or {})
        variables['male_count'] = str(eff_m)
        variables['female_count'] = str(eff_f)
        variables['participant_count'] = str(total)
    else:
        variables['participant_count'] = '0'
        variables['male_count'] = '0'
        variables['female_count'] = '0'

    # 날짜 프리픽스 변수: today/tomorrow/yesterday (동일 버퍼 적용)
    # NOTE: get_or_create_snapshot은 check_in_date 기준 집계. 인원 통계는 항상 체크인 기준.
    from datetime import timedelta as _td
    try:
        _base_date = datetime.strptime(target_date, '%Y-%m-%d').date() if isinstance(target_date, str) and target_date else datetime.now(KST).date()
    except (ValueError, TypeError):
        _base_date = datetime.now(KST).date()

    for _prefix, _delta in [('tomorrow', 1), ('yesterday', -1)]:
        _d = (_base_date + _td(days=_delta)).strftime('%Y-%m-%d')
        _snap = get_or_create_snapshot(db, _d)
        _pm, _pf, _pt = _apply_buffers(_snap.male_count, _snap.female_count, custom_vars or {})
        variables[f'{_prefix}_male_count'] = str(_pm)
        variables[f'{_prefix}_female_count'] = str(_pf)
        variables[f'{_prefix}_total_count'] = str(_pt)

    # surcharge 변수 (add_standard / add_double 템플릿용)
    if template_key in ('add_standard', 'add_double'):
        _inject_surcharge_vars(variables, reservation, room_assignment, db)

    # Custom variables override (excluding internal _prefixed keys)
    if custom_vars:
        variables.update({k: v for k, v in custom_vars.items() if not k.startswith('_')})

    diag(
        "template.variables.calculated",
        level="verbose",
        res_id=reservation.id if reservation else None,
        template_date=date,
        has_room=bool(variables.get("room_num")),
        has_building=bool(variables.get("building")),
        participant_count=variables.get("participant_count"),
        has_room_password=bool(variables.get("room_password")),
    )

    return variables


def get_variable_categories() -> Dict[str, list]:
    """
    Get variables grouped by category

    Returns:
        Dictionary with categories as keys and variable lists as values
    """
    categories = {}
    for var_name, var_info in AVAILABLE_VARIABLES.items():
        category = var_info['category']
        if category not in categories:
            categories[category] = []
        categories[category].append({
            'name': var_name,
            'description': var_info['description'],
            'example': var_info['example']
        })
    return categories
