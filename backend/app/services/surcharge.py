"""surcharge.py — 인원 초과 추가요금 SMS 칩 자동 조정 (2-type).

객실 타입에 따라 2개 스케줄 중 하나로 칩 생성:
  - surcharge_standard: 일반 객실 초과
  - surcharge_double:   더블 객실 초과 (업그레이드비 포함)

단가/박수는 템플릿 변수로 동적 계산됨 (templates/variables.py 참조).
"""
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from app.db.models import (
    Reservation,
    Room,
    RoomAssignment,
    ReservationSmsAssignment,
    TemplateSchedule,
    RoomBizItemLink,
)
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag

logger = logging.getLogger(__name__)

# 더블룸으로 취급할 네이버 biz_item_id (현재 stable 테넌트 기준)
DOUBLE_ROOM_BIZ_ITEM_IDS = {'4779024'}  # [특가] 오션뷰 더블룸 (1인~2인, 단독사용)

SURCHARGE_STANDARD = 'surcharge_standard'
SURCHARGE_DOUBLE = 'surcharge_double'
_ALL_SURCHARGE_TYPES = (SURCHARGE_STANDARD, SURCHARGE_DOUBLE)


def _is_double_room(db: Session, room: Room) -> bool:
    """방에 연결된 biz_item_id 중 DOUBLE_ROOM_BIZ_ITEM_IDS 에 속한 게 있으면 True."""
    links = db.query(RoomBizItemLink).filter(
        RoomBizItemLink.room_id == room.id
    ).all()
    for link in links:
        if link.biz_item_id in DOUBLE_ROOM_BIZ_ITEM_IDS:
            return True
    return False


def _has_test_marker(db: Session, reservation_id: int, date: str) -> bool:
    """[테스트 기간 전용] 예약/일자별 메모에 '테스트' 포함 여부.

    Reservation.notes 또는 ReservationDailyInfo(date).notes 중 하나라도
    '테스트' 포함하면 True. 테스트 기간 종료 시 이 함수 호출부와 함께 제거.
    """
    from app.db.models import Reservation, ReservationDailyInfo
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id
    ).first()
    if reservation and reservation.notes and '테스트' in reservation.notes:
        return True
    daily = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date == date,
    ).first()
    if daily and daily.notes and '테스트' in daily.notes:
        return True
    return False


def _find_schedule(db: Session, custom_type: str) -> Optional[TemplateSchedule]:
    return db.query(TemplateSchedule).filter(
        TemplateSchedule.schedule_category == 'custom_schedule',
        TemplateSchedule.custom_type == custom_type,
        TemplateSchedule.is_active == True,
    ).first()


def compute_guest_count(reservation) -> int:
    """예약의 게스트 인원 계산 (party_size 우선, 없으면 male+female, 없으면 1)."""
    return (
        getattr(reservation, 'party_size', None)
        or (reservation.male_count or 0) + (reservation.female_count or 0)
        or 1
    )


def compute_excess(reservation, room) -> int:
    """기준 인원 초과분 계산 (base_capacity 대비)."""
    if room is None:
        return 0
    base_capacity = room.base_capacity or 0
    return max(0, compute_guest_count(reservation) - base_capacity)


def reconcile_surcharge(
    db: Session,
    reservation_id: int,
    date: str,
    room_id: Optional[int] = None,
) -> None:
    """예약-날짜 기준 surcharge 칩 재조정.

    객실 타입에 따라 surcharge_standard 또는 surcharge_double 칩을 생성.
    반대 타입의 기존 칩은 삭제. excess <= 0 이면 양쪽 모두 삭제.
    """
    diag("surcharge.reconcile.enter", level="verbose", res_id=reservation_id, date=date)
    try:
        # 0. [테스트 기간 전용] notes 에 '테스트' 포함된 예약에만 발송.
        #    테스트 기간 종료 시 이 블록 제거하여 일반 발송으로 전환.
        if not _has_test_marker(db, reservation_id, date):
            _delete_all_surcharge_chips(db, reservation_id, date)
            diag("surcharge.skipped_no_test_marker",
                 level="verbose", res_id=reservation_id, date=date)
            return

        # 1. RoomAssignment 조회
        q = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date == date,
        )
        if room_id is not None:
            q = q.filter(RoomAssignment.room_id == room_id)
        assignment = q.first()
        if not assignment:
            _delete_all_surcharge_chips(db, reservation_id, date)
            return

        # 2. Room 조회 + 도미토리 스킵
        room = db.query(Room).filter(Room.id == assignment.room_id).first()
        if not room or room.is_dormitory:
            _delete_all_surcharge_chips(db, reservation_id, date)
            return

        # 3. 객실 타입 판단
        is_double = _is_double_room(db, room)
        target_type = SURCHARGE_DOUBLE if is_double else SURCHARGE_STANDARD
        other_type = SURCHARGE_STANDARD if is_double else SURCHARGE_DOUBLE

        # 4. 초과 계산 (variables.py 와 공유 helper)
        reservation = db.query(Reservation).filter(
            Reservation.id == reservation_id
        ).first()
        if not reservation:
            return
        excess = compute_excess(reservation, room)

        # 5. 칩 생성/삭제
        if excess > 0:
            _ensure_chip(db, reservation_id, date, target_type)
            _remove_chip(db, reservation_id, date, other_type)
            diag("surcharge.chip_applied", level="verbose",
                 res_id=reservation_id, date=date,
                 type=target_type, excess=excess, is_double=is_double)
        else:
            _remove_chip(db, reservation_id, date, target_type)
            _remove_chip(db, reservation_id, date, other_type)

        db.flush()
    except Exception:
        # 돈 관련 로직이라 조용히 삼키지 않고 critical diag 로 기록.
        # 호출자 경로들은 개별 try/except 로 격리돼 있어 전체 차단은 방지.
        logger.exception(
            "surcharge: reconcile 실패 (reservation_id=%s, date=%s)",
            reservation_id, date,
        )
        diag(
            "surcharge.reconcile_failed",
            level="critical",
            reservation_id=reservation_id,
            date=date,
        )


def _ensure_chip(db: Session, reservation_id: int, date: str, custom_type: str) -> None:
    """해당 custom_type 의 스케줄에 대한 칩이 없으면 생성.

    template 비활성화 상태면 칩 생성하지 않음 (chip_reconciler/template_scheduler 와 동일 규약).
    """
    schedule = _find_schedule(db, custom_type)
    if not schedule or not schedule.template or not schedule.template.is_active:
        return
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id == schedule.id,
    ).first()
    if existing:
        return
    tenant_id = get_session_tenant_id(db)
    db.add(ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=schedule.template.template_key,
        date=date,
        assigned_by='auto',
        schedule_id=schedule.id,
        sent_at=None,
        tenant_id=tenant_id,
    ))


def _remove_chip(db: Session, reservation_id: int, date: str, custom_type: str) -> None:
    """해당 custom_type 의 미발송 칩 삭제."""
    schedule = _find_schedule(db, custom_type)
    if not schedule:
        return
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id == schedule.id,
        ReservationSmsAssignment.sent_at.is_(None),
    ).first()
    if existing:
        db.delete(existing)


def _delete_all_surcharge_chips(db: Session, reservation_id: int, date: str) -> None:
    """해당 예약-날짜의 미발송 surcharge 칩을 모두 삭제."""
    surcharge_schedule_ids = [
        s.id for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == 'custom_schedule',
            TemplateSchedule.custom_type.in_(_ALL_SURCHARGE_TYPES),
        ).all()
    ]
    if not surcharge_schedule_ids:
        return
    deleted = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id.in_(surcharge_schedule_ids),
        ReservationSmsAssignment.sent_at.is_(None),
    ).delete(synchronize_session='fetch')
    if deleted:
        db.flush()
        diag("surcharge.all_deleted", level="verbose",
             res_id=reservation_id, date=date, count=deleted)


def reconcile_surcharge_batch(
    db: Session,
    reservation_ids: List[int],
    date: str,
) -> None:
    """배치 reconcile (개별 실패가 전체 차단 안 함)."""
    diag("surcharge.batch.enter", level="verbose", count=len(reservation_ids))
    for rid in reservation_ids:
        try:
            reconcile_surcharge(db, rid, date)
        except Exception:
            logger.exception("surcharge: batch 처리 중 예외 (rid=%s, date=%s)", rid, date)
    diag("surcharge.batch.exit", level="verbose", count=len(reservation_ids))
