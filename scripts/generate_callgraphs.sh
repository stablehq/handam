#!/usr/bin/env bash
#
# 함수 단위 호출 그래프 자동 생성 스크립트
#
# 사용법:
#   bash scripts/generate_callgraphs.sh
#
# 사전 요건:
#   - graphviz (시스템): macOS `brew install graphviz`, Ubuntu `apt-get install graphviz`
#   - code2flow (Python): `pip install code2flow`
#
# 출력:
#   docs/pipelines/_generated/{scheduler,services,api,templates,all}.svg

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend/app"
OUT_DIR="$REPO_ROOT/docs/pipelines/_generated"

if ! command -v code2flow >/dev/null 2>&1; then
    echo "ERROR: code2flow가 설치되어 있지 않습니다." >&2
    echo "  pip install code2flow" >&2
    exit 1
fi

if ! command -v dot >/dev/null 2>&1; then
    echo "ERROR: graphviz(dot)이 설치되어 있지 않습니다." >&2
    echo "  macOS:  brew install graphviz" >&2
    echo "  Ubuntu: sudo apt-get install graphviz" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

gen() {
    local name="$1"; shift
    local src="$1"; shift
    echo "→ $name.svg ($src)"
    code2flow "$src" --output "$OUT_DIR/$name.svg" --language py "$@" || {
        echo "  WARN: $name 생성 실패 (건너뜀)" >&2
        return 0
    }
}

gen scheduler "$BACKEND/scheduler"
gen services  "$BACKEND/services"
gen api       "$BACKEND/api"
gen templates "$BACKEND/templates"
gen all       "$BACKEND" --no-trimming

echo ""
echo "완료. 결과물: $OUT_DIR"
echo "참고: 자동 생성 그래프는 노이즈가 많습니다. 핵심 파이프라인은 docs/pipelines/0X-*.md (Mermaid)를 보세요."
