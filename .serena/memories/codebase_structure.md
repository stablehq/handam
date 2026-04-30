# Codebase Structure

## backend/app/
- `main.py` — FastAPI 앱, CORS, 보안 헤더 미들웨어, rate limit, SSE, 라우터 등록, startup/shutdown 훅
- `config.py` — Pydantic Settings (`DEMO_MODE`, DB URL, JWT, API 키 등)
- `factory.py` — 테넌트별 Provider Factory (SMS/예약). 항상 Real 구현; testmode 는 테넌트 DB 설정으로 제어
- `rate_limit.py` — slowapi 설정 + X-Forwarded-For 파싱
- `diag_logger.py` — 진단 로그 헬퍼

### `db/`
- `models.py` — 20+ SQLAlchemy 모델 (TenantMixin)
- `database.py` — 엔진/세션/init_db()
- `tenant_context.py` — ContextVar 기반 테넌트 격리 + `bypass_tenant_filter`
- `seed.py` — 초기 데이터 시딩

### `api/` (라우터)
실제 존재하는 모듈 (CLAUDE.md 보다 최신):
`auth.py`, `reservations.py`, `rooms.py`, `buildings.py`, `templates.py`,
`template_schedules.py`, `messages.py`, `events.py`, `event_sms.py`,
`dashboard.py`, `activity_logs.py`, `party_checkin.py`, `party_hosts.py`,
`daily_host.py`, `onsite_sales.py`, `onsite_auction.py`, `sales_report.py`,
`scheduler.py`, `settings.py`, `tenants.py`, `shared_schemas.py`, `deps.py`.

### `services/`
SMS 발송, 객실 배정, 활동 로깅, SSE 이벤트 버스, SMS 추적 등 비즈니스 로직.

### `scheduler/`
- `jobs.py` — APScheduler 설정 + 네이버 동기화/상태 로그 작업
- `template_scheduler.py` — 템플릿 스케줄 실행기 (필터링/발송)
- `schedule_manager.py` — TemplateSchedule ↔ APScheduler 트리거 동기화
- `room_auto_assign.py` — 자동 객실 배정 (도미토리 성별 잠금)

### `templates/`
- `renderer.py` — `{{변수}}` 치환 + 객실 비밀번호 생성
- `variables.py` — 템플릿 변수 계산 (ParticipantSnapshot 캐시)

### `auth/`
- `utils.py` — bcrypt 해싱 + JWT 생성/검증
- `dependencies.py` — FastAPI 인증 의존성 + 역할 가드

### `providers/` + `mock/` + `real/`
- `providers/base.py` — Protocol 정의 (SMSProvider, ReservationProvider, LLMProvider)
- `mock/` — 데모용 (sms, llm)
- `real/` — Aligo SMS, 네이버 예약, Claude LLM(stub)

### `_future/`
미래 구현 예정 모듈 (현재 기능에 영향 없음).

## backend/tests/
- `unit/` — 순수 유닛 테스트 (날짜 계산, 변수 치환, 토큰 등)
- `integration/` — 객실 배정·스케줄 발송·필터링 등 통합 시나리오
- `conftest.py` — 공용 fixture

## backend/alembic/
표준 Alembic 구조.

## frontend/src/
- `App.tsx` — React Router + 역할 보호
- `pages/` — 12개 페이지 (Dashboard, Reservations, RoomAssignment, RoomSettings, Templates, EventSms, ActivityLogs, PartyCheckin, SalesReport, Settings, UserManagement, Login)
- `components/` — Layout, FlowbiteTheme 등
- `services/api.ts` — Axios 클라이언트 (자동 토큰 갱신, X-Tenant-Id 헤더)
- `stores/` — Zustand (auth-store, tenant-store)
- `hooks/`, `lib/`
- `index.css` — 디자인 토큰 + 컴포넌트 클래스

## 기타
- `docker-compose.yml` / `docker-compose.prod.yml`
- `templates_schedules.xlsx` — 스케줄 설계 참고
- `docs/` — 보조 문서
