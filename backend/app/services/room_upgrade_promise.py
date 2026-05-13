"""room_upgrade_promise.py — 무료 업그레이드 약속 안내 (첫박 발송).

room_upgrade_review (마지막박 객후) 와 동일 도메인 룰이지만 발송 시점이 다름.

도메인 룰은 room_upgrade_common.decide_upgrade_eligible 에서 공유:
  배정 객실 등급 > 예약 상품 등급 AND 인원 미초과

이 모듈만의 가드:
  - custom_type = "room_upgrade_promise"
  - target_date == check_in_date (첫박)
    └ schedule.target_mode 가 명시되어 있으면 그것도 일치해야 함

stay 단위 1칩 — 다박이라도 첫박 1번만 발송.
"""
import logging
from typing import List

from sqlalchemy.orm import Session

from app.db.models import Reservation
from app.diag_logger import diag
from app.services.room_upgrade_common import (
    decide_upgrade_eligible,
    delete_all_chips,
    ensure_chip,
    find_single_schedule,
    has_chip_in_stay,
    matches_target_mode,
    remove_chip,
)

logger = logging.getLogger(__name__)

ROOM_UPGRADE_PROMISE = "room_upgrade_promise"
_DIAG_PREFIX = "room_upgrade_promise"


def decide_chip(db: Session, reservation: Reservation, target_date: str) -> bool:
    """target_date 가 첫박 AND 도메인 룰 통과 시 True."""
    if target_date != str(reservation.check_in_date):
        return False
    return decide_upgrade_eligible(
        db, reservation, target_date, diag_prefix=_DIAG_PREFIX
    )


def reconcile_room_upgrade_promise(
    db: Session, reservation_id: int, date: str
) -> None:
    """단건 reconcile (idempotent).

    가드 순서:
    1. _find_schedule None 이면 즉시 return (스케줄 비활성 시 critical 폭주 차단)
    2. matches_target_mode 통과 못 하면 skip
    3. 첫박 + 도메인 통과 시 stay 1칩 가드 거쳐 칩 생성
    """
    schedule = find_single_schedule(db, ROOM_UPGRADE_PROMISE)
    if not schedule:
        return  # 안전망

    reservation = (
        db.query(Reservation).filter(Reservation.id == reservation_id).first()
    )
    if not reservation:
        return

    if not matches_target_mode(reservation, date, schedule.target_mode):
        return

    diag(
        f"{_DIAG_PREFIX}.reconcile.enter",
        level="verbose",
        res_id=reservation_id,
        date=date,
    )
    try:
        if decide_chip(db, reservation, date):
            if has_chip_in_stay(db, schedule, reservation_id):
                return
            ensure_chip(db, reservation_id, date, schedule, diag_prefix=_DIAG_PREFIX)
        else:
            remove_chip(db, reservation_id, date, schedule, diag_prefix=_DIAG_PREFIX)
    except Exception:
        logger.exception(
            "room_upgrade_promise: reconcile 실패 (reservation_id=%s, date=%s)",
            reservation_id,
            date,
        )
        diag(
            f"{_DIAG_PREFIX}.reconcile_failed",
            level="critical",
            res_id=reservation_id,
            date=date,
        )


def reconcile_room_upgrade_promise_batch(
    db: Session, reservation_ids: List[int], date: str
) -> None:
    """배치 reconcile. 개별 실패 격리."""
    schedule = find_single_schedule(db, ROOM_UPGRADE_PROMISE)
    if not schedule:
        return  # 안전망
    diag(
        f"{_DIAG_PREFIX}.batch.enter",
        level="verbose",
        count=len(reservation_ids),
    )
    for rid in reservation_ids:
        try:
            reconcile_room_upgrade_promise(db, rid, date)
        except Exception:
            logger.exception(
                "room_upgrade_promise batch: 개별 reconcile 실패 (res_id=%s)", rid
            )


def _delete_all_room_upgrade_promise_chips(
    db: Session, reservation_id: int, date: str
) -> None:
    """해당 (res, date) 의 미발송 약속 칩 일괄 삭제 (배정 해제 등에서 호출)."""
    delete_all_chips(
        db,
        reservation_id,
        date,
        ROOM_UPGRADE_PROMISE,
        diag_prefix=_DIAG_PREFIX,
    )
