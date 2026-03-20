"""
Template Variable Definitions and Auto-calculation

Defines all available template variables and provides functions to calculate them.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Reservation, ReservationStatus


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
}


def get_or_create_snapshot(db: Session, target_date: str) -> 'ParticipantSnapshot':
    """Get existing snapshot for date, or create one from current DB state."""
    from app.db.models import ParticipantSnapshot

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
    db.flush()
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
    effective_room_number = (room_assignment.room_number if room_assignment else None) or reservation.room_number
    effective_room_password = (room_assignment.room_password if room_assignment else None) or reservation.room_password

    variables['room_password'] = effective_room_password or ''

    if effective_room_number:
        # Room number format: "본관 101호" → building="본관", room_num="101호"
        # Lookup Building name via Room → Building relationship
        from app.db.models import Room, Building
        room_obj = db.query(Room).filter(Room.room_number == effective_room_number).first()
        if room_obj and room_obj.building_id:
            building_obj = db.query(Building).filter(Building.id == room_obj.building_id).first()
            variables['building'] = building_obj.name if building_obj else ''
        else:
            variables['building'] = ''
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

        # Apply buffer from schedule if provided via custom_vars
        buffer = int(custom_vars.get('_participant_buffer', 0)) if custom_vars else 0

        variables['participant_count'] = str(total_male + total_female + buffer)
        variables['male_count'] = str(total_male)
        variables['female_count'] = str(total_female)
    else:
        variables['participant_count'] = '0'
        variables['male_count'] = '0'
        variables['female_count'] = '0'

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
