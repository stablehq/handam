#!/usr/bin/env bash
# Chip CRUD lint — 회귀 차단 (chip-store 마이그레이션 단계 #15).
#
# 검사 규칙:
#   1) ReservationSmsAssignment 직접 INSERT (db.add)
#      → services/chip_store.py + db/models.py 만 허용
#   2) ReservationSmsAssignment 직접 DELETE (db.query(...).delete())
#      → 동일 허용 목록
#
# UPDATE (setattr / attribute assignment) 은 lint 범위 외 — chip_store 가
# 다루지 않는 칩 상태 변경 (sent_at toggle, excluded mark 등) 은 caller 직접
# 처리.
#
# 사용법:
#   bash backend/scripts/check_chip_lint.sh
#   exit code 0=pass, 1=fail
#
# 참고: docs/plans/chip-store-migration-plan.md

set -u

cd "$(dirname "$0")/.."

ERR=0

echo "[lint] 1. ReservationSmsAssignment 직접 INSERT 검사..."
insert_hits=$(grep -rn -E "db\.add\(\s*ReservationSmsAssignment|=\s*ReservationSmsAssignment\(" app/ \
    --include="*.py" 2>/dev/null \
    | grep -v "app/services/chip_store.py" \
    | grep -v "app/db/models.py" \
    | grep -v "__pycache__" \
    | grep -v "ReservationSmsAssignment(TenantMixin" || true)
if [ -n "$insert_hits" ]; then
    echo "❌ ReservationSmsAssignment 직접 INSERT 발견 (chip_store.ensure_chip / record_sent / record_failed 사용 권장):"
    echo "$insert_hits"
    ERR=1
fi

echo "[lint] 2. ReservationSmsAssignment 직접 DELETE 검사..."
delete_hits=$(grep -rn -E "db\.query\(\s*ReservationSmsAssignment\s*\).*\.delete\b" app/ \
    --include="*.py" 2>/dev/null \
    | grep -v "app/services/chip_store.py" \
    | grep -v "__pycache__" || true)
if [ -n "$delete_hits" ]; then
    echo "❌ ReservationSmsAssignment 직접 DELETE 발견 (chip_store.remove_chip / delete_chips_for_* 사용 권장):"
    echo "$delete_hits"
    ERR=1
fi

if [ $ERR -eq 0 ]; then
    echo "✅ chip CRUD lint 통과"
fi
exit $ERR
