"""reconcile.py — 예약 mutation 후 SMS 칩 정합성 단일 진입점.

5종 칩 (일반 column_match / 추가요금 surcharge / 파티 MMS party3 /
무료 업그레이드 약속 room_upgrade_promise / 무료 업그레이드 후기 room_upgrade_review)
을 한 번에 재계산한다. 호출자는 이 함수 한 번만 호출하면 모든 칩이 일관된 상태가 됨.

스코프 분리:
  - RoomAssignment(객실 배정) 자체의 정리는 reconcile_dates 가 담당하며,
    이 함수는 "RoomAssignment 가 이미 최신" 인 시점에 호출되어야 한다.
"""
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import Reservation
from app.diag_logger import diag
from app.services.schedule_utils import date_range

logger = logging.getLogger(__name__)


def reconcile_all_chips(
    db: Session,
    reservation_id: int,
    *,
    dates: Optional[List[str]] = None,
    room_id: Optional[int] = None,
) -> None:
    """예약 1건의 모든 SMS 칩 정합성 보장.

    Args:
        reservation_id: 대상 예약
        dates: 처리할 날짜 목록. None 이면 예약의 stay 전체 기간 사용.
        room_id: surcharge 가 특정 RoomAssignment 만 보고 싶을 때 명시.
    """
    # 순환 import 회피용 지연 import
    from app.services.room_assignment import sync_sms_tags
    from app.services.surcharge import reconcile_surcharge
    from app.services.party3_mms import reconcile_party3_mms_for_reservation
    from app.services.room_upgrade_promise import reconcile_room_upgrade_promise
    from app.services.room_upgrade_review import reconcile_room_upgrade_review

    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        return

    if dates is not None:
        target_dates = list(dates)
    else:
        target_dates = list(date_range(res.check_in_date, res.check_out_date))

    diag(
        "reconcile_all_chips.enter",
        level="verbose",
        res_id=reservation_id,
        date_count=len(target_dates),
        explicit_dates=dates is not None,
    )

    try:
        sync_sms_tags(db, reservation_id)
    except Exception as e:
        logger.warning(
            f"reconcile_all_chips: sync_sms_tags failed for res={reservation_id}: {e}"
        )

    for d in target_dates:
        try:
            reconcile_surcharge(db, reservation_id, d, room_id=room_id)
        except Exception as e:
            logger.warning(
                f"reconcile_all_chips: surcharge failed res={reservation_id} date={d}: {e}"
            )
        try:
            reconcile_party3_mms_for_reservation(db, reservation_id, d)
        except Exception as e:
            logger.warning(
                f"reconcile_all_chips: party3 failed res={reservation_id} date={d}: {e}"
            )
        try:
            # room_upgrade_promise / _review 는 자체 진입 가드 (find_single_schedule)
            # 가 있어 스케줄 비활성 시 즉시 return (no-op + critical diag 미발화).
            # promise 는 첫박만, review 는 마지막박만 — 각자 target_mode 가드 내장.
            reconcile_room_upgrade_promise(db, reservation_id, d)
        except Exception as e:
            logger.warning(
                f"reconcile_all_chips: room_upgrade_promise failed res={reservation_id} date={d}: {e}"
            )
        try:
            reconcile_room_upgrade_review(db, reservation_id, d)
        except Exception as e:
            logger.warning(
                f"reconcile_all_chips: room_upgrade_review failed res={reservation_id} date={d}: {e}"
            )

    diag("reconcile_all_chips.exit", level="verbose", res_id=reservation_id)
