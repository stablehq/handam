"""ReservationLifecycle — 예약 라이프사이클 이벤트별 후처리 게이트웨이 (스켈레톤).

본 모듈은 단계 #2 시점에서는 어디서도 호출되지 않는다. 5개 lifecycle 이벤트
함수의 시그니처만 노출하여 후속 PR (#5~#9 구현, #10~#19 caller 전환) 의
이름 충돌 / signature drift 를 사전 방지한다.

각 함수는 "Reservation 의 라이프사이클 이벤트가 발생했을 때 따라와야 할 후처리
(shift_daily_records, reconcile_dates, reconcile_all_chips, invariant check 등)
를 일관된 순서로 호출" 한다는 책임을 가진다.

참고: docs/plans/room-assignment-pipeline-design.md
      docs/plans/lifecycle-migration-plan.md
      docs/plans/lifecycle-step-02-lifecycle-skeleton.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.db.models import Reservation


def on_dates_changed(
    db: "Session",
    reservation: "Reservation",
    old_check_in: str,
    old_check_out: str,
) -> None:
    """체크인/체크아웃 변경 직후 호출.

    호출 순서 (caller 책임이었던 후처리를 단일 함수로 통합):
      1) shift_daily_records — PartyCheckin / ReservationDailyInfo 평행이동
      2) reconcile_dates       — 범위 밖 RA 삭제 + 누락 날짜 INSERT + push-out
      3) reconcile_all_chips   — 5종 칩 전부 재계산 (sync_sms_tags + surcharge +
                                  party3 + room_upgrade_promise + _review)

    caller 가 reservation 의 새 check_in/out 값을 이미 적용한 상태에서 호출.
    old_check_in / old_check_out 은 shift_daily_records 가 평행이동 계산에 사용.

    caller (단계 #10/#13/#16/#17): reservations.py PUT, naver_sync._update,
    extend_stay, _do_reduce_extension.
    """
    from app.services.room_assignment import _shift_daily_records, _reconcile_dates
    from app.services.reconcile import reconcile_all_chips

    _shift_daily_records(db, reservation, old_check_in, old_check_out)
    _reconcile_dates(db, reservation)
    reconcile_all_chips(db, reservation.id)


def on_constraints_changed(
    db: "Session",
    reservation: "Reservation",
    changed_fields: set[str],
    *,
    actor: str,
) -> None:
    """성별/인원/section 등 invariant 영향 필드 변경 직후 호출.

    호출 순서:
      1) check_assignment_validity — RA 가 새 인원/성별 invariant 만족하는지 검사
      2) (위반 시) unassign_room — 위반 future 날짜의 RA 해제 + log_activity + critical diag
      3) reconcile_all_chips — 5종 칩 전부 재계산

    caller (단계 #11/#14): reservations.py PUT, naver_sync._update.

    Args:
        actor: log_activity 의 created_by 값. caller 가 자기 식별자 전달
               (예: current_user.username 또는 "naver_sync").
    """
    import logging
    from datetime import datetime, timedelta
    from app.config import KST
    from app.services.room_assignment_invariants import check_assignment_validity
    from app.services.room_assignment import unassign_room
    from app.services.reconcile import reconcile_all_chips
    from app.services.activity_logger import log_activity
    from app.diag_logger import diag

    logger = logging.getLogger(__name__)

    try:
        invalid_dates = check_assignment_validity(db, reservation)
    except Exception as e:
        logger.warning(f"check_assignment_validity failed: {e}")
        invalid_dates = []

    if invalid_dates:
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        future_invalid = sorted([d for d in invalid_dates if d > today_str])
        if future_invalid:
            end_d = (
                datetime.strptime(future_invalid[-1], "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            unassign_room(
                db, reservation.id,
                from_date=future_invalid[0],
                end_date=end_d,
            )
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 제약 위반 배정 해제 ({len(future_invalid)}일)",
                detail={
                    "reservation_id": reservation.id,
                    "invalid_dates": future_invalid,
                    "trigger": "constraint_field_change",
                    "changed_fields": sorted(changed_fields),
                },
                created_by=actor,
            )
            diag(
                "invariant.violation_detected",
                level="critical",
                reservation_id=reservation.id,
                invalid_dates=future_invalid,
            )

    reconcile_all_chips(db, reservation.id)


def on_status_cancelled(
    db: "Session",
    reservation: "Reservation",
    *,
    same_day: bool,
) -> None:
    """status=CANCELLED 변경 직후 호출. cc1 (당일) / cc2 (사전) 분기 흡수.

    동작:
      - same_day=True (cc1, 당일 취소):
          1) 오늘 이후 affected_dates 수집 (idempotent guard)
          2) unassign_dates 로 RA 삭제 + bed_order 재정렬 + 칩 cleanup
          3) reservation.room_number/room_password = None
          4) critical diag
      - same_day=False (cc2, 사전 취소):
          1) clear_all_for_reservation — 전체 RA 삭제 + denormalized 필드 정리
      - 공통: ReservationSmsAssignment 의 미발송 칩 (sent_at IS NULL) 삭제 + verbose diag

    caller (단계 #15): naver_sync cc1/cc2 분기.

    Note: stay_group unlink + peer sync_sms_tags 는 caller 책임 (부모 계획 Q2).
    """
    from datetime import datetime
    from app.config import KST
    from app.db.models import RoomAssignment, ReservationSmsAssignment
    from app.db.tenant_context import get_session_tenant_id
    from app.services import room_assignment
    from app.diag_logger import diag

    tid = get_session_tenant_id(db)

    if same_day:
        # cc1: 당일 취소 — 오늘 이후 affected_dates 수집
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        affected_dates = [
            ra.date for ra in db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id == reservation.id,
                RoomAssignment.tenant_id == tid,
                RoomAssignment.date >= today_str,
            ).all()
        ]
        # Idempotent guard: 이미 정리된 cancelled 예약이면 매 sync 무용한 delete 회피
        if affected_dates:
            room_assignment.unassign_dates(db, reservation.id, affected_dates)
            reservation.room_number = None
            reservation.room_password = None
            diag(
                "naver_sync.same_day_cancel",
                level="critical",
                reservation_id=reservation.id,
                dates=affected_dates,
            )
    else:
        # cc2: 사전 취소 — 전체 배정 해제
        room_assignment.clear_all_for_reservation(db, reservation.id)

    # 공통: 미발송 SMS 칩 삭제 (sent 보호)
    _cancel_deleted = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.tenant_id == reservation.tenant_id,
        ReservationSmsAssignment.reservation_id == reservation.id,
        ReservationSmsAssignment.sent_at.is_(None),
    ).delete(synchronize_session='fetch')
    diag(
        "naver_sync.cancel_chip_cleanup",
        level="verbose",
        res_id=reservation.id,
        tenant_id=reservation.tenant_id,
        deleted=_cancel_deleted,
    )


def on_room_assigned(
    db: "Session",
    reservation: "Reservation",
    pushed_out: Optional[list[dict]] = None,
) -> None:
    """assign_room 직후 호출. push-out 된 예약의 칩까지 재계산.

    동작:
      1) reconcile_all_chips(db, reservation.id) — 본인 칩 재계산
      2) for p in pushed_out: reconcile_all_chips(db, p["reservation_id"]) — push-out 예약별 재계산

    pushed_out 의 각 dict 구조 (assign_room 반환값의 두 번째 tuple element):
      {"reservation_id": int, "customer_name": str, "date": str, "cause": str}

    caller (단계 #16/#18/#19): extend_stay, reservations_room.py assign PUT, room_auto_assign.
    """
    from app.services.reconcile import reconcile_all_chips

    reconcile_all_chips(db, reservation.id)

    if pushed_out:
        seen_ids = set()
        for p in pushed_out:
            res_id = p.get("reservation_id")
            if res_id is not None and res_id not in seen_ids:
                seen_ids.add(res_id)
                reconcile_all_chips(db, res_id)


def on_reservation_deleted(
    db: "Session",
    reservation_id: int,
) -> None:
    """예약 삭제 (DELETE /reservations/{id}) 직후 호출.

    동작: 모든 연관 레코드 삭제 (FK 제약 + 깔끔 정리):
      1) clear_all_for_reservation — RoomAssignment 전체 + denormalized 필드
      2) ReservationSmsAssignment 전체 삭제 (sent/unsent 모두 — 예약 사라지므로)
      3) ReservationDailyInfo 전체 삭제
      4) PartyCheckin 전체 삭제

    caller (단계 #12): reservations.py delete_reservation.

    Note: stay_group unlink 와 db.delete(reservation) + commit + diag 는 caller 책임.
    """
    from app.db.models import ReservationSmsAssignment, ReservationDailyInfo, PartyCheckin
    from app.db.tenant_context import get_session_tenant_id
    from app.services.room_assignment import clear_all_for_reservation

    tid = get_session_tenant_id(db)

    clear_all_for_reservation(db, reservation_id)
    db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.tenant_id == tid,
    ).delete()
    db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.tenant_id == tid,
    ).delete()
    db.query(PartyCheckin).filter(
        PartyCheckin.reservation_id == reservation_id,
        PartyCheckin.tenant_id == tid,
    ).delete()
