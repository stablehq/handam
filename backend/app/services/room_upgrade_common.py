"""room_upgrade_common.py — 객실 업그레이드 안내 (약속/객후) 공통 유틸.

room_upgrade_promise (첫박 약속) 와 room_upgrade_review (마지막박 객후) 가
공유하는 도메인 룰 + DB 헬퍼.

도메인 룰 (공통):
  배정 객실 등급 > 예약 상품 등급 AND 인원 미초과
  → 무료 업그레이드 안내 대상

각 모듈의 차이:
  - promise: target_date == check_in_date (첫박)
  - review:  target_date == last_night_of_stay (체크아웃 전날)

stay 단위 1칩 가드 — schedule 별로 독립적 (약속 칩 1개 + 객후 칩 1개 = stay 당 최대 2개).
"""
from datetime import datetime, timedelta
from typing import Optional

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


def last_night_of_stay(reservation: Reservation) -> Optional[str]:
    """체크아웃 전날 = 마지막 박일.

    check_out_date 가 NULL 이면 check_in_date 자체가 마지막 박일 (1박).
    """
    if not reservation.check_in_date:
        return None
    if not reservation.check_out_date:
        return str(reservation.check_in_date)
    try:
        co = datetime.strptime(str(reservation.check_out_date), "%Y-%m-%d")
        return (co - timedelta(days=1)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def matches_target_mode(
    reservation: Reservation, target_date: str, target_mode: Optional[str]
) -> bool:
    """target_mode 가드. schedule.target_mode 와 target_date 의 정합성 확인.

    - "first_night": target_date == check_in_date
    - "last_night":  target_date == last_night_of_stay
    - 그 외 (None 포함): 항상 True (가드 없음 — schedule 의 의도가 명시 안 됐다고 봄)
    """
    if target_mode == "first_night":
        return target_date == str(reservation.check_in_date)
    if target_mode == "last_night":
        last = last_night_of_stay(reservation)
        return last is not None and target_date == last
    return True


def has_chip_in_stay(
    db: Session, schedule: TemplateSchedule, reservation_id: int
) -> bool:
    """stay 내 같은 schedule 칩 (sent/unsent 무관) 존재 여부.

    stay 단위 1칩 가드 — schedule 별로 독립.
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


def decide_upgrade_eligible(
    db: Session,
    reservation: Reservation,
    target_date: str,
    *,
    diag_prefix: str,
) -> bool:
    """공통 도메인 룰: 인원 미초과 + 등급 업그레이드 인가?

    target_mode 검증은 호출자 책임 (이미 박일이 맞다고 전제).

    diag_prefix: "room_upgrade_promise" 또는 "room_upgrade_review".
                 발생한 diag 의 prefix 를 모듈별로 구분하기 위함.
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
            f"{diag_prefix}.base_capacity_unknown",
            level="critical",
            res_id=reservation.id,
            biz_item_id=reservation.naver_biz_item_id,
            date=target_date,
        )
        return False
    if guest_count > booked_base:
        diag(
            f"{diag_prefix}.skipped_overcapacity",
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
            f"{diag_prefix}.grade_missing",
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


def ensure_chip(
    db: Session,
    reservation_id: int,
    date: str,
    schedule: TemplateSchedule,
    *,
    diag_prefix: str,
) -> None:
    """schedule 의 template 으로 칩 생성 (없을 때만). SAVEPOINT race 처리.

    template 비활성화 상태면 생성 skip (template_scheduler 와 동일 규약).
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
            f"{diag_prefix}.chip_applied",
            level="verbose",
            res_id=reservation_id,
            date=date,
        )
    except IntegrityError:
        diag(
            f"{diag_prefix}.chip_insert_race",
            level="warn",
            res_id=reservation_id,
            date=date,
        )


def remove_chip(
    db: Session,
    reservation_id: int,
    date: str,
    schedule: TemplateSchedule,
    *,
    diag_prefix: str,
) -> None:
    """해당 (res, date, schedule) 의 미발송 칩 삭제 (sent 칩은 보존)."""
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
            f"{diag_prefix}.chip_deleted",
            level="verbose",
            res_id=reservation_id,
            date=date,
            reason="decide_false",
        )


def delete_all_chips(
    db: Session,
    reservation_id: int,
    date: str,
    custom_type: str,
    *,
    diag_prefix: str,
) -> None:
    """해당 custom_type 의 (res, date) 미발송 칩 일괄 삭제 (배정 해제 등)."""
    schedule_ids = [
        s.id
        for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == "custom_schedule",
            TemplateSchedule.custom_type == custom_type,
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
            f"{diag_prefix}.all_deleted",
            level="verbose",
            res_id=reservation_id,
            date=date,
            count=deleted,
        )


def find_single_schedule(
    db: Session, custom_type: str
) -> Optional[TemplateSchedule]:
    """활성 schedule 1개 (없으면 None) — 진입 가드용.

    custom_type 당 보통 1개의 schedule 이 정상이지만, 운영자가 실수로 여러 개
    만들 수도 있어 .first() 사용. 두 개 만들어졌으면 운영자가 정리해야 함.
    """
    return (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.schedule_category == "custom_schedule",
            TemplateSchedule.custom_type == custom_type,
            TemplateSchedule.is_active == True,  # noqa: E712
        )
        .first()
    )
