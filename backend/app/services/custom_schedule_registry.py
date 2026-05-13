"""
custom_schedule_registry.py — 커스텀 스케줄 로직 레지스트리

새 커스텀 로직 추가 시 이 파일의 CUSTOM_SCHEDULE_TYPES에 등록하면
API를 통해 프론트엔드 드롭다운에 자동으로 반영됩니다.

Pre-send refresh:
  스케줄 실행(13:25 등) 직전에 해당 custom_type 의 칩 상태를 최신으로
  맞추기 위해 호출되는 handler 를 등록합니다. 핸들러는 DB 세션과
  target_date 를 받아 reconcile 함수를 호출하고, 발송 로직은 그 결과를
  Eligibility 필터의 기준으로 사용합니다.
"""
from typing import Callable

from sqlalchemy.orm import Session


# 커스텀 스케줄 타입 레지스트리
# key: custom_type 값 (DB에 저장됨)
# label: UI에 표시되는 한글 라벨
CUSTOM_SCHEDULE_TYPES = {
    "surcharge_standard": "인원 초과 (일반 객실)",
    "surcharge_double": "인원 초과 (더블 객실, 업그레이드비 포함)",
    "party3_today_mms": "파티 당일 안내 (MMS, 2차 참여자)",
    "room_upgrade_review": "무료 업그레이드 후기 안내 (객후)",
}


# 날짜별로 개별 발송되어야 하는 custom_type 집합.
# 기본 custom_schedule exclude_sent 는 "날짜 무관 once_per_stay" 이지만,
# 여기에 포함된 타입은 standard 처럼 (reservation_id, date) 단위 중복 차단으로 동작한다.
# (예: party3_today_mms 는 연박자가 매일 파티 참여 시 매일 발송되어야 함)
PER_DATE_DEDUP_CUSTOM_TYPES: set[str] = {
    "party3_today_mms",
}


def is_per_date_dedup(custom_type: str | None) -> bool:
    """custom_type 이 날짜별 dedup 대상인지 여부."""
    return bool(custom_type) and custom_type in PER_DATE_DEDUP_CUSTOM_TYPES


def get_custom_types() -> list[dict]:
    """프론트엔드 드롭다운용 커스텀 타입 목록 반환."""
    return [
        {"value": key, "label": label}
        for key, label in CUSTOM_SCHEDULE_TYPES.items()
    ]


def _refresh_surcharge(db: Session, target_date: str) -> None:
    """surcharge_* 타입 발송 직전 칩 상태 최신화.

    대상:
      (1) target_date 에 방 배정된 모든 예약 — 신규/유지되는 칩 정리
      (2) target_date 에 surcharge_* 미발송 칩이 이미 있는 예약
          — 배정 해제되어 RoomAssignment 에 없는 stale 칩도 정리 대상에 포함

    reconcile_surcharge 는 배정이 없으면 미발송 칩을 삭제하는 로직을 이미
    가지고 있어서 (2) 만 추가하면 잘못된 과금 SMS 를 차단할 수 있다.
    """
    from app.db.models import RoomAssignment, ReservationSmsAssignment, TemplateSchedule
    from app.services.surcharge import reconcile_surcharge_batch

    # (1) 현재 target_date 에 방 배정된 예약
    assigned_ids = {
        row[0] for row in
        db.query(RoomAssignment.reservation_id)
        .filter(RoomAssignment.date == target_date)
        .all()
    }

    # (2) surcharge_* 미발송 칩 보유 예약 (stale 가능)
    surcharge_custom_types = [
        ct for ct in CUSTOM_SCHEDULE_TYPES if ct.startswith("surcharge_")
    ]
    surcharge_schedule_ids = {
        row[0] for row in
        db.query(TemplateSchedule.id)
        .filter(TemplateSchedule.custom_type.in_(surcharge_custom_types))
        .all()
    }
    stale_chip_ids: set[int] = set()
    if surcharge_schedule_ids:
        stale_chip_ids = {
            row[0] for row in
            db.query(ReservationSmsAssignment.reservation_id)
            .filter(
                ReservationSmsAssignment.schedule_id.in_(surcharge_schedule_ids),
                ReservationSmsAssignment.date == target_date,
                ReservationSmsAssignment.sent_at.is_(None),
            )
            .all()
        }

    reservation_ids = list(assigned_ids | stale_chip_ids)
    if not reservation_ids:
        return
    reconcile_surcharge_batch(db, reservation_ids, target_date)


def _refresh_party3_today_mms(db: Session, target_date: str) -> None:
    """party3_today_mms 발송 직전 칩 상태 최신화.

    target_date 에 체크인하는 CONFIRMED 예약 중 party_type ∈ {'2','2차만'} 만
    칩으로 유지 (조건 불만족 미발송 칩은 삭제).
    """
    from app.services.party3_mms import reconcile_party3_mms
    reconcile_party3_mms(db, target_date)


def _refresh_room_upgrade_review(db: Session, target_date: str) -> None:
    """room_upgrade_review (객후) 발송 직전 칩 상태 최신화.

    대상:
      (1) target_date 에 방 배정된 모든 예약 — 신규/유지 칩 정리
      (2) target_date 에 객후 미발송 칩이 이미 있는 예약 — stale 칩 정리 포함

    reconcile_room_upgrade_review 는 idempotent — 진입 가드(_find_schedule) 가
    내장이라 스케줄 비활성이면 즉시 return (no-op).
    """
    from app.db.models import ReservationSmsAssignment, RoomAssignment, TemplateSchedule
    from app.services.room_upgrade_review import (
        ROOM_UPGRADE_REVIEW,
        reconcile_room_upgrade_review_batch,
    )

    # (1) 현재 target_date 에 방 배정된 예약
    assigned_ids = {
        row[0]
        for row in db.query(RoomAssignment.reservation_id)
        .filter(RoomAssignment.date == target_date)
        .all()
    }

    # (2) 객후 미발송 칩 보유 예약 (stale 가능)
    schedule_ids = {
        row[0]
        for row in db.query(TemplateSchedule.id)
        .filter(TemplateSchedule.custom_type == ROOM_UPGRADE_REVIEW)
        .all()
    }
    stale_chip_ids: set[int] = set()
    if schedule_ids:
        stale_chip_ids = {
            row[0]
            for row in db.query(ReservationSmsAssignment.reservation_id)
            .filter(
                ReservationSmsAssignment.schedule_id.in_(schedule_ids),
                ReservationSmsAssignment.date == target_date,
                ReservationSmsAssignment.sent_at.is_(None),
            )
            .all()
        }

    reservation_ids = list(assigned_ids | stale_chip_ids)
    if not reservation_ids:
        return
    reconcile_room_upgrade_review_batch(db, reservation_ids, target_date)


# custom_type → (db, target_date) -> None
# 같은 reconcile 로직을 공유하는 타입은 같은 handler 를 가리키면 됨.
PRE_SEND_REFRESH_HANDLERS: dict[str, Callable[[Session, str], None]] = {
    "surcharge_standard": _refresh_surcharge,
    "surcharge_double": _refresh_surcharge,
    "party3_today_mms": _refresh_party3_today_mms,
    "room_upgrade_review": _refresh_room_upgrade_review,
}


def get_pre_send_refresh_handler(custom_type: str | None) -> Callable[[Session, str], None] | None:
    """custom_type 에 등록된 refresh handler 를 반환. 없으면 None."""
    if not custom_type:
        return None
    return PRE_SEND_REFRESH_HANDLERS.get(custom_type)
