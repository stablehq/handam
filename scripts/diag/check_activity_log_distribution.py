#!/usr/bin/env python3
"""
Diag #5 — ActivityLog 분포 회귀 가드.

api/reservations.py 분리 후 log_activity() 호출이 누락되면 감사 로그가
조용히 비어버린다. 이 스크립트는 최근 24h 의 reservation_* activity_type
분포를 baseline 과 비교해 drift 를 감지한다.

사용법:
  # 1) baseline 캡처 (분리 전 또는 안정 운영 상태에서 1회)
  python3 scripts/diag/check_activity_log_distribution.py --capture-baseline

  # 2) 검증 (분리 후, 또는 매일)
  python3 scripts/diag/check_activity_log_distribution.py --check

  # 3) 단순 보기 (baseline 없이 현재 분포만)
  python3 scripts/diag/check_activity_log_distribution.py --show

baseline 파일: docs/diag-golden/activity_log_baseline.json
허용 drift: ±50% (±100% 처음 며칠은 표본 부족하니 --tolerance 로 조정)
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
# pydantic Settings 가 cwd 의 .env 를 읽으므로 backend 디렉토리로 이동.
# 그래야 backend/.env 의 운영 DATABASE_URL 이 적용됨 (DEMO_MODE=false 인 운영 환경).
os.chdir(BACKEND)

BASELINE_PATH = ROOT / "docs" / "diag-golden" / "activity_log_baseline.json"

# reservations.py 분리로 영향 받는 activity_type 들 (CRUD 파일에 남아 있어야 함)
# - room_move: PUT /{id} 에서 section 변경 시 발생 (reservations.py:299, 401)
# - naver_sync: POST /sync/naver 에서 발생 (reservations.py:489, 509)
# 분리 후 이 호출이 누락되면 두 type 의 카운트가 0 으로 떨어짐.
WATCHED_TYPES = {
    "room_move",
    "naver_sync",
}


def query_distribution(hours: int = 24) -> dict[str, int]:
    """최근 N시간 ActivityLog 의 type 별 카운트 반환 (cross-tenant)."""
    from sqlalchemy.exc import OperationalError
    from app.db.database import session_bypass
    from app.db.models import ActivityLog

    cutoff = datetime.now() - timedelta(hours=hours)
    counts: Counter[str] = Counter()
    db = session_bypass()
    try:
        try:
            rows = (
                db.query(ActivityLog.activity_type)
                .filter(ActivityLog.created_at >= cutoff)
                .all()
            )
        except OperationalError as e:
            if "no such table" in str(e).lower():
                print("⚠ activity_logs 테이블 없음 — DB 초기화 필요")
                print("   cd backend && python -m app.db.seed")
                sys.exit(2)
            raise
        for (t,) in rows:
            counts[t] += 1
    finally:
        db.close()
    return dict(counts)


def capture_baseline(hours: int = 24 * 7) -> None:
    """최근 N시간 분포를 baseline 으로 저장 (기본 7일)."""
    dist = query_distribution(hours=hours)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "window_hours": hours,
        "distribution": dist,
        "watched_types": sorted(WATCHED_TYPES),
        "_doc": (
            "Diag #5 baseline. reservations.py 분리 후 "
            "watched_types 의 발생 비율이 baseline ±tolerance 를 벗어나면 "
            "log_activity 호출 누락 의심."
        ),
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"✅ baseline 저장: {BASELINE_PATH}")
    print(f"   기간: 최근 {hours}h, 총 {sum(dist.values())} events, {len(dist)} types")
    for t in sorted(WATCHED_TYPES):
        print(f"   - {t}: {dist.get(t, 0)} 건")


def check(tolerance: float = 0.5, hours: int = 24) -> int:
    """현재 분포를 baseline 과 비교. 위반 건수 반환 (0 == OK)."""
    if not BASELINE_PATH.exists():
        print(f"⚠ baseline 없음: {BASELINE_PATH}")
        print("   먼저 --capture-baseline 으로 baseline 을 만드세요.")
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    base_dist: dict[str, int] = baseline["distribution"]
    base_hours: int = baseline.get("window_hours", 24 * 7)

    cur_dist = query_distribution(hours=hours)

    # baseline 은 7일치라 24h 비교를 위해 비율 환산
    scale = hours / base_hours

    violations: list[str] = []
    for t in sorted(WATCHED_TYPES):
        expected = base_dist.get(t, 0) * scale
        actual = cur_dist.get(t, 0)

        if expected < 1 and actual < 1:
            continue  # 둘 다 0 근처면 OK

        if expected < 1:
            # baseline 0 인데 현재 발생 — 새 type, 정보용으로만 노출
            print(f"  ℹ️  {t}: baseline 0 / current {actual} (신규 발생)")
            continue

        ratio = actual / expected
        lo, hi = 1 - tolerance, 1 + tolerance
        status = "✅" if lo <= ratio <= hi else "❌"
        msg = (
            f"  {status} {t}: expected≈{expected:.1f} actual={actual} "
            f"(ratio={ratio:.2f}, allowed [{lo:.2f}, {hi:.2f}])"
        )
        print(msg)
        if not (lo <= ratio <= hi):
            violations.append(t)

    print()
    if violations:
        print(f"❌ {len(violations)}개 type drift 감지: {violations}")
        print("   → log_activity() 호출이 누락됐는지 확인:")
        print("     grep -n log_activity backend/app/api/reservations*.py")
        return len(violations)
    print("✅ 모든 watched_types 정상 분포")
    return 0


def show(hours: int = 24) -> None:
    """현재 분포만 보기 (baseline 없이도 동작)."""
    dist = query_distribution(hours=hours)
    print(f"📊 최근 {hours}h ActivityLog 분포 (총 {sum(dist.values())} events)\n")
    for t, c in sorted(dist.items(), key=lambda x: -x[1]):
        marker = "★" if t in WATCHED_TYPES else " "
        print(f"  {marker} {t:<40s} {c:>6d}")
    print()
    print("★ = Diag #5 watched_types (분리 회귀 추적 대상)")


def main() -> int:
    p = argparse.ArgumentParser(description="Diag #5 — ActivityLog 분포 검증")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--capture-baseline", action="store_true",
                   help="현재 분포를 baseline 으로 저장")
    g.add_argument("--check", action="store_true",
                   help="baseline 과 비교 (drift 시 exit 1)")
    g.add_argument("--show", action="store_true",
                   help="현재 분포만 보기")
    p.add_argument("--hours", type=int, default=24,
                   help="조회 기간 (기본 24h)")
    p.add_argument("--baseline-hours", type=int, default=24 * 7,
                   help="baseline 캡처 기간 (기본 7일)")
    p.add_argument("--tolerance", type=float, default=0.5,
                   help="허용 drift 비율 (기본 0.5 == ±50%%)")
    args = p.parse_args()

    if args.capture_baseline:
        capture_baseline(hours=args.baseline_hours)
        return 0
    if args.show:
        show(hours=args.hours)
        return 0
    if args.check:
        return 0 if check(tolerance=args.tolerance, hours=args.hours) == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
