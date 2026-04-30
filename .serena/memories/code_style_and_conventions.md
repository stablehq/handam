# Code Style & Conventions

## Backend (Python)
- **Python 3** + 표준 PEP8 스타일.
- **타입 힌트** 적극 사용 (예: `def get_sms_provider_for_tenant(tenant=None) -> SMSProvider:`).
- **docstring**: 함수/메서드 핵심 동작은 짧은 한 줄 docstring(영문 또는 한국어).
- **로깅**: 모듈 상단에 `logger = logging.getLogger(__name__)`. 사용자 메시지/에러 흐름은 한국어 + `[태그]` 접두사 자주 사용 (예: `"[SMS] testmode=False but ALIGO_API_KEY is empty — SMS will fail"`).
- **Naming**: snake_case 함수/변수, PascalCase 클래스. 모델은 `Reservation`, `MessageTemplate` 등 단수형.
- **SQLAlchemy 모델**: 모두 `TenantMixin` 적용 (User/Tenant 제외). 신규 모델 추가 시 같은 패턴 따를 것.
- **Pydantic schema**: API 라우터별 `*_schemas.py` 또는 라우터 파일 상단에 정의. 공유 스키마는 `app/api/shared_schemas.py`.
- **테넌트 격리**: 라우터에서 직접 DB 세션을 만들지 말고 `Depends(get_tenant_scoped_db)` 사용 (`backend/app/api/deps.py`). 전역 작업은 `bypass_tenant_filter` 컨텍스트 매니저로 명시적으로 우회.
- **ActivityLog**: 사용자/스케줄러 액션 후 `app.services.activity_logger.log_activity(...)` 호출이 표준 패턴.
- **DEMO_MODE**: 외부 API 호출 시 `app.factory` 의 provider factory를 통해 Mock/Real 분기. 직접 `httpx`/`anthropic` import 금지(provider 레이어 안에서만).

## Frontend (TypeScript / React)
- **컴포넌트**: 함수형 + Hooks. 페이지는 `src/pages/<Name>.tsx`, 재사용 컴포넌트는 `src/components/`.
- **State**: Zustand 스토어 (`src/stores/`). 전역은 auth/tenant 등 최소화.
- **Style**: Tailwind 유틸리티 + 디자인 시스템 클래스 (`page-title`, `stat-card`, `section-card`, `filter-bar`, …) — CLAUDE.md "Frontend Design Guidelines" 절 참조.
- **컴포넌트 라이브러리**: Flowbite React (Ant Design 사용 금지). Toss Invest 디자인 시스템.
- **아이콘**: lucide-react. 기본 크기 `h-3.5 w-3.5` (버튼 내부), `h-4 w-4` (독립 아이콘).
- **숫자**: `tabular-nums` 클래스 적용.
- **언어**: UI 텍스트와 샘플 데이터는 한국어.
- **역할 기반 라우팅**: `App.tsx` 에서 `SUPERADMIN > ADMIN > STAFF` 보호. STAFF 는 파티 체크인만 접근.
- **다크 모드**: 기본 지원. `dark:` variant 적용 필수.

## 공통
- **주석**: WHY 가 자명하지 않을 때만 작성. WHAT 은 식별자 이름으로 표현.
- **불필요한 호환 레이어/플래그 금지**: 사용하지 않는 코드는 제거.
- **에러 처리**: 시스템 경계(외부 API, 사용자 입력)에서만. 내부 코드/프레임워크 보장 영역은 신뢰.
