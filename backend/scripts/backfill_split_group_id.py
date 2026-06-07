"""기존 naver_split 그룹에 split_group_id 소급 부여 (split-group P2 backfill).

P1(cf 022_add_split_group_id)이 신규 split 에만 키를 기록하므로, 기존 그룹
(소급분할 52건 코호트 포함)을 6-필드 휴리스틱으로 연결한다.

휴리스틱 (red-team 검증 제약):
  - 6-필드: (tenant, customer_name, phone, check_in_date, check_out_date, naver_biz_item_id)
  - created_at 사용 금지 — 소급분할 코호트는 sibling created_at=마이그레이션
    실행시각(2026-04-26)이라 시간창 매칭이 구조적으로 무효
  - status 무필터 — 취소 그룹도 연결해야 sweep/dedup 이 동작
  - ambiguous(후보 0 또는 2+) 자동 기록 금지 — 리포트만 (오연결 시 P3 자동취소가
    엉뚱한 예약을 취소할 수 있음)

사용:
  python -m scripts.backfill_split_group_id           # dry-run (기본)
  python -m scripts.backfill_split_group_id --apply   # 실제 기록

멱등: split_group_id 이미 있는 sibling 은 skip. 재실행 안전.
보고 규약: [tid=N] res=XXX (예약자 단독 res_id 노출 금지).
설계 문서: docs/plans/split-group-step-02-backfill-alerts.md
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import session_bypass, session_for_tenant  # noqa: E402
from app.db.models import Reservation, Tenant  # noqa: E402


def backfill_tenant(db, tenant, apply: bool) -> dict:
    siblings = (
        db.query(Reservation)
        .filter(
            Reservation.booking_source == "naver_split",
            Reservation.split_group_id.is_(None),
        )
        .all()
    )
    linked = 0
    ambiguous = []
    for sib in siblings:
        candidates = (
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
        if len(candidates) != 1:
            ambiguous.append((sib, len(candidates)))
            print(
                f"  AMBIGUOUS [tid={tenant.id}] sibling res={sib.id} "
                f"({sib.customer_name}, {sib.check_in_date}~{sib.check_out_date}) "
                f"— primary 후보 {len(candidates)}개 → 수동 검토 필요"
            )
            continue
        primary = candidates[0]
        gid = f"nsplit-{primary.naver_booking_id}"
        action = "WOULD LINK" if not apply else "LINKED"
        print(
            f"  {action} [tid={tenant.id}] sibling res={sib.id} ↔ "
            f"primary res={primary.id} ({sib.customer_name}, {sib.check_in_date}) "
            f"→ {gid}"
        )
        if apply:
            sib.split_group_id = gid
            # primary 는 다른 sibling 이 먼저 키를 줬을 수 있음 — 같은 값이면 무해 (멱등)
            primary.split_group_id = gid
        linked += 1

    return {"siblings_scanned": len(siblings), "linked": linked, "ambiguous": len(ambiguous)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="실제 기록 (기본: dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== split_group_id backfill ({mode}) ===")

    bypass = session_bypass()
    try:
        tenants = bypass.query(Tenant).filter(Tenant.is_active == True).all()  # noqa: E712
    finally:
        bypass.close()

    totals = {"siblings_scanned": 0, "linked": 0, "ambiguous": 0}
    for tenant in tenants:
        db = session_for_tenant(tenant.id)
        try:
            print(f"[tid={tenant.id}] {tenant.slug}:")
            result = backfill_tenant(db, tenant, apply=args.apply)
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
    # 실행 기록 diag — 서버 diag 로그에서 backfill 수행 여부/결과 추적 (split-group P2)
    from app.diag_logger import diag
    diag("split_guard.backfill_run", level="info", apply=args.apply, **totals)
    if totals["ambiguous"]:
        print("⚠️  ambiguous 건은 자동 기록하지 않았습니다 — 위 목록을 수동 검토하세요.")
    if not args.apply:
        print("dry-run 이었습니다. 실제 기록은 --apply 로 재실행.")


if __name__ == "__main__":
    main()
