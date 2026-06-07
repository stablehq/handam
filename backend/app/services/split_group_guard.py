"""split 그룹(네이버 다객실 분할) 정합 가드 — 경보(P2) + 취소 자동 전파(P3, 플래그 OFF 기본).

책임:
  - 취소 고아 경보 (P2): primary 취소 시 CONFIRMED 잔존 sibling 탐지
    (diag critical + ActivityLog. 예약 데이터는 절대 변경하지 않음)
  - booking_count drift 감지 (P2): 네이버 incoming bc ↔ 그룹 총 row 수(취소 포함) 비교
  - 비분할 매핑 일반실의 bc 1→N 변경 감지 (P2)
  - 일 1회 dedup: 같은 그룹/같은 KST 날짜 중복 경보 억제 (5분 cron 스팸 방지)
  - 취소 자동 전파 (P3, SPLIT_CANCEL_MODE='auto' 전용 — 기본 'alert'):
    비보호 sibling 자동 취소 + lifecycle. 그룹당 1회 ledger 로 재전파 금지.
    부활(취소→확정)은 모드 무관 경보만 (자동 복구 금지 — lifecycle 복구 이벤트 부재)

호출처 3곳:
  - naver_sync Phase 2.8 (메인 commit 이후 격리 phase — 세션 오염 방지)
  - api/reservations DELETE soft-cancel / PATCH status=CANCELLED (dedup=False — 운영자 직접 행동)
  - scheduler/jobs.split_orphan_sweep_job (09:45 KST — sync fetch 윈도우 밖 취소의 마지막 그물)

설계 제약 (red-team 검증 — 위반 금지):
  - 트리거는 status 트랜지션이 아닌 술어식 (운영자 선취소 mef 핀 사각 방지)
  - drift 비교는 그룹 총 row 수 (alive 수 비교는 정리 직후부터 영구 오탐 —
    네이버는 취소건도 fetch 윈도우 동안 매번 재전송)
  - primary CONFIRMED 가드 (취소된 그룹의 drift 는 노이즈)

설계 문서: docs/plans/split-group-step-02-backfill-alerts.md (P2),
          docs/plans/split-group-step-03-auto-propagation.md (P3 — auto 전환 절차 §7 필독)
"""
import logging
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import KST
from app.db.models import (
    ActivityLog,
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
)
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)

# ActivityLog.activity_type — dedup 키 겸용
TYPE_CANCEL_ORPHAN = "split_cancel_orphan"
TYPE_BC_DRIFT = "split_bc_drift"
# P3: 전파 원장 (그룹당 1회 전파 ledger — 일일 dedup 아님) + 부활 경보
TYPE_CANCEL_PROPAGATED = "split_cancel_propagated"
TYPE_REACTIVATED = "split_reactivated_orphan"
# P0 cleanup 스크립트의 원장 type — ledger 조회에 OR 포함 (최종감사: 스크립트로
# 취소된 그룹의 sibling 을 운영자가 복구해도 재전파 금지가 동일하게 적용되도록)
TYPE_ORPHAN_CLEANUP = "split_orphan_cleanup"


def _kst_day_start_utc() -> datetime:
    """오늘 KST 자정 → naive UTC (ActivityLog.created_at 비교용)."""
    day_start_kst = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start_kst.astimezone(dt_timezone.utc).replace(tzinfo=None)


def _alerted_today(db: Session, activity_type: str, marker: str) -> bool:
    """오늘(KST) 같은 종류+같은 대상 경보가 이미 있으면 True (일 1회 dedup)."""
    return (
        db.query(ActivityLog.id)
        .filter(
            ActivityLog.activity_type == activity_type,
            ActivityLog.created_at >= _kst_day_start_utc(),
            ActivityLog.detail.like(f"%{marker}%"),
        )
        .first()
        is not None
    )


def find_confirmed_siblings(
    db: Session,
    split_group_id: str,
    exclude_id: int,
    min_checkout: str | None = None,
) -> list[Reservation]:
    """같은 split 그룹의 CONFIRMED sibling 조회.

    Defense-in-depth: 명시 tenant 필터 (naver_sync 칩 reconcile :328-336 패턴 —
    bypass 누수 시에도 cross-tenant 매칭 차단).
    min_checkout: sweep 용 — check_out >= 기준일 (NULL check_out 은 check_in 으로 폴백).
    """
    tid = get_session_tenant_id(db)
    if tid is None:
        raise RuntimeError("split_group_guard requires tenant context")
    q = db.query(Reservation).filter(
        Reservation.tenant_id == tid,
        Reservation.split_group_id == split_group_id,
        Reservation.id != exclude_id,
        Reservation.booking_source == "naver_split",
        Reservation.status == ReservationStatus.CONFIRMED,
    )
    siblings = q.all()
    if min_checkout:
        siblings = [
            s for s in siblings
            if str(s.check_out_date or s.check_in_date or "") >= min_checkout
        ]
    return siblings


def _group_row_count(db: Session, split_group_id: str) -> int:
    """그룹 총 row 수 — 취소 포함 (red-team: alive 수 비교는 영구 오탐)."""
    tid = get_session_tenant_id(db)
    return (
        db.query(func.count(Reservation.id))
        .filter(
            Reservation.tenant_id == tid,
            Reservation.split_group_id == split_group_id,
        )
        .scalar()
        or 0
    )


def _sent_chip_count(db: Session, reservation_id: int) -> int:
    return (
        db.query(func.count(ReservationSmsAssignment.id))
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.sent_at.isnot(None),
        )
        .scalar()
        or 0
    )


def alert_cancel_orphan(
    db: Session,
    primary: Reservation,
    source: str,
    dedup: bool = True,
    min_checkout: str | None = None,
) -> list[int]:
    """primary 취소 상태에서 CONFIRMED 잔존 sibling 경보. 반환: 경보된 sibling id 목록.

    alert-only — sibling 의 status/배정/칩을 변경하지 않는다 (P3 에서 auto 모드 확장).
    dedup=True: 같은 그룹 일 1회 (naver_sync 5분 cron / sweep 경로).
    dedup=False: 운영자 직접 행동 (DELETE/PATCH) — 즉시 발화.
    min_checkout: sweep 경로에서 게이트와 동일 기준 전달 — 과거 체크아웃 sibling 이
    경보 detail/카운트에 혼입되는 것 방지 (최종감사 반영).
    """
    if not primary.split_group_id:
        return []
    siblings = find_confirmed_siblings(
        db, primary.split_group_id, primary.id, min_checkout=min_checkout)
    if not siblings:
        return []
    # JSON 경계 포함 마커 — 부분문자열 충돌 방지 (nsplit-77 이 nsplit-777 에 매칭 금지)
    marker = f'"split_group_id": "{primary.split_group_id}"'
    if dedup and _alerted_today(db, TYPE_CANCEL_ORPHAN, marker):
        return []

    sibling_ids = [s.id for s in siblings]
    sent_chips = {s.id: _sent_chip_count(db, s.id) for s in siblings}
    diag(
        "split_guard.cancel_orphan",
        level="critical",
        primary_id=primary.id,
        naver_booking_id=primary.naver_booking_id,
        split_group_id=primary.split_group_id,
        sibling_ids=sibling_ids,
        sibling_sent_chips=sent_chips,
        source=source,
    )
    log_activity(
        db,
        type=TYPE_CANCEL_ORPHAN,
        title=(
            f"[{primary.customer_name}] 분할예약 취소 — 동반 객실 {len(sibling_ids)}건 "
            f"미취소 잔존 (수동 확인 필요)"
        ),
        detail={
            "primary_id": primary.id,
            "split_group_id": primary.split_group_id,
            "sibling_ids": sibling_ids,
            "sibling_sent_chips": sent_chips,
            "check_in_date": str(primary.check_in_date),
            "source": source,
        },
        status="failed",
        target_count=len(sibling_ids),
        failed_count=len(sibling_ids),
    )
    return sibling_ids


def alert_bc_drift(
    db: Session,
    reservation_id: int,
    split_group_id: str,
    incoming_bc: int,
    source: str,
) -> bool:
    """네이버 incoming booking_count ↔ 그룹 총 row 수 불일치 경보 (일 1회 dedup)."""
    primary = db.get(Reservation, reservation_id)
    # primary CONFIRMED 가드 — 취소된 그룹의 drift 는 노이즈 (red-team)
    if primary is None or primary.status != ReservationStatus.CONFIRMED:
        return False
    group_rows = _group_row_count(db, split_group_id)
    if incoming_bc == group_rows:
        return False
    # JSON 경계 포함 마커 — 부분문자열 충돌 방지
    if _alerted_today(db, TYPE_BC_DRIFT, f'"split_group_id": "{split_group_id}"'):
        return False

    diag(
        "split_guard.bc_drift",
        level="critical",
        primary_id=reservation_id,
        split_group_id=split_group_id,
        incoming_bc=incoming_bc,
        group_rows=group_rows,
        source=source,
    )
    log_activity(
        db,
        type=TYPE_BC_DRIFT,
        title=(
            f"[{primary.customer_name}] 분할예약 객실수 불일치 — 네이버 {incoming_bc}개 "
            f"vs 시스템 {group_rows}개 (수동 확인 필요)"
        ),
        detail={
            "primary_id": reservation_id,
            "split_group_id": split_group_id,
            "incoming_bc": incoming_bc,
            "group_rows": group_rows,
            "source": source,
        },
        status="failed",
    )
    return True


def alert_unsplit_multi(
    db: Session,
    reservation_id: int,
    incoming_bc: int,
    source: str,
) -> bool:
    """비분할 매핑 일반실의 bc 1→N 변경 경보 (일 1회 dedup).

    skip_existing(재분할 안 함) + is_split_managed freeze(bc 덮어쓰기 차단)로
    이중 침묵되던 '추가 결제된 객실의 무음 손실' 경로 — 자동 처리는 위험하므로
    감지·경보만 (수동 처리 유도, d15eeb8 정책의 가시화 버전).
    """
    res = db.get(Reservation, reservation_id)
    if res is None or res.status != ReservationStatus.CONFIRMED:
        return False
    # 후행 콤마 포함 — 부분문자열 충돌 방지 (id 7 이 77 에 매칭 금지).
    # detail dict 의 첫 키가 reservation_id 라 직렬화 시 항상 콤마가 뒤따름.
    marker = f'"reservation_id": {reservation_id},'
    if _alerted_today(db, TYPE_BC_DRIFT, marker):
        return False

    # 키 누락 분할 그룹 구분 — 이미 분할됐는데 split_group_id 만 없는 primary
    # (backfill ambiguous 잔존분)를 '분할 미적용'으로 오도하면 운영자가 수동으로
    # 객실을 추가 생성해 중복 예약이 됨 (최종감사 F: unsplit 오탐). 6-필드로
    # naver_split 동반 row 존재를 확인해 문구/kind 분기.
    tid = get_session_tenant_id(db)
    has_split_sibling = (
        db.query(Reservation.id)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.booking_source == "naver_split",
            Reservation.customer_name == res.customer_name,
            Reservation.phone == res.phone,
            Reservation.check_in_date == res.check_in_date,
            Reservation.check_out_date == res.check_out_date,
            Reservation.naver_biz_item_id == res.naver_biz_item_id,
        )
        .first()
        is not None
    )
    kind = "keyless_split_group" if has_split_sibling else "unsplit_multi"
    diag(
        "split_guard.unsplit_multi_bc",
        level="critical",
        reservation_id=reservation_id,
        naver_booking_id=res.naver_booking_id,
        incoming_bc=incoming_bc,
        kind=kind,
        source=source,
    )
    if has_split_sibling:
        title = (
            f"[{res.customer_name}] 분할그룹 키 누락 감지 — sibling 은 존재 "
            f"(분할은 적용됨, backfill ambiguous 잔존 — 수동 키 부여 필요. 객실 추가 생성 금지)"
        )
    else:
        title = (
            f"[{res.customer_name}] 예약 객실수 변경 감지 — 네이버 {incoming_bc}개 "
            f"(시스템은 1개, 분할 미적용. 수동 처리 필요)"
        )
    log_activity(
        db,
        type=TYPE_BC_DRIFT,
        title=title,
        detail={
            "reservation_id": reservation_id,
            "incoming_bc": incoming_bc,
            "kind": kind,
            "source": source,
        },
        status="failed",
    )
    return True


def _propagated_before(db: Session, split_group_id: str) -> bool:
    """이 그룹에 자동 전파가 이미 실행됐는가 — **전기간** ledger 조회 (일일 dedup 아님).

    재전파 금지 (red-team): 운영자가 전파 후 sibling 을 의도적으로 복구(부분취소)한
    경우, 술어식 트리거가 매 sync 재발화해도 ledger 가 재취소를 차단한다.
    잔존 CONFIRMED sibling 은 일일 경보 경로가 계속 노출 (운영자와 싸우지 않음).
    """
    marker = f'"split_group_id": "{split_group_id}"'
    return (
        db.query(ActivityLog.id)
        .filter(
            # cleanup 스크립트 원장도 포함 — 비-전파 취소(스크립트 처리) 그룹의
            # sibling 복구 후 재취소 방지 (최종감사 F: ledger 비대칭)
            ActivityLog.activity_type.in_((TYPE_CANCEL_PROPAGATED, TYPE_ORPHAN_CLEANUP)),
            ActivityLog.detail.like(f"%{marker}%"),
        )
        .first()
        is not None
    )


def _protection_signals(db: Session, sibling: Reservation) -> list[str]:
    """sibling 의 운영자 개입 신호 풀셋 — 하나라도 있으면 자동 전파 금지 (과보호가 안전 방향).

    red-team: mef name/phone 만으론 부족 — 체류 연장(check_out_pinned) 등 실투숙
    의도가 명백한 sibling 을 자동 취소하면 안 됨. mef 는 any-key 검사 (superset).
    """
    from app.db.models import RoomAssignment
    from app.services.chip_store import PROTECTED_ASSIGNED_BY

    signals = []
    mef = sibling.manually_edited_fields or {}
    for key in mef:
        signals.append(f"mef:{key}")
    if sibling.check_in_pinned:
        signals.append("check_in_pinned")
    if sibling.check_out_pinned:
        signals.append("check_out_pinned")
    if sibling.manually_extended_until:
        signals.append("manually_extended_until")
    if sibling.gender_manual:
        signals.append("gender_manual")
    has_manual_ra = (
        db.query(RoomAssignment.id)
        .filter(
            RoomAssignment.reservation_id == sibling.id,
            RoomAssignment.assigned_by == "manual",
        )
        .first()
        is not None
    )
    if has_manual_ra:
        signals.append("manual_room_assignment")
    has_protected_unsent_chip = (
        db.query(ReservationSmsAssignment.id)
        .filter(
            ReservationSmsAssignment.reservation_id == sibling.id,
            ReservationSmsAssignment.sent_at.is_(None),
            or_(
                ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
                # PR4 이전 레거시 실패칩 (assigned_by='auto' + send_status='failed')
                # — chip_store.py:43-45 가 동일 보호 대상으로 명시
                ReservationSmsAssignment.send_status == "failed",
            ),
        )
        .first()
        is not None
    )
    if has_protected_unsent_chip:
        signals.append("protected_unsent_chip")
    return signals


def propagate_cancel(db: Session, primary: Reservation, source: str) -> dict:
    """primary 취소를 비보호 CONFIRMED sibling 에 자동 전파 (SPLIT_CANCEL_MODE=auto 전용).

    동작 (sibling 별 SAVEPOINT 격리 — 1멤버 실패가 sync 전체를 죽이지 않음):
      1) 보호신호 풀셋 검사 → 있으면 skip (경보 강등)
      2) status=CANCELLED + cancelled_at 명시 복사 (CancelledZone 노출 필수 — red-team)
      3) on_status_cancelled (same_day=멤버 자신 check_in 기준) — RA 해제 + 미발송 칩
         삭제 (sent 칩 보존은 lifecycle 기존 정책)
      4) 수동 stay_group 이면 unlink + peer 칩 reconcile (lifecycle docstring :143 —
         caller 책임. naver_sync :828-846 패턴 동일 적용)
    그룹당 1회 ledger (TYPE_CANCEL_PROPAGATED) — 기전파 그룹은 경보로 강등.
    """
    from datetime import datetime as _dt

    from app.config import today_kst
    from app.services.reservation_lifecycle import on_status_cancelled

    if not primary.split_group_id:
        return {"propagated": [], "skipped": {}, "failed": [], "ledger_skip": False}
    # primary 실제 취소 상태 가드 — mef status 핀 '진짜 모순' 상태(naver_sync 가
    # 핀+CONFIRMED+네이버 cancelled 에서 '자동 보정 위험, 경보만'을 선언한 분기)에서는
    # 전파도 경보로 강등 (리뷰 HIGH finding — bc_drift 의 status 가드와 동일 패턴)
    if primary.status != ReservationStatus.CANCELLED:
        alert_cancel_orphan(db, primary, source=source, dedup=True)
        return {"propagated": [], "skipped": {}, "failed": [], "ledger_skip": False}
    today_str = today_kst()
    # min_checkout=today — 과거 체류 sibling 은 전파 제외 (발송/배정 실위험이 없고,
    # from_date 수동 sync 가 과거 RA 이력을 소급 삭제하는 것 방지. sweep 정책과 대칭 —
    # 최종감사 F: 과거 체류 가드 부재). 과거분은 경보 경로가 가시화.
    siblings = find_confirmed_siblings(
        db, primary.split_group_id, primary.id, min_checkout=today_str)
    if not siblings:
        return {"propagated": [], "skipped": {}, "failed": [], "ledger_skip": False}

    if _propagated_before(db, primary.split_group_id):
        # 재전파 금지 — 잔존 sibling 은 일일 경보로만 노출
        alert_cancel_orphan(db, primary, source=source, dedup=True)
        return {"propagated": [], "skipped": {}, "failed": [], "ledger_skip": True}

    propagated: list[int] = []
    skipped: dict[int, list[str]] = {}
    failed: list[int] = []

    for sib in siblings:
        signals = _protection_signals(db, sib)
        if signals:
            skipped[sib.id] = signals
            continue
        savepoint = db.begin_nested()
        try:
            sib.status = ReservationStatus.CANCELLED
            # cancelled_at 명시 복사 — 누락 시 CancelledZone 비노출 + paired-state
            # invariant (CANCELLED ⇔ cancelled_at NOT NULL) 위반 (red-team)
            sib.cancelled_at = primary.cancelled_at or _dt.now(KST).replace(tzinfo=None)
            is_same_day = (str(sib.check_in_date or "") == today_str)
            on_status_cancelled(db, sib, same_day=is_same_day)
            # 수동 stay_group unlink + peer 칩 — caller 책임 (naver_sync 패턴)
            if sib.stay_group_id:
                from app.services.consecutive_stay import unlink_from_group
                from app.services.reconcile import reconcile_all_chips
                peer_ids = [
                    r.id for r in db.query(Reservation).filter(
                        Reservation.stay_group_id == sib.stay_group_id,
                        Reservation.id != sib.id,
                    ).all()
                ]
                unlink_from_group(db, sib.id)
                if peer_ids:
                    db.flush()
                    for peer_id in peer_ids:
                        try:
                            reconcile_all_chips(db, peer_id)
                        except Exception as e:
                            logger.warning(
                                f"propagate_cancel peer reconcile failed: res={peer_id} err={e}")
            savepoint.commit()
            propagated.append(sib.id)
        except Exception as e:
            savepoint.rollback()
            failed.append(sib.id)
            logger.warning(f"propagate_cancel sibling failed: res={sib.id} err={e}")

    diag(
        "split_guard.cancel_propagated",
        level="critical",
        primary_id=primary.id,
        naver_booking_id=primary.naver_booking_id,
        split_group_id=primary.split_group_id,
        propagated=propagated,
        skipped=skipped,
        failed=failed,
        source=source,
    )
    # ledger 기록 — 부분 skip/실패여도 그룹당 1회 (잔존은 일일 경보가 담당).
    # 단 전원 failed(transient DB 오류 등)면 ledger 미기록 → 다음 sync 자연 재시도
    # (일시 오류 1회가 그룹 자동전파를 영구 차단하지 않도록 — 최종감사 반영)
    if not (propagated or skipped):
        if failed:
            alert_cancel_orphan(db, primary, source=source, dedup=False)
        return {"propagated": [], "skipped": {}, "failed": failed, "ledger_skip": False}
    log_activity(
        db,
        type=TYPE_CANCEL_PROPAGATED,
        title=(
            f"[{primary.customer_name}] 분할예약 취소 자동 전파 — "
            f"취소 {len(propagated)}건"
            + (f", 보호 skip {len(skipped)}건" if skipped else "")
            + (f", 실패 {len(failed)}건" if failed else "")
        ),
        detail={
            "primary_id": primary.id,
            "split_group_id": primary.split_group_id,
            "propagated": propagated,
            "skipped": skipped,
            "failed": failed,
            "source": source,
        },
        status="success" if not (skipped or failed) else "failed",
        target_count=len(siblings),
        success_count=len(propagated),
        failed_count=len(skipped) + len(failed),
    )
    # skip/실패 잔존 sibling 즉시 가시화 — dedup=False (전파는 그룹당 1회뿐이라
    # 스팸 없음. 당일 sweep 선행 경보에 먹히지 않게 — 리뷰 finding 반영)
    if skipped or failed:
        alert_cancel_orphan(db, primary, source=source, dedup=False)
    return {"propagated": propagated, "skipped": skipped, "failed": failed,
            "ledger_skip": False}


def alert_reactivated_orphan(db: Session, primary: Reservation, source: str) -> bool:
    """부활 경보 — primary 가 CANCELLED→CONFIRMED 전이했는데 그룹에 CANCELLED sibling 잔존.

    자동 부활 전파는 금지 (lifecycle 에 칩/배정 복구 이벤트 부재 — red-team).
    전이 기반 트리거 (술어식이면 '운영자가 sibling 만 의도적으로 취소한 정상 상태'를
    영구 경보하게 됨). 일일 dedup.
    """
    if not primary.split_group_id:
        return False
    tid = get_session_tenant_id(db)
    cancelled_sibs = (
        db.query(Reservation)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.split_group_id == primary.split_group_id,
            Reservation.id != primary.id,
            Reservation.booking_source == "naver_split",
            Reservation.status == ReservationStatus.CANCELLED,
        )
        .all()
    )
    if not cancelled_sibs:
        return False
    marker = f'"split_group_id": "{primary.split_group_id}"'
    if _alerted_today(db, TYPE_REACTIVATED, marker):
        return False

    sib_ids = [s.id for s in cancelled_sibs]
    diag(
        "split_guard.reactivated_orphan",
        level="critical",
        primary_id=primary.id,
        split_group_id=primary.split_group_id,
        cancelled_sibling_ids=sib_ids,
        source=source,
    )
    log_activity(
        db,
        type=TYPE_REACTIVATED,
        title=(
            f"[{primary.customer_name}] 분할예약 부활 감지 — 동반 객실 {len(sib_ids)}건은 "
            f"취소 상태 (배정/칩 자동 복구 안 됨, 수동 확인 필요)"
        ),
        detail={
            "primary_id": primary.id,
            "split_group_id": primary.split_group_id,
            "cancelled_sibling_ids": sib_ids,
            "source": source,
        },
        status="failed",
    )
    return True


def sweep_orphan_groups(db: Session, today_str: str) -> dict:
    """일일 정합 sweep — 취소 primary(키 보유) × CONFIRMED sibling(check_out>=today).

    sync 경로 경보는 네이버 fetch 윈도우(REGDATE 1일 + USEDATE 오늘~내일)를
    벗어난 취소를 놓칠 수 있음 — 이 sweep 이 마지막 그물.
    dedup 은 alert_cancel_orphan(dedup=True)와 공유 → sync 경보와 같은 날 중복 억제.
    """
    cancelled_primaries = (
        db.query(Reservation)
        .filter(
            Reservation.booking_source != "naver_split",
            Reservation.split_group_id.isnot(None),
            Reservation.status == ReservationStatus.CANCELLED,
        )
        .all()
    )
    groups_scanned = 0
    groups_alerted = 0
    sibling_total = 0
    for primary in cancelled_primaries:
        groups_scanned += 1
        siblings = find_confirmed_siblings(
            db, primary.split_group_id, primary.id, min_checkout=today_str
        )
        if not siblings:
            continue
        # min_checkout 전달 — 게이트와 경보 내용의 기준 일치 (과거 체크아웃 sibling
        # 이 detail/카운트에 혼입 금지 — 최종감사 반영)
        alerted = alert_cancel_orphan(
            db, primary, source="sweep", dedup=True, min_checkout=today_str)
        if alerted:
            groups_alerted += 1
            sibling_total += len(alerted)

    result = {
        "groups_scanned": groups_scanned,
        "groups_alerted": groups_alerted,
        "siblings_alerted": sibling_total,
    }
    diag("split_guard.sweep", level="verbose", today=today_str, **result)
    return result
