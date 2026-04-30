"""party3_mms.py — target_date 에 투숙/방문 중이고 party_type='2'/'2차만' 인 예약용 MMS 칩 자동 생성.

파티는 매일 열리고, 연박자가 해당 날짜에 party_type='2'/'2차만' 로 참여하면
매번 "파티 당일 안내" MMS 를 받아야 한다. 따라서 대상 기준은
"당일 체크인" 이 아니라 **"그 날 투숙/방문 중 + 유효 party_type"**.

스케줄(custom_schedule, custom_type='party3_today_mms')이 지정 시각에 실행되기
직전에 pre_send_refresh 로 이 모듈의 reconcile 가 호출된다. 그 시점에
target_date 에 투숙 중인 CONFIRMED 예약을 스캔해서:

  - 유효 party_type (ReservationDailyInfo.party_type 우선, 없으면 Reservation.party_type)
    가 PARTY3_TYPES 안에 들면 → MMS 칩 생성 (없으면 유지)
  - 아니면 → 미발송 MMS 칩 삭제 (이미 발송된 칩은 건드리지 않음)

연박자의 각 밤은 (reservation_id, date) 단위로 칩이 따로 생성되므로,
특정 날짜에 파티 미참여(party_type override=None)면 그날만 자동 제외된다.

실제 MMS 발송은 services/sms_sender.send_single_sms 의 MMS_TEMPLATES 분기에서
레거시 프록시(http://15.164.246.59:3000/sendMass/image)로 라우팅된다.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models import (
    Reservation,
    ReservationStatus,
    ReservationDailyInfo,
    ReservationSmsAssignment,
    TemplateSchedule,
)
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag

logger = logging.getLogger(__name__)

PARTY3_MMS_CUSTOM_TYPE = "party3_today_mms"
PARTY3_TYPES = ("2", "2차만")


def _find_schedule(db: Session) -> Optional[TemplateSchedule]:
    return db.query(TemplateSchedule).filter(
        TemplateSchedule.schedule_category == 'custom_schedule',
        TemplateSchedule.custom_type == PARTY3_MMS_CUSTOM_TYPE,
        TemplateSchedule.is_active == True,
    ).first()


def reconcile_party3_mms(db: Session, date: str) -> None:
    """target_date 기준 party3 MMS 칩 재조정.

    - 대상: date 에 투숙/방문 중인 CONFIRMED 예약, 유효 party_type ∈ PARTY3_TYPES
      (연박 중간일, NULL 체크아웃, 당일 파티/언스테이블 모두 포함)
    - 유효 party_type = ReservationDailyInfo(date).party_type or Reservation.party_type
    - stale 칩은 미발송인 경우만 삭제 (이미 발송된 칩 보존)
    """
    from app.services.filters import stay_coverage_filter

    diag("party3_mms.reconcile.enter", level="verbose", date=date)
    schedule = _find_schedule(db)
    if not schedule or not schedule.template or not schedule.template.is_active:
        diag("party3_mms.no_schedule", level="verbose", date=date)
        return

    template_key = schedule.template.template_key

    # 1. date 에 투숙/방문 중인 CONFIRMED 예약 전체
    reservations = db.query(Reservation).filter(
        stay_coverage_filter(date),
        Reservation.status == ReservationStatus.CONFIRMED,
    ).all()

    if not reservations:
        diag("party3_mms.no_reservations", level="verbose", date=date)
        # 그럼에도 고아 칩이 있을 수 있으므로 계속 진행 (existing 정리)

    reservation_ids = [r.id for r in reservations]

    # 2. 해당 예약들의 당일 daily info 한 번에 조회
    daily_party_map: dict[int, Optional[str]] = {}
    if reservation_ids:
        daily_rows = db.query(ReservationDailyInfo).filter(
            ReservationDailyInfo.reservation_id.in_(reservation_ids),
            ReservationDailyInfo.date == date,
        ).all()
        daily_party_map = {d.reservation_id: d.party_type for d in daily_rows}

    # 3. 유효 party_type 계산 → 타겟 집합
    target_ids: set[int] = set()
    for r in reservations:
        effective = daily_party_map.get(r.id) or r.party_type
        if effective in PARTY3_TYPES:
            target_ids.add(r.id)

    # 4. 기존 칩 조회
    existing_chips = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.schedule_id == schedule.id,
        ReservationSmsAssignment.date == date,
    ).all()
    existing_ids = {c.reservation_id for c in existing_chips}

    # 5. 생성 (target - existing)
    tenant_id = get_session_tenant_id(db)
    created = 0
    for rid in (target_ids - existing_ids):
        db.add(ReservationSmsAssignment(
            reservation_id=rid,
            template_key=template_key,
            date=date,
            assigned_by='auto',
            schedule_id=schedule.id,
            sent_at=None,
            tenant_id=tenant_id,
        ))
        created += 1

    # 6. 삭제 (existing - target, 미발송만)
    deleted = 0
    for chip in existing_chips:
        if chip.reservation_id not in target_ids and chip.sent_at is None:
            db.delete(chip)
            deleted += 1

    if created or deleted:
        db.flush()

    diag(
        "party3_mms.reconcile.done",
        level="verbose",
        date=date,
        targets=len(target_ids),
        existing=len(existing_ids),
        created=created,
        deleted=deleted,
    )


def reconcile_party3_mms_for_reservation(
    db: Session, reservation_id: int, date: str
) -> None:
    """단건 처리: (reservation, date) 기준 party3 MMS 칩 재조정.

    reconcile_party3_mms 의 single-row 변형. mutation 후처리(예약/일자별 정보 변경,
    객실 배정 등) 에서 단일 예약의 칩만 즉시 정리하기 위함.
    """
    schedule = _find_schedule(db)
    if not schedule or not schedule.template or not schedule.template.is_active:
        return

    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        return

    # stay coverage 검사 (퇴실일 제외, 첫날/연박중간/NULL체크아웃/당일 모두 포함)
    check_in = res.check_in_date
    check_out = res.check_out_date
    in_stay = bool(check_in) and (
        check_in == date
        or (check_out and check_in <= date < check_out)
    )

    # 유효 party_type = DailyInfo override or Reservation.party_type
    daily = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date == date,
    ).first()
    effective = (daily.party_type if daily else None) or res.party_type

    is_target = (
        in_stay
        and res.status == ReservationStatus.CONFIRMED
        and effective in PARTY3_TYPES
    )

    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id == schedule.id,
    ).first()

    if is_target and not existing:
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
        db.flush()
        diag("party3_mms.single.created", level="verbose",
             res_id=reservation_id, date=date)
    elif (not is_target) and existing and existing.sent_at is None:
        db.delete(existing)
        db.flush()
        diag("party3_mms.single.deleted", level="verbose",
             res_id=reservation_id, date=date)
