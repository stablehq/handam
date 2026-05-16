# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SMS Reservation System - 숙소(게스트하우스) 예약 관리 + SMS 자동 발송 시스템. 네이버 예약 연동, 객실 배정, 템플릿 기반 SMS 스케줄링, 파티 체크인 등을 지원합니다.

**핵심 아키텍처 패턴**:
1. **Provider Factory + Hot-Swap**: `DEMO_MODE` 환경변수로 Mock/Real 구현체 즉시 전환
2. **Multi-Tenant Isolation**: ContextVar 기반 테넌트 격리 (SELECT/INSERT 자동 필터링)
3. **Template Schedule System**: APScheduler + DB 기반 SMS 자동 발송 스케줄링
4. **Reservation Mutator + Lifecycle Gateway**: 예약 필드 변경(`ReservationMutator`)과 라이프사이클 후처리(`ReservationLifecycle`)를 단일 게이트웨이 두 단계로 통일
5. **Chip Reconcile**: `ReservationSmsAssignment`(="칩") 를 예약/스케줄 변경 시점에 항상 재계산 — `assigned_by='manual'/'excluded'` 또는 `sent_at` 있는 칩은 보호
6. **Diag-Golden Validation**: `app/diag_logger.diag()` 호출을 정답지 YAML 과 매일 비교해 회귀 탐지

## Development Commands

### Backend Setup and Execution

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database with seed data
# Important: Delete old DB file if schema has changed
rm -f sms.db
python -m app.db.seed

# Run development server
uvicorn app.main:app --reload

# Run on custom port
uvicorn app.main:app --reload --port 8001
```

**API Documentation**: http://localhost:8000/docs (Swagger UI automatically generated)

### Frontend Setup and Execution

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (if not already installed)
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

**Frontend URL**: http://localhost:5173 (or auto-incremented port if in use)

### Docker Services

```bash
# Start all services (PostgreSQL, Redis, ChromaDB)
docker compose up -d

# Start specific service
docker compose up -d postgres

# Stop all services
docker compose down

# View logs
docker compose logs -f
```

**Note**: Docker is optional for development. The backend can run with SQLite instead.

### Database Management

```bash
# Reseed database (wipes and recreates all tables + sample data)
cd backend
rm -f sms.db  # Delete old DB file first if schema changed
python -m app.db.seed

# Database migrations (Alembic)
cd backend
alembic revision --autogenerate -m "Description"
alembic upgrade head
alembic downgrade -1
```

## Architecture

### Multi-Tenant System

ContextVar 기반 자동 테넌트 격리 (`app/db/tenant_context.py`):
- **before_compile event**: 모든 SELECT에 `WHERE tenant_id = X` 자동 추가
- **before_flush event**: 모든 INSERT에 `tenant_id` 자동 주입
- **bypass_tenant_filter**: 스케줄러/마이그레이션 등 전역 작업 시 필터 우회
- **X-Tenant-Id 헤더**: 프론트엔드 요청마다 테넌트 지정 (`app/api/deps.py`)

### Provider Factory (Hot-Swap)

`app/factory.py` — 테넌트별 provider 생성:
- `get_sms_provider_for_tenant(tenant)`: Mock 또는 Real(Aligo API)
- `get_reservation_provider_for_tenant(tenant)`: Mock 또는 Real(네이버 API)
- `get_llm_provider()`: Mock(키워드 매칭) 또는 Real(Claude API, 미구현)

### SMS Template Schedule Pipeline

핵심 비즈니스 로직 — 예약 기반 자동 SMS 발송:
1. `TemplateSchedule` (DB) → APScheduler 등록 (`scheduler/schedule_manager.py`)
2. 트리거 시점 → `TemplateScheduleExecutor.execute_schedule()` (`scheduler/template_scheduler.py`)
3. 대상 예약 필터링 (building/room/assignment/column_match 조건)
4. 템플릿 변수 계산 (`templates/variables.py`) → 렌더링 (`templates/renderer.py`)
5. SMS 발송 (`services/sms_sender.py`) → ActivityLog 기록

### Room Assignment System

`services/room_assignment.py`:
- `assign_room()`: 객실 배정 (SELECT FOR UPDATE로 중복 방지)
- `sync_sms_tags()`: 배정 변경 시 ReservationSmsAssignment 자동 동기화
- `scheduler/room_auto_assign.py`: 자동 배정 (도미토리 성별 잠금, 용량 체크)
- `services/room_assignment_invariants.py`: 배정 후 무결성 가드 (중복/범위/성별 잠금)

### Reservation Mutator + Lifecycle (단일 게이트웨이)

예약 변경 6개 경로(네이버 sync, 직원 수정, stay 연장/축소, 객실 배정, push-out, reconcile)를 두 모듈로 통일:

- `services/reservation_mutator.py`: **Reservation 필드 변경 게이트웨이**
  - `ChangeSource`: `NAVER` / `MANUAL` / `SYSTEM` — caller 자기소개
  - `FIELD_PERMISSIONS`: 필드 × source 행렬 (`guarded` / `always` / `never`) — pin 필드 보호
  - 모든 직접 `reservation.field = X` 대입은 이 게이트웨이로 흡수 중 (단계적 마이그레이션)

- `services/reservation_lifecycle.py`: **변경 직후 후처리 게이트웨이**
  - `on_dates_changed(...)`: shift_daily_records → reconcile_dates → reconcile_all_chips
  - 5개 이벤트(`on_dates_changed`, `on_room_changed`, `on_status_changed` 등)별 후처리를 일관된 순서로 실행
  - caller 가 새 필드 값을 적용한 다음 호출하는 것이 규약

> 설계 문서: `docs/plans/reservation-mutator-design.md`, `docs/pipelines/05-reservation-change-routes.md`

### Chip Reconcile System

`services/chip_reconciler.py` — "칩"(= `ReservationSmsAssignment`) 일관성 재계산:

- **reservation-centric**: 1 예약 × N 스케줄 × M 날짜 (예약 변경 시)
- **schedule-centric**: 1 스케줄 × N 예약 × M 날짜 (스케줄 변경/실행 시)
- **칩 보호 규칙**: `assigned_by ∈ {manual, excluded}` 또는 `sent_at IS NOT NULL` 이면 reconcile 이 삭제하지 않음

`services/reconcile.py::reconcile_all_chips()` 가 5종 칩 reconciler 를 일괄 호출:
표준 칩(`sync_sms_tags`) + 4종 custom: `surcharge`, `party3_today_mms`, `room_upgrade_promise`, `room_upgrade_review`.

### Custom Schedule Types

`services/custom_schedule_registry.py` — 표준 칩 외 비표준 발송 로직 등록소:

| `custom_type` | 라벨 | 모듈 |
|---------------|------|------|
| `surcharge_standard` / `surcharge_double` | 인원 초과 안내 | `services/surcharge.py` |
| `party3_today_mms` | 파티 당일 안내 (MMS) | `services/party3_mms.py` |
| `room_upgrade_promise` | 무료 업그레이드 약속 (첫박) | `services/room_upgrade_promise.py` |
| `room_upgrade_review` | 무료 업그레이드 후기 (마지막박) | `services/room_upgrade_review.py` |

- `PER_DATE_DEDUP_CUSTOM_TYPES`: 기본은 stay 단위 1칩이지만, 여기 들어가면 (예약, 날짜) 단위 중복 차단
- Pre-send refresh handler: 스케줄 실행 직전 칩 상태를 최신화

### Room Upgrade — 약속(promise) vs 객후(review)

도메인 룰은 동일(`배정 등급 > 상품 등급 AND 인원 미초과`), 발송 시점만 다름:

- `services/room_upgrade_common.py`: 공통 유틸 (`decide_upgrade_eligible`, `ensure_chip`, `find_single_schedule`, `last_night_of_stay`)
- `services/room_upgrade_promise.py`: **첫박** (`target_date == check_in_date`) — "업그레이드 해드릴게요"
- `services/room_upgrade_review.py`: **마지막박** (`target_date == check_out_date - 1`) — "어떠셨나요" 후기 요청

stay 단위 1칩 가드는 모듈별 독립(약속 1 + 객후 1 = stay 당 최대 2칩).

### Auto-Response Pipeline

`router/message_router.py`: DB Rules → YAML Rules → LLM → Review Queue
- confidence ≥ 0.6: 자동 발송
- confidence < 0.6: 사람 검토 대기열

## Key File Locations

### Configuration & Core
- `backend/app/config.py`: Pydantic Settings (`DEMO_MODE`, DB, API keys, JWT)
- `backend/app/factory.py`: 테넌트별 Provider Factory
- `backend/app/main.py`: FastAPI app (CORS, rate limit, 19개 라우터 등록, startup/shutdown)
- `backend/app/rate_limit.py`: slowapi + X-Forwarded-For 파싱

### Database Layer
- `backend/app/db/models.py`: 20+ SQLAlchemy 모델 (TenantMixin 적용)
- `backend/app/db/database.py`: 엔진/세션 + init_db() 자동 마이그레이션
- `backend/app/db/tenant_context.py`: ContextVar 기반 멀티테넌트 격리
- `backend/app/db/seed.py`: 초기 데이터 시딩 (admin/staff 계정)

### API Endpoints (19 routers)
- `auth.py`: 로그인, 토큰 갱신, 사용자 CRUD
- `reservations.py`: 예약 CRUD + 객실 배정/SMS 배정
- `reservations_sync.py`: 네이버 예약 동기화
- `rooms.py`: 객실 CRUD + N:M biz_item 매핑 + 캘린더
- `buildings.py`: 건물 CRUD
- `templates.py`: SMS 템플릿 CRUD + 변수 미리보기
- `template_schedules.py`: 스케줄 CRUD + APScheduler 연동
- `messages.py`: SMS 수발신 관리 + 연락처 목록
- `webhooks.py`: SMS 수신 웹훅 + 자동응답 파이프라인
- `auto_response.py`: 자동응답 테스트/생성
- `rules.py`: 자동응답 규칙 CRUD
- `dashboard.py`: 대시보드 통계 + 성별 예측
- `activity_logs.py`: 활동 로그 조회/통계
- `party_checkin.py`: 파티 체크인 토글
- `events.py`: SSE 실시간 이벤트
- `settings.py`: 테넌트 설정 (네이버 쿠키 등)
- `tenants.py`: 테넌트 목록
- `documents.py`: 지식 베이스 문서 관리
- `deps.py`: FastAPI 의존성 (테넌트 스코프 DB 세션)

### Services (`backend/app/services/`)

| 파일 | 역할 |
|------|------|
| `sms_sender.py` | SMS 발송 (단건 + 배치) + ActivityLog |
| `sms_tracking.py` | `ReservationSmsAssignment`(칩) 생성/조회 |
| `reservation_mutator.py` | **Reservation 필드 변경 단일 게이트웨이** (ChangeSource × FIELD_PERMISSIONS) |
| `reservation_lifecycle.py` | **변경 직후 후처리 게이트웨이** (shift / reconcile_dates / reconcile_all_chips) |
| `reconcile.py` | `reconcile_all_chips()` — 5종 칩 reconciler 일괄 실행 |
| `chip_reconciler.py` | 표준 칩 reservation-centric / schedule-centric reconcile + 보호 규칙 |
| `filters.py` | 스케줄 필터(`building`, `room`, `assignment`, `column_match`, stay) |
| `schedule_utils.py` | `get_schedule_dates`, `resolve_target_date` 등 날짜 계산 |
| `custom_schedule_registry.py` | custom_type 레지스트리 + pre-send refresh handler |
| `surcharge.py` | 인원초과 안내 (`surcharge_standard` / `surcharge_double`) |
| `party3_mms.py` | 파티 당일 MMS 안내 (per-date dedup) |
| `room_upgrade_common.py` | 업그레이드 안내 공통 유틸 (등급 비교, 칩 보장/삭제) |
| `room_upgrade_promise.py` | 첫박 무료 업그레이드 약속 안내 |
| `room_upgrade_review.py` | 마지막박 객후(後) 후기 요청 안내 |
| `room_assignment.py` | 객실 배정(SELECT FOR UPDATE), `sync_sms_tags`, `_shift_daily_records`, `_reconcile_dates` |
| `room_assignment_invariants.py` | 배정 후 무결성 가드 |
| `room_auto_assign.py` | 자동 배정 (도미토리 성별 잠금) |
| `room_grade.py` | 객실/biz_item 등급 산출 + UI 배지 |
| `room_lookup.py` | 객실 ↔ biz_item 조회 헬퍼 |
| `consecutive_stay.py` | 연박 묶음 산출 |
| `naver_sync.py` | 네이버 동기화 본체 (5분 주기 호출 대상) |
| `event_sms_hook.py` | 신규 예약 즉시 발송 훅 (fire-and-forget, 호출자 보호) |
| `password_display.py` | 객실 비밀번호 표시 규칙 |
| `event_bus.py` | SSE 브로드캐스트 (테넌트별 격리) |
| `activity_logger.py` | 감사 로그 생성 |

### Scheduler
- `scheduler/jobs.py`: APScheduler 설정 + 네이버 동기화/상태 로그 작업
- `scheduler/template_scheduler.py`: 템플릿 스케줄 실행기 (필터링/발송)
- `scheduler/schedule_manager.py`: 스케줄 ↔ APScheduler 트리거 관리
- `scheduler/room_auto_assign.py`: 자동 객실 배정 (도미토리 성별 잠금)

### Templates
- `templates/renderer.py`: `{{변수}}` 치환 + 객실 비밀번호 생성
- `templates/variables.py`: 템플릿 변수 계산 (ParticipantSnapshot 캐시)

### Auth
- `auth/utils.py`: bcrypt 해싱 + JWT 생성/검증
- `auth/dependencies.py`: FastAPI 인증 의존성 (역할 기반 접근 제어)

### Providers
- `providers/base.py`: Protocol 정의 (SMSProvider, ReservationProvider, LLMProvider)
- `mock/sms.py`, `mock/llm.py`: 데모용 Mock 구현
- `real/sms.py`: Aligo SMS API (SMS/LMS 자동 감지, 500건 배치)
- `real/reservation.py`: 네이버 스마트플레이스 API (쿠키 인증, 성별/연령 조회)
- `real/llm.py`: Claude API (미구현 stub)

### Frontend
- `src/App.tsx`: React Router (역할별 라우트 보호)
- `src/pages/`: 12개 페이지 (Dashboard, Reservations, RoomAssignment, RoomSettings, Templates, Messages, AutoResponse, ActivityLogs, PartyCheckin, Settings, Login, UserManagement)
- `src/services/api.ts`: Axios 클라이언트 (자동 토큰 갱신, X-Tenant-Id 헤더)
- `src/stores/`: Zustand (auth-store, tenant-store)
- `src/components/Layout.tsx`: 사이드바 + 역할별 네비게이션

## Database Schema

### Core Models (all TenantMixin except User, Tenant)

| 모델 | 용도 | 핵심 필드 |
|------|------|-----------|
| `User` | 인증 | username, hashed_password, role (SUPERADMIN/ADMIN/STAFF) |
| `Tenant` | 멀티테넌트 | slug, name, naver_business_id, naver_cookie, aligo_sender |
| `Reservation` | 예약 | customer_name, phone, check_in/out_date, section (room/party/unassigned), male_count, female_count |
| `Message` | SMS 이력 | direction, from_, to, content, auto_response, confidence, needs_review, response_source |
| `Room` | 객실 | room_number, room_type, is_dormitory, base/max_capacity, building_id |
| `Building` | 건물 | name, sort_order, is_active |
| `RoomAssignment` | 일자별 배정 | reservation_id, date, room_number, room_password, assigned_by |
| `RoomBizItemLink` | N:M 매핑 | room_id, biz_item_id, male/female_priority |
| `NaverBizItem` | 네이버 상품 | biz_item_id, name, is_exposed |
| `MessageTemplate` | SMS 템플릿 | template_key, content, variables (JSON), category, participant_buffer |
| `TemplateSchedule` | 발송 스케줄 | template_id, schedule_type, hour, minute, filters (JSON), target_mode |
| `ReservationSmsAssignment` | SMS 추적 | reservation_id, template_key, date, assigned_by, sent_at |
| `Rule` | 자동응답 규칙 | pattern (regex), response, priority, is_active |
| `ActivityLog` | 감사 로그 | activity_type, title, detail (JSON), target/success/failed_count |
| `PartyCheckin` | 파티 출석 | reservation_id, date, checked_in_at |
| `ReservationDailyInfo` | 일자별 오버라이드 | reservation_id, date, party_type |
| `ParticipantSnapshot` | 성별 캐시 | date, male_count, female_count |
| `GenderStat` | 인구통계 | date, male_count, female_count |

### Enums
- `UserRole`: SUPERADMIN, ADMIN, STAFF
- `MessageDirection`: INBOUND, OUTBOUND
- `MessageStatus`: PENDING, SENT, FAILED, RECEIVED
- `ReservationStatus`: PENDING, CONFIRMED, CANCELLED, COMPLETED

## Environment Variables

`backend/.env` 주요 설정:

- `DEMO_MODE`: `true` (mock) / `false` (production) — **핵심 스위치**
- `DATABASE_URL`: `sqlite:///./sms.db` (데모) / `postgresql://...` (운영)
- `JWT_SECRET_KEY`: 데모 모드에서 자동 생성
- `ADMIN_DEFAULT_PASSWORD`, `STAFF_DEFAULT_PASSWORD`: 데모 모드에서 자동 생성

운영 전용 (`DEMO_MODE=false`):
- `ALIGO_API_KEY`, `ALIGO_USER_ID`, `ALIGO_SENDER`: Aligo SMS API
- `CLAUDE_API_KEY`: Anthropic Claude API
- 네이버 쿠키: DB Tenant 레코드에 저장 (런타임 업데이트 가능)

## Scheduler Jobs

| Job | 주기 | 설명 |
|-----|------|------|
| `sync_naver_reservations_job` | 5분 | 네이버 예약 동기화 (전 테넌트) |
| `sync_status_log_job` | 6시간 (00,06,12,18) | 동기화 상태 로그 기록 |
| `daily_room_assign_job` | 매일 | 미래 날짜 자동 객실 배정 |
| `TemplateSchedule` 기반 | DB 설정 | 템플릿별 SMS 자동 발송 |

## Common Development Patterns

### API 엔드포인트 추가
1. `app/api/[domain].py`에 라우터 작성
2. `get_tenant_scoped_db()` 의존성으로 테넌트 격리 DB 세션 획득
3. `app/main.py`에 라우터 등록

### SMS 템플릿 변수
`{{customer_name}}`, `{{room_num}}`, `{{building}}`, `{{room_password}}`, `{{participant_count}}`, `{{male_count}}`, `{{female_count}}` 등 — `templates/variables.py`의 `calculate_template_variables()` 참조

### ActivityLog 기록
```python
from app.services.activity_logger import log_activity
log_activity(db, type="sms_send", title="...", detail={...},
             target_count=1, success_count=1, created_by="system")
```

### 서비스 모듈 읽기 순서
`backend/app/services/*.py` 의 핵심 모듈(`reservation_mutator`, `reservation_lifecycle`, `chip_reconciler`, `room_upgrade_*` 등)은 **파일 상단 docstring 에 책임/호출 순서/마이그레이션 단계를 명시**합니다. 코드 본문 읽기 전에 docstring 부터 확인하고, 참조된 `docs/plans/*.md` 가 있다면 같이 읽으세요.

## Frontend Design Guidelines

→ [`frontend/CLAUDE.md`](frontend/CLAUDE.md) 로 분리. 색상 팔레트, 타이포그래피, Flowbite 버튼/뱃지/모달 규칙, 컴포넌트 클래스, 다크 모드 패턴 등 프론트 작업 시 참조.

## Documentation & Validation Pipeline

설계 의도와 실제 런타임 동작의 갭을 막기 위한 문서/로그 체계:

- **`docs/pipelines/`** — 핵심 비즈니스 흐름 4종 (`01-sms-template-schedule`, `02-room-assignment`, `03-multi-tenant`, `04-naver-sync`) + `05-reservation-change-routes`. 수기 Mermaid 우선, `_generated/*.svg` 는 보조.
- **`docs/plans/`** — 진행 중인 단계적 마이그레이션 plan (현재 37개: `lifecycle-step-01..22`, `mutator-step-*`, `room-upgrade-*` 등). 서비스 파일 상단 docstring 이 자신의 단계를 명시하므로, "스켈레톤/일부만 호출됨" 형태의 모듈을 만나면 plan 부터 확인.
- **`docs/diag-golden/`** — Diag 정답지 시스템
  - `actions/*.yaml`: 각 액션이 찍어야 할 `diag()` 이벤트 시퀀스 (정답)
  - `state.json`: 마지막 검증 체크포인트 (`last_log_timestamp`, `last_commit_sha`, `last_coverage_scan_sha`)
  - `invariants.md`: 8개 불변식 규칙
  - `scripts/diag/`: `extract_trace.py` / `diff_trace.py` / `check_invariants.py` / `coverage_scan.py`
- **계측 함수**: `app/diag_logger.diag(event, **fields)` — 새 비즈니스 분기마다 한 줄 추가, 정답지에 반영.
- **검증 트리거**: `/oh-my-claudecode:ooo-log-validation` 스킬이 매일 증분 분석. `ooo-chip-check` 는 칩 누락/미발송을 SQL+diag 로 case-by-case 진단.
- **변경 검증**: 코드 수정 계획은 `/oh-my-claudecode:ooo-change-validator` 로 사전 Impact Analysis.

## Notes

- SQLAlchemy ORM: SQLite (데모) + PostgreSQL (운영) 지원
- 타임존: Asia/Seoul (KST) 사용
- 프론트엔드: Flowbite React + Toss Invest 디자인 시스템 (NOT Ant Design)
- UI/샘플 데이터: 한국어
- 인증: JWT (access 1h + refresh 7d), bcrypt 해싱
- 역할: SUPERADMIN → ADMIN → STAFF (파티 체크인만 접근 가능)
- 실시간: SSE 이벤트 버스 (`services/event_bus.py`)
- Aligo SMS: SMS(≤90바이트)/LMS(>90바이트) 자동 감지, 500건 배치
- 네이버 API: 쿠키 기반 인증, Semaphore(10) 동시성 제한
- CampaignLog: 레거시 (읽기 전용), 신규 활동은 ActivityLog 사용
- `_future/` 디렉토리: 미래 구현 예정 모듈
