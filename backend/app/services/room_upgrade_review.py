"""room_upgrade_review.py — 객실 무료 업그레이드 후기 안내(객후) SMS 칩 자동 조정.

발송 조건 (모두 만족):
  1. 배정 객실 등급 > 예약 상품 등급 (Room.grade vs NaverBizItem.grade)
  2. guest_count <= 예약 상품 default_capacity (인원 초과면 surcharge 영역, skip)
  3. Room.grade / NaverBizItem.grade 모두 NOT NULL
  4. stay 내 이미 같은 schedule 칩이 없을 것 (sent/unsent 무관 — stay 당 평생 1번)

surcharge.py 와 동형이지만 lifecycle 은 독립 (surcharge 칩 상태에 의존하지 않음).
인원 미초과 + 등급 업 = 무료 업그레이드 = 객후 발송 대상.
인원 초과 시 = 추가요금 영역 = surcharge 가 처리 = 객후 skip.

진입 가드:
  reconcile_room_upgrade_review() 맨 처음에 _find_schedule() 호출.
  스케줄 비활성/미존재 시 즉시 return — decide_chip 호출 안 함.
  PR 2 배포 직후 (스케줄 활성화 전) grade_missing critical 폭주 방지.
"""
import logging
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    NaverBizItem,
    Reservation,
    ReservationSmsAssignment,
    Room,
    RoomAssignment,
    TemplateSchedule,
)
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag
from app.services.room_grade import grade_of_biz_item, grade_of_room

logger = logging.getLogger(__name__)

ROOM_UPGRADE_REVIEW = "room_upgrade_review"


def _find_schedule(db: Session) -> Optional[TemplateSchedule]:
    """활성 room_upgrade_review 스케줄 1개 (없으면 None).

    PR 2 배포 직후, 또는 운영자가 스케줄 비활성화한 경우 None 반환 →
    reconcile 함수가 즉시 early return 하여 grade_missing critical 폭주 차단.
    """
    return (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.schedule_category == "custom_schedule",
            TemplateSchedule.custom_type == ROOM_UPGRADE_REVIEW,
            TemplateSchedule.is_active == True,  # noqa: E712 (SQLAlchemy)
        )
        .first()
    )


def _has_existing_chip_in_stay(
    db: Session, schedule: TemplateSchedule, reservation_id: int
) -> bool:
    """stay 내 같은 schedule 의 칩이 존재 (sent/unsent 무관).

    객후는 stay 당 평생 1번 발송 정책. exclude_sent 가 박일 무관 dedup 으로
    재발송은 막지만, unique constraint 가 (res_id, template_key, date) 라
    박일별로 row 자체는 만들 수 있다. 그 row 노이즈도 막아 UI 일관성 유지.
    """
    return (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.schedule_id == schedule.id,
        )
        .first()
        is not None
    )


def decide_chip(db: Session, reservation: Reservation, target_date: str) -> bool:
    """target_date 에 객후 칩이 있어야 하는가? (stay 단위 1칩 가드는 호출자에서 추가 확인)

    - RoomAssignment 없음 → False
    - 인원 초과 (surcharge 영역) → False + skipped_overcapacity diag
    - 등급 정보 부족 → False + grade_missing critical diag
    - 등급 동일/다운그레이드 → False (정상 — diag 없음)
    - 등급 업그레이드 → True
    """
    ra = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.date == target_date,
        )
        .first()
    )
    if not ra:
        return False
    room = db.query(Room).filter(Room.id == ra.room_id).first()
    if not room:
        return False

    # 1. 인원 초과 가드 — surcharge 와 동일한 공통 유틸 재사용
    from app.services.surcharge import compute_guest_count, resolve_product_base_capacity

    guest_count = compute_guest_count(reservation)
    booked_base = resolve_product_base_capacity(db, reservation, room)
    if booked_base == 0:
        diag(
            "room_upgrade_review.base_capacity_unknown",
            level="critical",
            res_id=reservation.id,
            biz_item_id=reservation.naver_biz_item_id,
            date=target_date,
        )
        return False
    if guest_count > booked_base:
        # 인원 초과 = 추가요금 영역. surcharge 가 처리. 객후 skip.
        diag(
            "room_upgrade_review.skipped_overcapacity",
            level="verbose",
            res_id=reservation.id,
            guest_count=guest_count,
            base=booked_base,
            date=target_date,
        )
        return False

    # 2. 등급 비교
    biz_item = None
    if reservation.naver_biz_item_id:
        biz_item = (
            db.query(NaverBizItem)
            .filter(NaverBizItem.biz_item_id == str(reservation.naver_biz_item_id))
            .first()
        )
    booked_grade = grade_of_biz_item(biz_item)
    assigned_grade = grade_of_room(room)
    if booked_grade is None or assigned_grade is None:
        diag(
            "room_upgrade_review.grade_missing",
            level="critical",
            res_id=reservation.id,
            booked=booked_grade,
            assigned=assigned_grade,
            biz_item_id=reservation.naver_biz_item_id,
            room_id=room.id,
            date=target_date,
        )
        return False

    return assigned_grade > booked_grade


def reconcile_room_upgrade_review(
    db: Session, reservation_id: int, date: str
) -> None:
    """단건 reconcile (idempotent).

    ★ 진입 가드: 스케줄 비활성/미존재 시 즉시 return.
       이 가드로 PR 2 배포 직후 grade_missing critical 폭주 차단.
    ★ stay 단위 1칩 가드: 이미 stay 내 같은 schedule 칩이 있으면 추가 생성 skip.
       다박 D1=더블, D2=스위트, D3=트윈 시나리오에서 D2 칩 1개만 유지.
    """
    schedule = _find_schedule(db)
    if not schedule:
        return  # 안전망 — decide_chip 호출 안 함 (grade_missing critical 미발화)

    reservation = (
        db.query(Reservation).filter(Reservation.id == reservation_id).first()
    )
    if not reservation:
        return

    diag(
        "room_upgrade_review.reconcile.enter",
        level="verbose",
        res_id=reservation_id,
        date=date,
    )
    try:
        if decide_chip(db, reservation, date):
            # stay 내 이미 칩(sent/unsent 무관) 있으면 추가 생성 skip
            if _has_existing_chip_in_stay(db, schedule, reservation_id):
                return
            _ensure_chip(db, reservation_id, date, schedule)
        else:
            _remove_chip(db, reservation_id, date, schedule)
    except Exception:
        logger.exception(
            "room_upgrade_review: reconcile 실패 (reservation_id=%s, date=%s)",
            reservation_id,
            date,
        )
        diag(
            "room_upgrade_review.reconcile_failed",
            level="critical",
            res_id=reservation_id,
            date=date,
        )


def reconcile_room_upgrade_review_batch(
    db: Session, reservation_ids: List[int], date: str
) -> None:
    """배치 reconcile — 개별 실패가 전체 차단 안 함.

    진입 가드도 한 번만 — 스케줄 없으면 즉시 return.
    """
    schedule = _find_schedule(db)
    if not schedule:
        return  # 안전망
    diag(
        "room_upgrade_review.batch.enter",
        level="verbose",
        count=len(reservation_ids),
    )
    for rid in reservation_ids:
        try:
            reconcile_room_upgrade_review(db, rid, date)
        except Exception:
            logger.exception(
                "room_upgrade_review batch: 개별 reconcile 실패 (res_id=%s)", rid
            )


def _ensure_chip(
    db: Session, reservation_id: int, date: str, schedule: TemplateSchedule
) -> None:
    """객후 칩 생성 (없을 때만). SAVEPOINT 로 race 시 외부 트랜잭션 보호.

    template 비활성화 상태면 칩 생성 skip (template_scheduler 와 동일 규약).
    """
    if not schedule.template or not schedule.template.is_active:
        return
    template_key = schedule.template.template_key
    # uq_res_sms_template_date: (reservation_id, template_key, date)
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.date == date,
            ReservationSmsAssignment.template_key == template_key,
        )
        .first()
    )
    if existing:
        return
    tenant_id = get_session_tenant_id(db)
    try:
        with db.begin_nested():
            db.add(
                ReservationSmsAssignment(
                    reservation_id=reservation_id,
                    template_key=template_key,
                    date=date,
                    assigned_by="auto",
                    schedule_id=schedule.id,
                    sent_at=None,
                    tenant_id=tenant_id,
                )
            )
        diag(
            "room_upgrade_review.chip_applied",
            level="verbose",
            res_id=reservation_id,
            date=date,
        )
    except IntegrityError:
        diag(
            "room_upgrade_review.chip_insert_race",
            level="warn",
            res_id=reservation_id,
            date=date,
        )


def _remove_chip(
    db: Session, reservation_id: int, date: str, schedule: TemplateSchedule
) -> None:
    """해당 (res, date) 의 미발송 객후 칩 삭제 (sent 칩은 보존)."""
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.date == date,
            ReservationSmsAssignment.schedule_id == schedule.id,
            ReservationSmsAssignment.sent_at.is_(None),
        )
        .first()
    )
    if existing:
        db.delete(existing)
        diag(
            "room_upgrade_review.chip_deleted",
            level="verbose",
            res_id=reservation_id,
            date=date,
            reason="decide_false",
        )


def _delete_all_room_upgrade_review_chips(
    db: Session, reservation_id: int, date: str
) -> None:
    """해당 (res, date) 의 미발송 객후 칩 일괄 삭제 (배정 해제 등에서 호출)."""
    schedule_ids = [
        s.id
        for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == "custom_schedule",
            TemplateSchedule.custom_type == ROOM_UPGRADE_REVIEW,
        ).all()
    ]
    if not schedule_ids:
        return
    deleted = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.date == date,
            ReservationSmsAssignment.schedule_id.in_(schedule_ids),
            ReservationSmsAssignment.sent_at.is_(None),
        )
        .delete(synchronize_session="fetch")
    )
    if deleted:
        db.flush()
        diag(
            "room_upgrade_review.all_deleted",
            level="verbose",
            res_id=reservation_id,
            date=date,
            count=deleted,
        )
