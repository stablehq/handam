"""취소 고아 sibling 정리 (split-group P0) — primary 취소 + CONFIRMED sibling 잔존 해소.

용도:
  1) 과거 누적 사고분 정리 (예: [tid=2] res=6296 김하린 건)
  2) SPLIT_CANCEL_MODE=auto 전환 직전 재실행 (경보 관찰 기간 누적 고아 소급 —
     docs/plans/split-group-step-03-auto-propagation.md §7 절차 3)

탐지 2-pass:
  (a) 키 기반: 같은 split_group_id 의 primary CANCELLED × sibling CONFIRMED (backfill 후)
  (b) 무키 폴백: split_group_id NULL sibling 을 6-필드 휴리스틱으로 취소 primary 에 매칭
      (tenant, customer_name, phone, check_in, check_out, naver_biz_item_id —
       created_at 사용 금지, backfill 과 동일 제약)

apply 시 sibling 별:
  - 보호신호(split_group_guard._protection_signals) 있으면 skip + 수동검토 리포트
  - status=CANCELLED + cancelled_at 복사 → on_status_cancelled(same_day=자기 check_in 기준)
  - 수동 stay_group unlink + peer 칩 reconcile (lifecycle caller 책임)
  - 변경 전 스냅샷을 ActivityLog(type='split_orphan_cleanup') detail 에 원장 기록 (복원용)

사용:
  python -m scripts.cleanup_orphan_split_siblings           # dry-run (기본)
  python -m scripts.cleanup_orphan_split_siblings --apply

보고 규약: [tid=N] res=XXX.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import KST, today_kst  # noqa: E402
from app.db.database import session_bypass, session_for_tenant  # noqa: E402
from app.db.models import (  # noqa: E402
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    RoomAssignment,
    Tenant,
)
from app.services.activity_logger import log_activity  # noqa: E402
from app.services.split_group_guard import (  # noqa: E402
    TYPE_ORPHAN_CLEANUP,
    _protection_signals,
)


def _find_orphans(db) -> list[tuple[Reservation, Reservation, str]]:
    """(sibling, primary, 매칭방식) 목록. 키 기반 우선, 무키는 6-필드 폴백."""
    orphans = []
    seen_sibling_ids = set()

    # (a) 키 기반
    keyed_sibs = (
        db.query(Reservation)
        .filter(
            Reservation.booking_source == "naver_split",
            Reservation.split_group_id.isnot(None),
            Reservation.status == ReservationStatus.CONFIRMED,
        )
        .all()
    )
    for sib in keyed_sibs:
        primary = (
            db.query(Reservation)
            .filter(
                Reservation.split_group_id == sib.split_group_id,
                Reservation.booking_source != "naver_split",
                Reservation.status == ReservationStatus.CANCELLED,
            )
            .first()
        )
        if primary:
            orphans.append((sib, primary, "keyed"))
            seen_sibling_ids.add(sib.id)

    # (b) 무키 폴백 (backfill 미실행/ambiguous 잔존 대비)
    unkeyed_sibs = (
        db.query(Reservation)
        .filter(
            Reservation.booking_source == "naver_split",
            Reservation.split_group_id.is_(None),
            Reservation.status == ReservationStatus.CONFIRMED,
        )
        .all()
    )
    for sib in unkeyed_sibs:
        if sib.id in seen_sibling_ids:
            continue
        # status 무필터 후보 조회 — backfill 의 ambiguous 안전기준과 대칭 (최종감사 F:
        # CANCELLED 필터로 좁히면 '취소A + 재예약 확정B 공존' 상황에서 확정B 소속일 수
        # 있는 sibling 을 취소A 에 오귀속해 살아있는 예약을 취소할 수 있음)
        candidates_all = (
            db.query(Reservation)
            .filter(
                Reservation.booking_source != "naver_split",
                Reservation.naver_booking_id.isnot(None),
                Reservation.customer_name == sib.customer_name,
                Reservation.phone == sib.phone,
                Reservation.check_in_date == sib.check_in_date,
                Reservation.check_out_date == sib.check_out_date,
                Reservation.naver_biz_item_id == sib.naver_biz_item_id,
            )
            .all()
        )
        cancelled_cands = [c for c in candidates_all if c.status == ReservationStatus.CANCELLED]
        if len(candidates_all) == 1 and len(cancelled_cands) == 1:
            orphans.append((sib, cancelled_cands[0], "heuristic"))
        elif candidates_all:
            others = [f"res={c.id}({c.status})" for c in candidates_all]
            print(
                f"  AMBIGUOUS [tid={sib.tenant_id}] sibling res={sib.id} "
                f"({sib.customer_name}) — 후보 {len(candidates_all)}개 [{', '.join(others)}]"
                f" → 수동 검토 (재예약 공존 가능 — created_at 으로 귀속 판별)"
            )
    return orphans


def _snapshot(db, sib: Reservation) -> dict:
    """복원용 변경 전 스냅샷 (ActivityLog 원장에 JSON 기록)."""
    ras = db.query(RoomAssignment).filter(RoomAssignment.reservation_id == sib.id).all()
    chips = (
        db.query(ReservationSmsAssignment)
        .filter(ReservationSmsAssignment.reservation_id == sib.id)
        .all()
    )
    return {
        "status": str(sib.status),
        "cancelled_at": str(sib.cancelled_at) if sib.cancelled_at else None,
        "stay_group_id": sib.stay_group_id,
        "room_assignments": [
            {"date": r.date, "room_id": r.room_id, "assigned_by": r.assigned_by}
            for r in ras
        ],
        "unsent_chips": [
            {"template_key": c.template_key, "date": c.date, "assigned_by": c.assigned_by}
            for c in chips if c.sent_at is None
        ],
        "sent_chip_count": sum(1 for c in chips if c.sent_at is not None),
    }


def cleanup_tenant(db, tenant, apply: bool) -> dict:
    from app.services.reservation_lifecycle import on_status_cancelled

    orphans = _find_orphans(db)
    today_str = today_kst()
    cleaned = 0
    skipped = 0
    for sib, primary, how in orphans:
        signals = _protection_signals(db, sib)
        future = str(sib.check_in_date or "") >= today_str
        tag = "🔴미래" if future else "과거"
        if signals:
            skipped += 1
            print(
                f"  SKIP({','.join(signals)}) [tid={tenant.id}] sibling res={sib.id} "
                f"({sib.customer_name}, {sib.check_in_date}, {tag}) ← primary res={primary.id}"
            )
            continue
        action = "WOULD CANCEL" if not apply else "CANCELLED"
        print(
            f"  {action} [tid={tenant.id}] sibling res={sib.id} "
            f"({sib.customer_name}, {sib.check_in_date}~{sib.check_out_date}, {tag}, {how}) "
            f"← primary res={primary.id}"
        )
        if apply:
            before = _snapshot(db, sib)
            sib.status = ReservationStatus.CANCELLED
            sib.cancelled_at = primary.cancelled_at or datetime.now(KST).replace(tzinfo=None)
            is_same_day = (str(sib.check_in_date or "") == today_str)
            on_status_cancelled(db, sib, same_day=is_same_day)
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
                            print(f"    peer reconcile 실패 res={peer_id}: {e}")
            # TYPE_ORPHAN_CLEANUP 은 _propagated_before 의 ledger 조회에 OR 포함됨 —
            # 스크립트 정리 그룹의 sibling 복구 후 auto 재취소 방지 (최종감사 반영)
            log_activity(
                db,
                type=TYPE_ORPHAN_CLEANUP,
                title=f"[{sib.customer_name}] 고아 sibling 정리 — res={sib.id} 취소 처리",
                detail={
                    "sibling_id": sib.id,
                    "primary_id": primary.id,
                    "split_group_id": sib.split_group_id,
                    "match": how,
                    "before": before,  # 복원 원장
                },
                status="success",
                created_by="cleanup_script",
            )
        cleaned += 1
    return {"orphans": len(orphans), "cleaned": cleaned, "skipped_protected": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="실제 취소 처리 (기본: dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== 고아 sibling 정리 ({mode}) ===")

    bypass = session_bypass()
    try:
        tenants = bypass.query(Tenant).filter(Tenant.is_active == True).all()  # noqa: E712
    finally:
        bypass.close()

    totals = {"orphans": 0, "cleaned": 0, "skipped_protected": 0}
    for tenant in tenants:
        db = session_for_tenant(tenant.id)
        try:
            print(f"[tid={tenant.id}] {tenant.slug}:")
            result = cleanup_tenant(db, tenant, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            for k in totals:
                totals[k] += result[k]
            print(f"  → {result}")
        except Exception as e:
            db.rollback()
            print(f"  ERROR [tid={tenant.id}]: {e}")
        finally:
            db.close()

    print(f"=== 합계: {totals} ({mode}) ===")
    # 실행 기록 diag — 서버 diag 로그에서 정리 수행 여부/결과 추적 (split-group P0)
    from app.diag_logger import diag
    diag("split_guard.cleanup_run", level="info", apply=args.apply, **totals)
    if not args.apply:
        print("dry-run 이었습니다. 실제 처리는 --apply 로 재실행.")


if __name__ == "__main__":
    main()
