#!/usr/bin/env bash
# Lifecycle migration lint — caller 회귀 차단.
#
# 검사 규칙:
#   1) RoomAssignment 직접 조작 (db.delete / db.query.delete / 인스턴스 생성)
#      → services/room_assignment.py + db/models.py 만 허용
#   2) shift_daily_records / reconcile_dates 직접 호출 (non-_ prefix)
#      → 단계 #20 후 private. 외부 호출 0건이어야 함
#
# 사용법:
#   bash backend/scripts/check_lifecycle_lint.sh
#   exit code 0=pass, 1=fail
#
# 참고: docs/plans/lifecycle-migration-plan.md

set -u

cd "$(dirname "$0")/.."

ERR=0

echo "[lint] 1. RoomAssignment 직접 조작 검사 (services/room_assignment.py 외부)..."
ra_hits=$(grep -rn -E "db\.delete\([^)]*RoomAssignment|db\.query\(RoomAssignment\)[^)]*\.delete|^[[:space:]]*RoomAssignment\(|=\s*RoomAssignment\(" app/ \
    --include="*.py" 2>/dev/null \
    | grep -v "app/services/room_assignment.py" \
    | grep -v "app/db/models.py" \
    | grep -v "__pycache__" || true)
if [ -n "$ra_hits" ]; then
    echo "❌ RoomAssignment 직접 조작 발견 (services/room_assignment.py + db/models.py 만 허용):"
    echo "$ra_hits"
    ERR=1
fi

echo "[lint] 2. non-private 함수 직접 호출 검사 (shift_daily_records / reconcile_dates)..."
for fn in shift_daily_records reconcile_dates; do
    fn_hits=$(grep -rn -E "\b${fn}\(" app/ --include="*.py" 2>/dev/null \
        | grep -v "app/services/room_assignment.py" \
        | grep -v "app/services/reservation_lifecycle.py" \
        | grep -v "__pycache__" || true)
    if [ -n "$fn_hits" ]; then
        echo "❌ '${fn}' 외부 호출 발견 (단계 #20 후 _${fn} 으로 private):"
        echo "$fn_hits"
        ERR=1
    fi
done

if [ $ERR -eq 0 ]; then
    echo "✅ lifecycle lint 통과"
fi
exit $ERR
