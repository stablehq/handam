"""
RoomAssignment invariant 검증 서비스.

FILL-ONLY 전환(Phase 2-4) 후 엣지 케이스 커버:
  - 예약의 성별/인원 변경으로 기존 배정이 제약 위반하는지 감지
  - 방 설정(biz_item, capacity) 변경 시 영향받는 예약 추적

관심사 분리: room_assignment.py (CRUD) 와 invariants.py (검증) 분리.
"""
from collections import defaultdict
from typing import List
from sqlalchemy.orm import Session, joinedload

from app.db.models import RoomAssignment, Reservation
from app.config import today_kst
from app.diag_logger import diag


def check_assignment_validity(db: Session, reservation: Reservation) -> List[str]:
    """현재 배정이 예약 제약을 위반하는 날짜 리스트 반환.

    체크 항목:
      1. 도미토리: 성별 잠금 (다른 성별 입실자 존재)
      2. 도미토리: 용량 초과
      (일반실 다중 점유는 운영자 수동 결정으로 정책상 허용)

    과거/당일 배정은 체크 대상에서 제외 (변경 비실용적).

    H-B 최적화: joinedload로 Room 배치 로드 + others 배치 조회.

    Returns: 위반 날짜 리스트. 호출자는 try/except로 감싸야 함.
    """
    diag("invariant.check.enter", level="verbose", res_id=reservation.id)
    invalid: List[str] = []
    today_str = today_kst()

    # H-B: joinedload로 Room 미리 로드
    assignments = db.query(RoomAssignment).options(
        joinedload(RoomAssignment.room)
    ).filter(
        RoomAssignment.reservation_id == reservation.id,
        RoomAssignment.date > today_str,  # 과거/당일 제외
    ).all()

    if not assignments:
        diag("invariant.check.exit", level="verbose", res_id=reservation.id, invalid_count=0)
        return invalid

    # H-B: 모든 (room_id, date) 쌍에 대한 others를 배치 조회
    room_ids = list({ra.room_id for ra in assignments})
    dates = list({ra.date for ra in assignments})
    all_others = db.query(RoomAssignment).filter(
        RoomAssignment.room_id.in_(room_ids),
        RoomAssignment.date.in_(dates),
        RoomAssignment.reservation_id != reservation.id,
    ).all()

    others_by_key = defaultdict(list)
    for o in all_others:
        others_by_key[(o.room_id, o.date)].append(o)

    # Reservation 배치 조회 (성별 체크용)
    other_res_ids = {o.reservation_id for o in all_others}
    other_res_map = {}
    if other_res_ids:
        rows = db.query(Reservation).filter(
            Reservation.id.in_(other_res_ids)
        ).all()
        other_res_map = {r.id: r for r in rows}

    res_gender = (reservation.gender or "").strip()
    res_count = reservation.party_size or reservation.booking_count or 1

    for ra in assignments:
        room = ra.room  # joinedload 덕분
        if not room:
            continue
        others = others_by_key.get((ra.room_id, ra.date), [])

        if room.is_dormitory:
            # 성별 충돌 체크
            if res_gender:
                gender_conflict = False
                for o in others:
                    o_res = other_res_map.get(o.reservation_id)
                    o_gender = (o_res.gender or "").strip() if o_res else ""
                    if o_gender and o_gender != res_gender:
                        gender_conflict = True
                        break
                if gender_conflict:
                    invalid.append(ra.date)
                    diag(
                        "invariant.violation",
                        level="verbose",
                        res_id=reservation.id,
                        date=ra.date,
                        reason="gender_conflict",
                    )
                    continue

            # 용량 체크
            other_total = sum(
                (other_res_map.get(o.reservation_id).party_size or 1) if other_res_map.get(o.reservation_id) else 1
                for o in others
            )
            if other_total + res_count > (room.bed_capacity or 1):
                invalid.append(ra.date)
                diag(
                    "invariant.violation",
                    level="verbose",
                    res_id=reservation.id,
                    date=ra.date,
                    reason="capacity",
                )
                continue
        else:
            # 일반실: 수동 공동 점유 허용 (운영자 의도된 배정).
            # 자동배정은 한 방 1팀 강제이므로 일반실 다중 점유는 항상 수동 결정.
            pass

    diag("invariant.check.exit", level="verbose", res_id=reservation.id, invalid_count=len(invalid))
    return invalid


def check_room_config_impact(db: Session, room_id: int) -> List[int]:
    """방 설정 변경 시 영향받을 미래 배정의 reservation_id 리스트.

    Returns: 영향받는 unique reservation_id 리스트.
    """
    today_str = today_kst()
    affected = db.query(RoomAssignment.reservation_id).filter(
        RoomAssignment.room_id == room_id,
        RoomAssignment.date >= today_str,
    ).distinct().all()
    result = [r[0] for r in affected]
    diag(
        "invariant.room_config_impact",
        level="verbose",
        room_id=room_id,
        affected_count=len(result),
    )
    return result
