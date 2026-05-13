"""room_grade.py — 객실/상품 등급 read 유틸.

객실(Room.grade) 과 예약 상품(NaverBizItem.grade) 의 등급을 비교해 객실 업그레이드
여부를 판정한다. room_upgrade_review 커스텀 칩(객후) 발송 조건.

운영자가 객실 설정 / 상품 설정 모달에서 직접 입력. NULL 인 경우 비교 불가 →
객후 칩 생성 skip.
"""
from typing import Optional


# 등급 라벨 (UI 헤더 가이드 전용 — DB 비교에는 사용 안 함)
ROOM_GRADE_LABELS: dict[int, str] = {
    1: "도미토리",
    2: "더블",
    3: "트윈",
    4: "트윈3인실",
    5: "스위트",
}

GRADE_GUIDE_TEXT = "1=도미 < 2=더블 < 3=트윈 < 4=트윈3인실 < 5=스위트"

GRADE_MIN = 1
GRADE_MAX = 5


def grade_of_room(room) -> Optional[int]:
    """Room.grade 반환. room 또는 grade 가 None 이면 None."""
    return room.grade if room is not None else None


def grade_of_biz_item(biz_item) -> Optional[int]:
    """NaverBizItem.grade 반환. biz_item 또는 grade 가 None 이면 None."""
    return biz_item.grade if biz_item is not None else None


def is_valid_grade(value) -> bool:
    """1 <= value <= 5 인 정수만 True. bool 은 거부 (Python bool 은 int subclass)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and GRADE_MIN <= value <= GRADE_MAX
