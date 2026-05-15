#!/usr/bin/env bash
# sync_sms_tags 호출 lint — 회귀 차단 (sync-sms-tags 통합 PR5).
#
# 검사 규칙:
#   sync_sms_tags() 직접 호출은 Group A (배치 최적화 의도) 만 허용.
#   외부에서 sync_sms_tags 만 호출하면 4종 칩 (surcharge/party3/upgrade*) 누락
#   회귀 위험 — reconcile_all_chips 사용 권장.
#
# Group A 화이트리스트 (배치 최적화 의도):
#   - services/reconcile.py        (reconcile_all_chips 의 1단계 — 정의상)
#   - services/room_auto_assign.py (직후 surcharge_batch + upgrade_batch 별도 호출)
#   - services/room_assignment.py  (dorm push-out 직후 surcharge 별도 처리)
#
# 사용법:
#   bash backend/scripts/check_sync_sms_tags_lint.sh
#   exit code 0=pass, 1=fail
#
# 참고: docs/plans/sync-sms-tags-consolidation-plan.md

set -u

cd "$(dirname "$0")/.."

ERR=0

echo "[lint] sync_sms_tags 외부 호출 검사 (Group A 화이트리스트 외)..."
hits=$(grep -rn -E "\bsync_sms_tags\s*\(" app/ \
    --include="*.py" 2>/dev/null \
    | grep -v "app/services/room_assignment.py" \
    | grep -v "app/services/reconcile.py" \
    | grep -v "app/services/room_auto_assign.py" \
    | grep -v "__pycache__" \
    | grep -v "def sync_sms_tags" \
    | grep -v "#" || true)

# 주석/문자열 안의 sync_sms_tags 참조는 grep -v "#" 로 대부분 걸러지지만,
# 라인 중간에 # 가 있을 수도 있음. 보수적으로 한 번 더 필터:
hits=$(echo "$hits" | grep -v "import sync_sms_tags" | grep -v "from app.services.room_assignment import.*sync_sms_tags" || true)

# import 만 하고 호출 안 하는 경우는 OK — 호출만 검사:
# 결과 라인에 sync_sms_tags(  형태가 있는 것만:
hits=$(echo "$hits" | grep -E "sync_sms_tags\s*\(" || true)

if [ -n "$hits" ]; then
    echo "❌ sync_sms_tags 외부 호출 발견 (reconcile_all_chips 사용 권장):"
    echo "$hits"
    echo ""
    echo "이유: sync_sms_tags 는 1종 칩만 reconcile. 4종 칩 (surcharge/party3/"
    echo "upgrade_promise/_review) 누락 회귀 위험. 외부 caller 는"
    echo "reconcile_all_chips 사용해 5종 통합 보장."
    echo ""
    echo "예외 (배치 최적화 의도) 는 위 화이트리스트에 추가 필요."
    ERR=1
fi

if [ $ERR -eq 0 ]; then
    echo "✅ sync_sms_tags 호출 lint 통과 (Group A 화이트리스트만 사용 중)"
fi
exit $ERR
