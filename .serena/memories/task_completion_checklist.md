# Task Completion Checklist

작업을 "완료"로 보고하기 전에 다음을 확인할 것.

## 1. 빌드/타입 체크
- **Frontend 변경**: `cd frontend && npm run build` 통과 여부 확인 (tsc 가 함께 돌아감 — 타입 에러 캐치).
- **Backend 변경**: 최소한 `python -c "from app.main import app"` 또는 서버를 한 번 띄워서 import 에러 확인.

## 2. 테스트
- 영향 범위에 해당하는 pytest 실행:
  ```bash
  cd backend && source venv/bin/activate
  pytest tests/unit              # 빠르게 체크
  pytest tests/integration       # 핵심 비즈니스 흐름 변경 시
  pytest -k "<관련 키워드>"
  ```
- 새 기능/버그 수정에는 가능하면 unit 또는 integration 테스트 추가.

## 3. DB 스키마 변경 시
- 모델(`backend/app/db/models.py`)을 바꿨다면:
  - 데모 환경: `rm -f backend/sms.db && python -m app.db.seed`
  - 운영 의도면 Alembic 마이그레이션 추가: `alembic revision --autogenerate -m "..."` → 검토 → `alembic upgrade head`
- `TenantMixin` 적용 여부 확인 (User/Tenant 제외 모든 신규 모델에 필수).

## 4. UI/Frontend 변경 시
- 가능하면 `npm run dev` 띄워 브라우저에서 골든 패스 + 엣지 케이스 확인.
- 다크 모드(`dark:` variant) 적용 여부.
- Toss/Flowbite 디자인 시스템 규칙(버튼 size/color, 간격, 라운딩) 준수.
- 브라우저 테스트가 불가하면 명시적으로 "수동 테스트 미실시" 라고 알릴 것.

## 5. 멀티테넌트 안전성
- 새 라우터/쿼리에서 `get_tenant_scoped_db` 사용했는지 확인.
- 전역 작업이라면 `bypass_tenant_filter` 로 명시적으로 우회했는지 확인.
- 새 모델은 `tenant_id` 필터가 자동 적용되는지 (TenantMixin 상속) 확인.

## 6. ActivityLog
- 사용자/스케줄러가 트리거하는 의미 있는 액션이라면 `log_activity(...)` 호출 추가.

## 7. 린트/포맷
- 현재 레포에는 강제 린터/포매터 미설정. 따로 도입하지 말고, 기존 스타일에 맞출 것.
- 새 도구(black, ruff, prettier 등)를 도입하려면 사용자에게 먼저 확인.

## 8. 커밋
- 사용자가 명시적으로 요청했을 때만 커밋. 자동 커밋 금지.
- 메시지 스타일은 `git log --oneline -20` 으로 최근 컨벤션 참고 (예: `feat(scope): ...`, `fix(scope): ...`, 한국어 병기).

## 9. 보고
- 한 줄 요약 + 무엇이 변했는지/다음에 필요한 게 무엇인지.
- 검증 못 한 부분은 정직하게 명시.
