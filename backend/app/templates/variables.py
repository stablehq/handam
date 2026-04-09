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
    "naver_room_type": {
        "description": "객실 타입",
        "example": "스탠다드 더블",
        "category": "room"
    },
    "room_password": {
        "description": "객실 비밀번호",
        "example": "1234",
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

    existing = db.query(ParticipantSnapshot).filter(
        ParticipantSnapshot.date == target_date
    ).first()
    if existing:
        return existing

    # Calculate from current confirmed reservations
    result = db.query(
        func.coalesce(func.sum(Reservation.male_count), 0).label("total_male"),
        func.coalesce(func.sum(Reservation.female_count), 0).label("total_female"),
    ).filter(
        Reservation.check_in_date == target_date,
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
    _logger = logging.getLogger(__name__)

    # Recalculate from current confirmed reservations
    result = db.query(
        func.coalesce(func.sum(Reservation.male_count), 0).label("total_male"),
        func.coalesce(func.sum(Reservation.female_count), 0).label("total_female"),
    ).filter(
        Reservation.check_in_date == target_date,
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


def calculate_template_variables(
    reservation: Reservation,
    db: Session,
    date: Optional[str] = None,
    custom_vars: Optional[Dict[str, Any]] = None,
    room_assignment=None,
) -> Dict[str, Any]:
    """
    Calculate all template variables for a reservation

    Args:
        reservation: Reservation object
        db: Database session
        date: Optional date for party statistics
        custom_vars: Custom variables to override defaults

    Returns:
        Dictionary of all calculated variables
    """
    variables = {}

    # 직접 매핑 (모델 필드 = 변수명)
    variables['customer_name'] = reservation.customer_name or ''
    variables['phone'] = reservation.phone or ''
    variables['naver_room_type'] = reservation.naver_room_type or ''

    # 객실 정보 - prefer room_assignment if provided
    # room_assignment has room_id (FK) → look up Room for display name
    effective_room_password = (room_assignment.room_password if room_assignment else None) or reservation.room_password
    variables['room_password'] = effective_room_password or ''

    from app.db.models import Room, Building
    room_obj = None
    if room_assignment and room_assignment.room_id:
        room_obj = db.query(Room).filter(Room.id == room_assignment.room_id).first()

    effective_room_number = (room_obj.room_number if room_obj else None) or reservation.room_number

    if effective_room_number:
        # Lookup Building name via Room → Building relationship
        if room_obj and room_obj.building_id:
            building_obj = db.query(Building).filter(Building.id == room_obj.building_id).first()
            building_name = building_obj.name if building_obj else ''
        elif not room_obj:
            # Fallback: look up by reservation.room_number (denormalized)
            fallback_room = db.query(Room).filter(Room.room_number == effective_room_number).first()
            if fallback_room and fallback_room.building_id:
                building_obj = db.query(Building).filter(Building.id == fallback_room.building_id).first()
                building_name = building_obj.name if building_obj else ''
            else:
                building_name = ''
        else:
            building_name = ''
        # room_number 첫 글자가 A/B면 동 이름으로 치환 (본관 A동/B동 구분)
        if effective_room_number and effective_room_number[0] in ('A', 'B'):
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

    # Custom variables override (excluding internal _prefixed keys)
    if custom_vars:
        variables.update({k: v for k, v in custom_vars.items() if not k.startswith('_')})

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
