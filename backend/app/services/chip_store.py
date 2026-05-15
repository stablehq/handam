"""ReservationSmsAssignment(=칩) CRUD 통합 게이트웨이.

본 모듈은 17개 파일에 분산된 칩 직접 조작(db.add / db.query.delete)을
단일 진입점으로 통합한다. ded670f 의 RoomAssignment 통합과 동형.

핵심 보호 (force=False 기본):
  - sent_at IS NOT NULL — 이미 발송된 칩은 절대 삭제 안 함
  - assigned_by IN ('manual', 'excluded', 'failed') — 운영자 의도 보호

force=True 는 명시적 lifecycle 이벤트에서만 사용:
  - on_status_cancelled (예약 취소 — 손님 안 옴)
  - on_reservation_deleted (예약 row 삭제 — cascade)

PR 분할:
  - PR1: ensure_chip + remove_chip (이 파일, 단계 #1~#3)
  - PR2: delete_chips_for_reservation + delete_chips_for_schedule (#4~#5)
  - PR3: record_sent + record_failed (#6)
  - PR4~PR10: caller 별 이주 (sms_tracking, surcharge, party3, ...)
  - PR11: CI lint (scripts/check_chip_lint.sh)

참고: docs/plans/chip-store-migration-plan.md
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy.exc import IntegrityError

from app.db.models import ReservationSmsAssignment
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# 자동 reconcile 에서 보호되는 assigned_by 값 (force=False 기본).
# OQ-1/OQ-5 결정 반영: manual (운영자 수동) / excluded (명시적 발송 제외) / failed (발송 실패 기록).
PROTECTED_ASSIGNED_BY = ('manual', 'excluded', 'failed')


def ensure_chip(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    date: str,
    assigned_by: str = "auto",
    schedule_id: Optional[int] = None,
    **extra,
) -> ReservationSmsAssignment:
    """Idempotent INSERT — 이미 존재하면 그대로 반환, 없으면 생성.

    매칭 키 (DB unique constraint `uq_res_sms_template_date`):
      (reservation_id, template_key, date)

    schedule_id 는 신규 생성 시에만 적용 (기존 칩의 schedule_id 갱신 안 함).
    tenant_id 는 ContextVar 에서 자동 주입.

    Race 처리: db.begin_nested() SAVEPOINT + IntegrityError catch + 재조회.

    Returns:
        ReservationSmsAssignment (신규 또는 기존).
    """
    # 1. 이미 존재하면 그대로 반환 (idempotent)
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )
    if existing:
        return existing

    # 2. 신규 생성 (race-safe SAVEPOINT)
    tenant_id = get_session_tenant_id(db)
    try:
        with db.begin_nested():
            chip = ReservationSmsAssignment(
                reservation_id=reservation_id,
                template_key=template_key,
                date=date,
                assigned_by=assigned_by,
                schedule_id=schedule_id,
                tenant_id=tenant_id,
                **extra,
            )
            db.add(chip)
        diag(
            "chip_store.ensure.created",
            level="verbose",
            res_id=reservation_id,
            template_key=template_key,
            date=date,
            assigned_by=assigned_by,
            schedule_id=schedule_id,
        )
        return chip
    except IntegrityError:
        # 동시 다른 트랜잭션이 먼저 만든 경우 — 재조회로 반환
        diag(
            "chip_store.ensure.race",
            level="warn",
            res_id=reservation_id,
            template_key=template_key,
            date=date,
        )
        existing = (
            db.query(ReservationSmsAssignment)
            .filter(
                ReservationSmsAssignment.reservation_id == reservation_id,
                ReservationSmsAssignment.template_key == template_key,
                ReservationSmsAssignment.date == date,
            )
            .first()
        )
        if existing is None:
            # IntegrityError 인데 재조회도 없는 비정상 — 알람
            diag(
                "chip_store.ensure.race_no_existing",
                level="critical",
                res_id=reservation_id,
                template_key=template_key,
                date=date,
            )
        return existing


def remove_chip(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    date: str,
    schedule_id: Optional[int] = None,
    force: bool = False,
) -> int:
    """단건 칩 삭제 (보호 가드 포함).

    매칭 키 (OQ-3 결정 반영):
      - schedule_id 가 있으면: (reservation_id, schedule_id, date)
        예) 평일/주말 동일 template_key 가 schedule 두 개에 연결될 때 한쪽만 정리.
      - schedule_id 가 None 이면: (reservation_id, template_key, date) + schedule_id IS NULL
        예) 운영자 수동 토글 칩 (schedule 없음).

    force=False (기본 — 자동 reconcile 용):
      - sent_at IS NULL 만 후보
      - assigned_by NOT IN ('manual', 'excluded', 'failed') 만 후보

    force=True (명시적 lifecycle — cancel/delete):
      - 가드 없음, 전부 삭제

    Returns:
        실제 삭제된 row 수.
    """
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
    )

    # 매칭 키 분기 (OQ-3)
    if schedule_id is not None:
        q = q.filter(ReservationSmsAssignment.schedule_id == schedule_id)
    else:
        q = q.filter(
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.schedule_id.is_(None),
        )

    # 보호 가드 (force=False 기본)
    if not force:
        q = q.filter(
            ReservationSmsAssignment.sent_at.is_(None),
            ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
        )

    deleted = q.delete(synchronize_session='fetch')

    if deleted:
        diag(
            "chip_store.remove.deleted",
            level="verbose",
            res_id=reservation_id,
            template_key=template_key,
            date=date,
            schedule_id=schedule_id,
            force=force,
            count=deleted,
        )

    return deleted


# ═══════════════════════════════════════════════════════════════════
# 스켈레톤 — 후속 PR 에서 구현
# ═══════════════════════════════════════════════════════════════════

def delete_chips_for_reservation(
    db: 'Session',
    *,
    reservation_id: int,
    dates: Optional[list[str]] = None,
    template_keys: Optional[list[str]] = None,
    schedule_ids: Optional[list[int]] = None,
    force: bool = False,
) -> int:
    """범위 삭제 — 예약 단위. PR2 (#4) 에서 구현.

    옵션 조합:
      - dates 만: 해당 날짜의 모든 칩
      - template_keys 만: 해당 템플릿의 모든 칩
      - schedule_ids 만: 해당 스케줄의 모든 칩
      - 다중 조합: AND 매칭
      - 옵션 전부 None: 예약의 모든 칩
    """
    raise NotImplementedError("PR2 (#4) 에서 구현")


def delete_chips_for_schedule(
    db: 'Session',
    *,
    schedule_id: int,
    force: bool = False,
) -> int:
    """스케줄 단위 일괄 삭제 (템플릿/스케줄 삭제·비활성 시). PR2 (#5) 에서 구현."""
    raise NotImplementedError("PR2 (#5) 에서 구현")


def record_sent(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    date: Optional[str] = None,
    sent_at=None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 성공 기록 — 기존 칩 update or 신규 INSERT.

    OQ-4 결정: 칩 없을 시 신규 INSERT 정상 흐름 (이벤트 SMS / race 대응).
    PR3 (#6) 에서 구현.
    """
    raise NotImplementedError("PR3 (#6) 에서 구현")


def record_failed(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    error: Optional[str] = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 실패 기록 — assigned_by='failed' 칩 생성/갱신.

    OQ-5 결정: 영구 보호 (운영자 개입 대기). PR3 (#6) 에서 구현.
    """
    raise NotImplementedError("PR3 (#6) 에서 구현")
