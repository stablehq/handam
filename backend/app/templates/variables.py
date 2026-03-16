"""
Template Variable Definitions and Auto-calculation

Defines all available template variables and provides functions to calculate them.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import Reservation


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
        variables['building'] = effective_room_number[0] if len(effective_room_number) >= 2 else ''
        variables['room_num'] = effective_room_number[1:] if len(effective_room_number) >= 2 else effective_room_number
    else:
        variables['building'] = ''
        variables['room_num'] = ''

    # 참여자 통계 (해당 날짜 확정 예약 기준)
    target_date = date or reservation.check_in_date
    if target_date:
        total_count = db.query(Reservation).filter(
            Reservation.check_in_date == target_date,
            Reservation.status.in_(['confirmed', 'completed'])
        ).count()

        female_count = db.query(Reservation).filter(
            Reservation.check_in_date == target_date,
            Reservation.status.in_(['confirmed', 'completed']),
            Reservation.gender == '여'
        ).count()

        male_count = total_count - female_count

        variables['participant_count'] = str(total_count)
        variables['male_count'] = str(male_count)
        variables['female_count'] = str(female_count)
    else:
        variables['participant_count'] = '0'
        variables['male_count'] = '0'
        variables['female_count'] = '0'

    # Custom variables override
    if custom_vars:
        variables.update(custom_vars)

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
