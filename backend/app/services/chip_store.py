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

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy.exc import IntegrityError

from app.db.models import Reservation, ReservationSmsAssignment
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# 자동 reconcile 에서 보호되는 assigned_by 값 (force=False 기본).
# OQ-1/OQ-5 결정 반영: manual (운영자 수동) / excluded (명시적 발송 제외) / failed (발송 실패 기록).
PROTECTED_ASSIGNED_BY = ('manual', 'excluded', 'failed')

# 발송 실패 흔적은 send_status='failed' 컬럼으로도 마크됨. PR4 (OQ-5) 이전 데이터는
# assigned_by='auto' + send_status='failed' 형태로 존재 — chip_reconciler 의 기존
# 가드가 이걸 보호. chip_store 도 동일 보호 (PR7 이주 호환).


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
            # 옛 데이터 호환 — assigned_by='auto' + send_status='failed' 케이스 보호
            (ReservationSmsAssignment.send_status.is_(None))
            | (ReservationSmsAssignment.send_status != 'failed'),
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
    """범위 삭제 — 예약 단위 + 옵션 필터 AND 매칭.

    옵션 조합:
      - 옵션 전부 None: 예약의 모든 칩
      - dates 만: 해당 날짜의 칩만
      - template_keys 만: 해당 템플릿의 칩만
      - schedule_ids 만: 해당 스케줄의 칩만
      - 다중 조합: AND 매칭

    force=False (자동 reconcile): sent_at IS NULL + assigned_by NOT IN PROTECTED.
    force=True (cancel/delete cascade): 가드 우회.

    Returns:
        실제 삭제된 row 수.
    """
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
    )
    if dates:
        q = q.filter(ReservationSmsAssignment.date.in_(dates))
    if template_keys:
        q = q.filter(ReservationSmsAssignment.template_key.in_(template_keys))
    if schedule_ids:
        q = q.filter(ReservationSmsAssignment.schedule_id.in_(schedule_ids))

    if not force:
        q = q.filter(
            ReservationSmsAssignment.sent_at.is_(None),
            ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
            # 옛 데이터 호환 — assigned_by='auto' + send_status='failed' 케이스 보호
            (ReservationSmsAssignment.send_status.is_(None))
            | (ReservationSmsAssignment.send_status != 'failed'),
        )

    deleted = q.delete(synchronize_session='fetch')

    if deleted:
        diag(
            "chip_store.delete_reservation.deleted",
            level="verbose",
            res_id=reservation_id,
            dates_count=len(dates) if dates else None,
            template_keys_count=len(template_keys) if template_keys else None,
            schedule_ids_count=len(schedule_ids) if schedule_ids else None,
            force=force,
            count=deleted,
        )

    return deleted


def delete_chips_for_schedule(
    db: 'Session',
    *,
    schedule_id: int,
    force: bool = False,
) -> int:
    """스케줄 단위 일괄 삭제 (template_schedule 비활성·삭제 시).

    tenant_id 는 ContextVar 가 자동 필터 (cross-tenant 우회는 caller 책임).

    Returns:
        실제 삭제된 row 수.
    """
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.schedule_id == schedule_id,
    )

    if not force:
        q = q.filter(
            ReservationSmsAssignment.sent_at.is_(None),
            ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
            # 옛 데이터 호환 — assigned_by='auto' + send_status='failed' 케이스 보호
            (ReservationSmsAssignment.send_status.is_(None))
            | (ReservationSmsAssignment.send_status != 'failed'),
        )

    deleted = q.delete(synchronize_session='fetch')

    if deleted:
        diag(
            "chip_store.delete_schedule.deleted",
            level="verbose",
            schedule_id=schedule_id,
            force=force,
            count=deleted,
        )

    return deleted


def _resolve_reservation_tenant(db: 'Session', reservation_id: int) -> int:
    """Reservation 의 실제 tenant_id + cross-tenant 시도 가시화.

    session.info['tenant_id'] 와 reservation 의 실제 tenant 가 다르면 critical
    diag 발화. 옵션 C Phase 6 강화 — silent cross-tenant 즉시 알람.

    구현 노트: `db` 자체에 임시 bypass 플래그 토글 — 별도 세션 분리 시 트랜잭션
    격리 (SQLite/PG) 로 inflight 데이터 안 보임 문제 회피. try/finally 로 플래그
    복원 보장. sms_tracking 의 SessionLocal() 분리 방식 대비 테스트·운영 모두 동작.

    Returns:
        실제 tenant_id. reservation 없으면 RuntimeError.
    """
    # 일시 bypass — 트랜잭션 inflight 데이터까지 조회 가능
    saved_bypass = db.info.get('bypass_tenant', False)
    db.info['bypass_tenant'] = True
    try:
        tid = (
            db.query(Reservation.tenant_id)
            .filter(Reservation.id == reservation_id)
            .scalar()
        )
    finally:
        db.info['bypass_tenant'] = saved_bypass

    if tid is None:
        raise RuntimeError(f"reservation {reservation_id} not found for chip_store")

    session_tid = db.info.get('tenant_id')
    if session_tid is not None and session_tid != tid:
        diag(
            "chip_store.cross_tenant_reservation",
            level="critical",
            session_tid=session_tid,
            reservation_id=reservation_id,
            reservation_tid=tid,
        )
    return tid


def record_sent(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    date: str = "",
    assigned_by: str = "auto",
    sent_at: Optional[datetime] = None,
    schedule_id: Optional[int] = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 성공 기록 — 기존 칩 update 또는 신규 INSERT.

    OQ-4: 칩 없을 시 신규 INSERT 정상 흐름 (이벤트 SMS / race / 외부 발송).
    cross-tenant 검증 포함 (sms_tracking 패턴 보존).

    Returns:
        ReservationSmsAssignment (갱신 또는 신규).
    """
    sent_at = sent_at or datetime.now(timezone.utc)
    res_tid = _resolve_reservation_tenant(db, reservation_id)

    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    diag(
        "chip_store.record_sent",
        level="verbose",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by=assigned_by,
        new_record=(existing is None),
    )

    if existing:
        existing.sent_at = sent_at
        existing.send_status = 'sent'
        existing.send_error = None
        return existing

    # OQ-4: 칩 없을 시 신규 INSERT — 이벤트 SMS / race / 외부 발송 흔적
    chip = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by=assigned_by,
        schedule_id=schedule_id,
        sent_at=sent_at,
        send_status='sent',
        tenant_id=res_tid,
        **extra,
    )
    db.add(chip)
    return chip


def record_failed(
    db: 'Session',
    *,
    reservation_id: int,
    template_key: str,
    error: Optional[str] = None,
    date: str = "",
    schedule_id: Optional[int] = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 실패 기록.

    OQ-5: assigned_by='failed' 강제 (기존 칩이 'auto'/'manual' 등이어도 'failed'
    로 승격) → 다음 자동 reconcile 의 PROTECTED_ASSIGNED_BY 가드가 보호.

    ⚠️ sms_tracking.record_sms_failed 와 silent 차이:
        - 기존: existing.assigned_by 그대로 (예: 'auto' 유지)
        - 신규: 'failed' 로 강제 승격
        → 다음 reconcile 가 '실패 흔적' 보존. OQ-5 의도된 fix.
        본 PR3 는 caller 0 — 변화 0. PR4 (sms_tracking 이주) 시 발효.

    cross-tenant 검증 포함.

    Returns:
        ReservationSmsAssignment (갱신 또는 신규).
    """
    error_str = (error or 'unknown')[:500]
    res_tid = _resolve_reservation_tenant(db, reservation_id)

    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    diag(
        "chip_store.record_failed",
        level="critical",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        error=error_str[:100],
        new_record=(existing is None),
        prior_assigned_by=(existing.assigned_by if existing else None),
    )

    if existing:
        existing.send_status = 'failed'
        existing.send_error = error_str
        existing.assigned_by = 'failed'  # OQ-5 fix
        return existing

    # OQ-5: 신규 INSERT 시 assigned_by='failed'
    chip = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by='failed',
        schedule_id=schedule_id,
        send_status='failed',
        send_error=error_str,
        tenant_id=res_tid,
        **extra,
    )
    db.add(chip)
    return chip
