# SMS 예약 시스템 상세 가이드북

## 목차
1. [프로젝트 개요](#1-프로젝트-개요)
2. [백엔드 구조](#2-백엔드-구조)
3. [프론트엔드 구조](#3-프론트엔드-구조)
4. [인프라 및 배포](#4-인프라-및-배포)
5. [데이터 흐름도](#5-데이터-흐름도)

---

## 1. 프로젝트 개요

### 1.1 시스템 목적

SMS 예약 시스템은 호텔/게스트하우스의 SMS 자동응답 및 예약 관리를 자동화하는 데모/MVP 시스템입니다.

**핵심 기능:**
- SMS 수신/발송 및 자동응답 (규칙 기반, LLM 기반)
- 네이버 스마트플레이스 예약 동기화
- 객실 자동배정 (성별 기반, 용량 제한)
- 템플릿 기반 스케줄 발송 (일일, 주간, 시간 기반, 간격 기반)
- 사용자 계층(슈퍼어드민, 어드민, 스태프) 관리
- 활동 로그 및 통계 분석

### 1.2 아키텍처 패턴: Hot-Swap Provider

시스템의 핵심은 **Provider Factory Pattern** (PEP 544 Protocol 기반)으로, 단 하나의 환경변수(`DEMO_MODE`)로 모든 외부 서비스를 Mock과 Real 사이에 전환합니다.

```
DEMO_MODE=true  → MockSMSProvider, RealLLMProvider, RealReservationProvider
DEMO_MODE=false → RealSMSProvider, RealLLMProvider, RealReservationProvider
```

**파일:** `backend/app/factory.py`, `backend/app/providers/base.py`

### 1.3 기술 스택

| 계층 | 기술 |
|------|------|
| **백엔드** | FastAPI, SQLAlchemy, Alembic |
| **데이터베이스** | SQLite (Demo) / PostgreSQL (Prod) |
| **프론트엔드** | React 19, TypeScript, Tailwind CSS, Flowbite |
| **스케줄링** | APScheduler (AsyncIO) |
| **인증** | JWT (HS256) |
| **SMS API** | Aligo (NHN Cloud) |
| **LLM** | Claude API (Anthropic) |
| **예약 API** | Naver Smart Place |
| **벡터DB** | ChromaDB (RAG 용) |
| **캐시** | Redis (선택사항) |

---

## 2. 백엔드 구조

### 2.1 진입점 및 설정

#### `backend/app/main.py` - FastAPI 앱 진입점

**역할:** 앱 초기화, 라우터 등록, 미들웨어 설정

**주요 기능:**
- CORS, Rate Limiting 미들웨어 설정
- 데이터베이스 초기화 (`init_db()`)
- 스케줄러 시작/종료 (`start_scheduler()`, `stop_scheduler()`)
- Health Check 엔드포인트 (`GET /health`)

**라우터 등록:**
```python
app.include_router(auth.router)           # 인증
app.include_router(messages.router)       # SMS 메시지
app.include_router(reservations.router)   # 예약
app.include_router(rooms.router)          # 객실
app.include_router(scheduler.router)      # 스케줄 관리
app.include_router(template_schedules.router)  # 템플릿 스케줄
app.include_router(auto_response.router)  # 자동응답
# ... 기타 11개 라우터
```

**설정 항목:**
- `DEMO_MODE`: Demo/Prod 전환 (기본값: true)
- `CORS_ORIGINS`: CORS 화이트리스트
- `JWT_SECRET_KEY`: JWT 토큰 서명 키 (미설정 시 자동 생성)

#### `backend/app/config.py` - 환경 설정

**클래스:** `Settings` (Pydantic BaseSettings)

**핵심 설정값:**
- `DEMO_MODE` (bool): Mock vs Real 프로바이더 선택
- `DATABASE_URL`: SQLite/PostgreSQL 연결 문자열
- `ALIGO_*`: SMS API 자격증명 (DEMO_MODE=false 시 필수)
- `CLAUDE_API_KEY`: Claude API 키 (LLM 사용 시 필수)
- `JWT_SECRET_KEY`, `ADMIN_DEFAULT_PASSWORD`, `STAFF_DEFAULT_PASSWORD`: 보안 값

**검증 로직:** `@model_validator(mode='after')` - 프로덕션 모드에서 필수 값 검증

#### `backend/app/factory.py` - 프로바이더 팩토리

**함수:**
```python
get_sms_provider() -> SMSProvider
  ├─ DEMO_MODE=true  → MockSMSProvider()
  └─ DEMO_MODE=false → RealSMSProvider(api_key, user_id, sender, testmode)

get_llm_provider() -> LLMProvider
  └─ RealLLMProvider(api_key)  # 항상 Real (Mock은 불필요)

get_reservation_provider() -> ReservationProvider
  └─ RealReservationProvider(business_id, cookie)  # 항상 Real
```

**주목:** `@lru_cache(maxsize=1)` 데코레이터로 인스턴스 재사용

---

### 2.2 API 라우터 (`backend/app/api/`)

각 라우터는 특정 도메인의 엔드포인트를 관리합니다.

#### **messages.py** - SMS 메시지 관리

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/messages` | GET | 메시지 목록 (페이징, 필터링) |
| `/api/messages/contacts` | GET | 고유 연락처 목록 (마지막 메시지 포함) |
| `/api/messages/review-queue` | GET | 인간 검토 필요 메시지 목록 |
| `/api/messages/send` | POST | SMS 발송 |
| `/webhooks/sms/receive` | POST | SMS 수신 웹훅 (또는 시뮬레이션) |

**핵심 함수:**
- `send_sms_message(to, content)`: SMS 발송 → 데이터베이스 저장 → auto_response 생성
- `simulate_receive(from_, to, content)`: Demo 모드에서 SMS 수신 시뮬레이션

**사용 프로바이더:** `get_sms_provider()` (MockSMSProvider 또는 RealSMSProvider)

---

#### **reservations.py** - 예약 관리

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/reservations` | GET | 예약 목록 (필터링: status, date, 검색) |
| `/api/reservations` | POST | 예약 생성 |
| `/api/reservations/{id}` | GET | 예약 상세 조회 |
| `/api/reservations/{id}` | PUT | 예약 수정 |
| `/api/reservations/{id}` | DELETE | 예약 삭제 |
| `/api/reservations/{id}/room` | PUT | 객실 배정 |
| `/api/reservations/sync/naver` | POST | 네이버 스마트플레이스 동기화 |

**데이터 모델:**
```python
ReservationCreate / ReservationUpdate:
  - customer_name, phone, check_in_date, check_in_time
  - status (pending/confirmed/cancelled/completed)
  - male_count, female_count (성별 투숙 인원)
  - party_size, party_type ('1', '2', '2차만')
  - tags (쉼표 구분 또는 배열: "객후,1초,2차만")
  - section ('room'=객실배정, 'party'=파티, 'unassigned'=미배정)
  - naver_room_type (네이버 원본 객실 타입)
```

**핵심 함수:**
- `assign_room(reservation_id, room_number, date)`: 객실 배정 → RoomAssignment 생성 → SMS 태그 동기화
- `sync_naver_to_db()`: 네이버 API → 데이터베이스 동기화 (scheduler job 호출)

**사용 서비스:** `room_assignment.sync_sms_tags()` (SMS 발송 자격 재계산)

---

#### **rooms.py** - 객실 관리

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/rooms` | GET | 활성 객실 목록 |
| `/api/rooms` | POST | 객실 생성 |
| `/api/rooms/{id}` | PUT | 객실 수정 |
| `/api/rooms/{id}` | DELETE | 객실 삭제 |
| `/api/rooms/naver/biz-items` | GET | 네이버 BizItem 목록 |
| `/api/rooms/naver/biz-items/sync` | POST | 네이버 BizItem 동기화 |
| `/api/rooms/auto-assign` | POST | 수동 자동배정 트리거 |

**데이터 모델:**
```python
Room:
  - room_number (예: "A101", "B205")
  - room_type (예: "더블룸", "트윈룸")
  - base_capacity, max_capacity (기본/최대 인원)
  - is_active, sort_order
  - building_id (건물 ID - N:M 관계)
  - is_dormitory, bed_capacity (기숙사 전용)
  - door_password (고정 비밀번호)
  - biz_item_links (N:M 관계 - RoomBizItemLink)
```

**주목:** `biz_item_ids` 배열 지원 - 하나의 객실이 여러 네이버 상품에 매핑 가능

---

#### **auto_response.py** - 자동응답

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/auto-response/test` | POST | 메시지 테스트 (저장 X) |
| `/api/auto-response/generate` | POST | 메시지 ID로 응답 생성 및 발송 |
| `/api/auto-response/reload-rules` | POST | 규칙 파일 핫 리로드 |

**흐름:**
1. 메시지 입력 → `MessageRouter.generate_auto_response()` 호출
2. 규칙 엔진 매칭 시도 (confidence 0.95)
3. 규칙 없으면 LLM 호출
4. confidence < 0.6이면 인간 검토 대기
5. confidence >= 0.6이면 자동 발송

---

#### **rules.py** - 자동응답 규칙

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/rules` | GET | 규칙 목록 |
| `/api/rules` | POST | 규칙 생성 |
| `/api/rules/{id}` | PUT | 규칙 수정 |
| `/api/rules/{id}` | DELETE | 규칙 삭제 |

**Rule 모델:**
```python
Rule:
  - name (규칙명)
  - pattern (regex 패턴, ≤500자)
  - response (응답 텍스트, Jinja2 템플릿 지원)
  - priority (높을수록 우선 처리)
  - is_active (활성화 여부)
```

**저장소:** 메모리 로딩은 `app/rules/rules.yaml`에서, 생성/수정은 DB에 저장

---

#### **scheduler.py** - 스케줄 관리

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/scheduler/jobs` | GET | 전체 스케줄 job 목록 |
| `/api/scheduler/jobs/{job_id}` | GET | 특정 job 상세 |
| `/api/scheduler/jobs/{job_id}/run` | POST | job 수동 실행 |
| `/api/scheduler/jobs/{job_id}/pause` | POST | job 일시 중지 |

**Job 종류:**
- `sync_naver_reservations`: 10분마다 (10:00-21:59)
- `daily_room_assign`: 매일 08:00
- `template_schedule_*`: 템플릿 스케줄 동적 생성

---

#### **template_schedules.py** - 템플릿 스케줄

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/template-schedules` | GET | 스케줄 목록 |
| `/api/template-schedules` | POST | 스케줄 생성 |
| `/api/template-schedules/{id}` | PUT | 스케줄 수정 |
| `/api/template-schedules/{id}` | DELETE | 스케줄 삭제 |
| `/api/template-schedules/{id}/run` | POST | 스케줄 수동 실행 |

**TemplateSchedule 모델:**
```python
TemplateSchedule:
  - template_id (MessageTemplate 참조)
  - schedule_name
  - schedule_type ('daily', 'weekly', 'hourly', 'interval')
  - hour, minute (시간, 분)
  - day_of_week ('mon,tue,wed,...')
  - interval_minutes (간격 타입용)
  - active_start_hour, active_end_hour (활성화 시간대)
  - timezone ('Asia/Seoul')
  - filters (JSON: [{"type": "tag", "value": "객후"}, ...])
    - 필터 타입: tag, assignment (room/party/unassigned), building, room
  - date_filter ('today', 'tomorrow', 'YYYY-MM-DD')
  - exclude_sent (이미 발송한 대상 제외)
  - is_active
```

**필터 로직:** 같은 타입은 OR, 다른 타입은 AND

---

#### **templates.py** - SMS 템플릿

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/templates` | GET | 템플릿 목록 |
| `/api/templates` | POST | 템플릿 생성 |
| `/api/templates/{id}` | PUT | 템플릿 수정 |
| `/api/templates/{id}` | DELETE | 템플릿 삭제 |

**MessageTemplate 모델:**
```python
MessageTemplate:
  - template_key (고유 ID: "room_guide", "party_guide" 등)
  - name (표시명)
  - short_label (칩 표시용 약자, 2-4자)
  - content (SMS 본문, Jinja2 변수 지원)
  - variables (JSON: ["customer_name", "room_number", ...])
  - category ('room_guide', 'party_guide', ...)
  - is_active
```

**변수 예시:** `{{ customer_name }}, {{ room_number }}, {{ room_password }}`

---

#### **기타 라우터**

| 라우터 | 설명 |
|--------|------|
| `auth.py` | 로그인, 토큰 발급 |
| `documents.py` | 지식 베이스 문서 업로드 (RAG용) |
| `dashboard.py` | 통계 (메시지 수, 예약 상태 분포, 성별 통계) |
| `buildings.py` | 건물 관리 (본관, 별관, 로하스 등) |
| `activity_logs.py` | 활동 로그 조회 |
| `party_checkin.py` | 파티 체크인 관리 |
| `events.py` | SSE 이벤트 스트림 (room assignment auto-refresh) |
| `reservations_sync.py` | 네이버 동기화 로직 |
| `settings.py` | 시스템 설정 (Naver 쿠키, 앱 상태) |

---

### 2.3 데이터베이스 (`backend/app/db/`)

#### `database.py` - DB 연결 및 초기화

**주요 함수:**
- `init_db()`: 테이블 생성 + 자동 마이그레이션
  - 기본 admin 사용자 생성
  - 레거시 1:1 `naver_biz_item_id` → N:M `room_biz_item_links` 마이그레이션
  - 레거시 `target_type/target_value` → JSON `filters` 마이그레이션
  - 기본 `Building` 및 `Room` 데이터 생성 (필요 시)

- `get_db()`: FastAPI 의존성 주입 함수

**연결 풀:** PostgreSQL 프로덕션에서 `pool_size=5, max_overflow=10, pool_recycle=300`

---

#### `models.py` - SQLAlchemy ORM 모델

**핵심 모델:**

| 테이블 | 설명 | 주요 필드 |
|--------|------|---------|
| **User** | 사용자 | id, username, hashed_password, role (superadmin/admin/staff), is_active |
| **Message** | SMS 메시지 | id, message_id, direction (inbound/outbound), from_, to, content, status, auto_response, auto_response_confidence, needs_review, response_source (rule/llm/manual) |
| **Reservation** | 예약 | id, external_id, customer_name, phone, check_in_date, check_in_time, status, section ('room'/'party'/'unassigned'), room_number, room_password, male_count, female_count, party_size, party_type, tags, naver_booking_id, naver_room_type, gender, age_group |
| **RoomAssignment** | 객실 배정 (날짜별) | id, reservation_id (FK), date (YYYY-MM-DD), room_number, room_password, assigned_by ('auto'/'manual') |
| **Room** | 객실 설정 | id, room_number, room_type, base_capacity, max_capacity, is_active, building_id (FK), is_dormitory, bed_capacity, door_password |
| **Building** | 건물 | id, name ('본관', '별관', '로하스'), description, is_active, sort_order |
| **MessageTemplate** | SMS 템플릿 | id, template_key, name, short_label, content, variables (JSON), category, is_active |
| **TemplateSchedule** | 스케줄 | id, template_id (FK), schedule_name, schedule_type, hour, minute, day_of_week, interval_minutes, active_start_hour, active_end_hour, timezone, filters (JSON), date_filter, exclude_sent, is_active |
| **ReservationSmsAssignment** | SMS 태그 (N:M) | id, reservation_id (FK), template_key, assigned_at, sent_at (null=pending), assigned_by ('auto'/'manual') |
| **Rule** | 자동응답 규칙 | id, name, pattern (regex), response, priority, is_active |
| **Document** | 지식 베이스 | id, filename, content, file_path, uploaded_at, is_indexed |
| **NaverBizItem** | 네이버 상품 | id, biz_item_id (고유), name, biz_item_type, is_exposed, is_active |
| **RoomBizItemLink** | 객실↔상품 (N:M) | id, room_id (FK), biz_item_id (FK) |
| **GenderStat** | 성별 통계 | id, date (YYYY-MM-DD), male_count, female_count, participant_count |
| **ActivityLog** | 활동 로그 | id, action (create/update/delete/...), resource_type, resource_id, user_id (FK), details (JSON), created_at |

**관계도:**
```
User
  ├─ ActivityLog (1:N)

Reservation (1:N)
  ├─ RoomAssignment
  ├─ ReservationSmsAssignment

RoomAssignment (N:1)
  └─ Reservation

Room (1:N)
  ├─ RoomBizItemLink
  └─ Building

RoomBizItemLink (N:1 to both)
  ├─ Room
  └─ NaverBizItem

TemplateSchedule (N:1)
  └─ MessageTemplate

ReservationSmsAssignment (N:1)
  └─ Reservation
```

---

### 2.4 서비스 레이어 (`backend/app/services/`)

#### `room_assignment.py` - 객실 배정 서비스

**핵심 함수:**

```python
sync_sms_tags(db: Session, reservation_id: int, schedules=None) -> None
```
목적: TemplateSchedule의 filters와 일치하는 메시지 템플릿을 ReservationSmsAssignment에 자동 추가/삭제

과정:
1. 예약의 section (room/party/unassigned)과 RoomAssignment 조회
2. 활성 TemplateSchedule 순회
3. 각 schedule의 filters 평가 (_reservation_matches_schedule)
4. 예상 template_keys 계산
5. 새 키는 추가, 오래된 미발송 키는 삭제 (수동 발송 키는 보호)

**주요 필터 그룹:**
- `tag`: 예약의 tags 필드에 값 포함 여부
- `assignment`: section 값 (room/party/unassigned)
- `building`: RoomAssignment의 room → Room.building_id 매칭
- `room`: RoomAssignment의 room_number 매칭

**필터 로직:** 같은 타입 필터는 OR, 다른 타입은 AND

---

#### `sms_sender.py` - SMS 발송 서비스

```python
async def send_sms(to: str, message: str) -> Dict[str, Any]
```

`get_sms_provider().send_sms()` 호출 래퍼. 발송 후 Message 레코드 생성.

---

#### `activity_logger.py` - 활동 로그 서비스

```python
def log_activity(db, action: str, resource_type: str, resource_id: int,
                 current_user: User, details: Dict = None)
```

모든 CRUD 작업을 ActivityLog에 기록. 감시 목적.

---

#### `sms_tracking.py` - SMS 추적

```python
def record_sms_sent(db, reservation_id, template_key) -> None
```

ReservationSmsAssignment의 `sent_at` 업데이트 (이미 발송한 대상 제외에 사용)

---

#### `event_bus.py` - 이벤트 버스

```python
async def publish(event_type: str, data: Dict[str, Any]) -> None
```

SSE (Server-Sent Events) 클라이언트에 푸시. 예: room assignment 수행 시 프론트엔드 자동 새로고침

---

### 2.5 메시지 라우팅 (`backend/app/router/`)

#### `message_router.py` - 자동응답 라우팅

```python
class MessageRouter:
    async def generate_auto_response(message: str) -> Dict[str, Any]:
        # 반환:
        # {
        #   "response": str,
        #   "confidence": float (0-1),
        #   "needs_review": bool,
        #   "source": str ("rule" or "llm")
        # }
```

**파이프라인:**
1. **Step 1 - Rule Engine** (confidence: 0.95)
   - `RuleEngine.match(message)` 호출
   - regex 패턴 매칭 시도 (우선순위순)
   - 매칭 시 즉시 반환

2. **Step 2 - LLM Fallback**
   - 규칙 불일치 시 LLM 호출
   - RealLLMProvider (Claude API) 또는 Mock (키워드 매칭)

3. **Step 3 - Human Review Decision**
   - confidence < 0.6 → needs_review=true
   - confidence >= 0.6 → 자동 발송

---

### 2.6 규칙 엔진 (`backend/app/rules/`)

#### `engine.py` - 규칙 기반 매칭

```python
class RuleEngine:
    def load_rules(self) -> None
        # app/rules/rules.yaml에서 YAML 파싱

    def match(message: str) -> Optional[Dict[str, Any]]
        # regex 패턴 매칭 (IGNORECASE)
        # ReDoS 방어: 패턴 길이 ≤500, 컴파일 검증
```

**규칙 파일 형식** (`app/rules/rules.yaml`):
```yaml
rules:
  - name: "영업시간"
    pattern: "영업시간|오픈|시작"
    response: "08:00~22:00 입니다."
    priority: 10
    active: true
  - name: "객실안내"
    pattern: "객실|방|숙박"
    response: "더블룸, 트윈룸, 패밀리룸이 있습니다."
    priority: 5
    active: true
```

**Response 템플릿:** Jinja2 변수 지원
```python
response_template = "안녕하세요. {{ customer_name }}님! 객실은 {{ room_number }}입니다."
```

---

### 2.7 프로바이더 (`backend/app/providers/`, `backend/app/mock/`, `backend/app/real/`)

#### `providers/base.py` - Protocol 정의 (PEP 544)

```python
class SMSProvider(Protocol):
    async def send_sms(to: str, message: str) -> Dict[str, Any]
    async def send_bulk(messages: List[Dict]) -> Dict[str, Any]
    async def simulate_receive(from_: str, to: str, message: str) -> Dict[str, Any]

class LLMProvider(Protocol):
    async def generate_response(message: str, context: Dict = None) -> Dict[str, Any]

class ReservationProvider(Protocol):
    async def sync_reservations(date=None) -> List[Dict[str, Any]]
    async def get_reservation_details(reservation_id: str) -> Optional[Dict[str, Any]]
```

---

#### `mock/sms.py` - Mock SMS (Demo용)

```python
class MockSMSProvider:
    async def send_sms(to, message) -> Dict:
        # 콘솔 로깅만 수행
        # "[MOCK SMS SENT] To: {to} Message: {message}"
        # 실제 API 호출 없음

    async def simulate_receive(from_, to, message) -> Dict:
        # 수신 시뮬레이션 (웹훅으로 전달됨)
```

**특징:** DEMO_MODE=true일 때만 사용. 실제 비용 없음.

---

#### `real/sms.py` - Real SMS (NHN Cloud Aligo API)

```python
class RealSMSProvider:
    def __init__(self, api_key, user_id, sender, testmode=True)

    async def send_sms(to, message) -> Dict:
        # HTTP POST to Aligo API
        # ALIGO_TESTMODE=true면 test 모드 (실제 발송 안함)
        # ALIGO_TESTMODE=false면 실제 발송
```

---

#### `real/llm.py` - Real LLM (Claude API)

```python
class RealLLMProvider:
    def __init__(self, api_key: str)

    async def generate_response(message: str, context=None) -> Dict:
        # Claude API 호출 (anthropic 라이브러리)
        # 반환: {response, confidence, needs_review}
```

---

#### `real/reservation.py` - Real Reservation (Naver API)

```python
class RealReservationProvider:
    def __init__(self, business_id: str, cookie: str)

    async def sync_reservations(date=None) -> List[Dict]:
        # Naver Smart Place API 호출
        # 예약 데이터 반환
```

---

### 2.8 스케줄러 (`backend/app/scheduler/`)

#### `jobs.py` - APScheduler Job 정의

**생성되는 Job:**
```python
# Job 1: Naver 동기화 (매 10분, 10:00-21:59)
scheduler.add_job(
    sync_naver_reservations_job,
    trigger=CronTrigger(hour='10-21', minute='*/5', timezone='Asia/Seoul'),
    id='sync_naver_reservations'
)

# Job 2: 일일 자동배정 (매일 08:00)
scheduler.add_job(
    daily_room_assign_job,
    trigger=CronTrigger(hour=8, minute=0, timezone='Asia/Seoul'),
    id='daily_room_assign'
)

# Job 3: 템플릿 스케줄 로드 (시작 시)
load_template_schedules()
```

**주요 함수:**
- `sync_naver_reservations_job()`: ReservationProvider 호출 → DB 동기화
- `daily_room_assign_job()`: `auto_assign_rooms()` 호출
- `load_template_schedules()`: ScheduleManager.sync_all_schedules() 호출

---

#### `schedule_manager.py` - 스케줄 관리자

```python
class ScheduleManager:
    def __init__(self, scheduler: AsyncIOScheduler)

    def sync_all_schedules(db: Session) -> None
        # DB의 활성 TemplateSchedule 조회
        # 기존 job 제거
        # 각 schedule에 대해 APScheduler job 생성

    def add_schedule_job(schedule: TemplateSchedule, db: Session) -> None
        # Job ID: f"template_schedule_{schedule.id}"
        # Trigger 생성: _create_trigger(schedule)
        # 활성 시간 체크 (hourly/interval용)

    def _create_trigger(schedule) -> Optional[CronTrigger]
        # schedule_type별로 CronTrigger 또는 IntervalTrigger 생성
```

---

#### `template_scheduler.py` - 템플릿 스케줄 실행 엔진

```python
class TemplateScheduleExecutor:
    async def execute_schedule(schedule_id: int) -> Dict[str, Any]
        # schedule 조회
        # filters 파싱 및 대상 예약 조회
        # 각 예약의 메시지 템플릿 렌더링
        # SMS 발송 (bulk)
        # ReservationSmsAssignment.sent_at 업데이트
        # 활동 로그 기록
```

**필터 빌더:** `FILTER_BUILDERS` 딕셔너리로 SQL WHERE 절 동적 생성
- `tag`: `tags LIKE '%{value}%'`
- `assignment`: `section = {value}` (room/party/unassigned)
- `building`: RoomAssignment JOIN Room 후 building_id 매칭
- `room`: RoomAssignment의 room_number 매칭

---

#### `room_auto_assign.py` - 객실 자동배정

```python
def auto_assign_rooms(db: Session, target_date: str = None) -> Dict[str, Any]
```

**알고리즘:**
1. `target_date` (기본: today) 조회
2. 활성 객실 중 NaverBizItem 링크가 있는 것만 선택
3. BizItem ID → Room 매핑 구성 (N:M)
4. 미배정 확정 예약 조회 (해당 날짜에 RoomAssignment 없음)
5. 각 예약의 naver_biz_item_id로 후보 객실 조회
6. 용량 및 성별 규칙으로 배정 시도:
   - **일반 객실:** 1예약/객실
   - **기숙사:** 성별 제한 (gender lock) + bed_capacity까지 복수 배정

**수동 배정 보호:** `assigned_by='manual'`인 RoomAssignment는 절대 덮어쓰지 않음

**부수 작업:**
- RoomAssignment 생성 후 `room_assignment.sync_sms_tags()` 호출
- SMS 발송 자격 재계산 및 이벤트 발행

---

### 2.9 알림 서비스 (`backend/app/notifications/`)

SQLAlchemy event 리스너로 예약 상태 변경 시 자동 SMS 발송

```python
@event.listens_for(Reservation, "after_insert")
@event.listens_for(Reservation, "after_update")
def send_reservation_notification(mapper, connection, target):
    # Reservation의 status 변경 감지
    # 상태별 템플릿 선택 및 SMS 발송
```

---

### 2.10 기타 서비스

#### `templates/renderer.py` - SMS 템플릿 렌더링

```python
class TemplateRenderer:
    def render(template: MessageTemplate, context: Dict) -> str
        # Jinja2 템플릿 렌더링
        # 변수: customer_name, room_number, room_password, check_in_date, party_size 등
```

---

#### `analytics/gender_analyzer.py` - 성별 통계

```python
def extract_gender_stats(db, date) -> Dict[str, int]
    # 해당 날짜 예약들의 male_count, female_count 집계
    # GenderStat 레코드 생성/업데이트
```

---

## 3. 프론트엔드 구조

### 3.1 앱 구조 및 라우팅

#### `frontend/src/App.tsx` - 라우터 설정

```typescript
<Router>
  <Route path="/login" element={<Login />} />
  <Route element={<ProtectedRoute><Layout><Outlet /></Layout></ProtectedRoute>}>
    {/* Dashboard, Reservations, Messages, etc. */}
    <Route path="/" element={<StaffRedirect><Dashboard /></StaffRedirect>} />
    <Route path="/party-checkin" element={<PartyCheckin />} />
    {/* admin만 접근 가능 */}
    <Route path="/users" element={<ProtectedRoute requiredRoles={['admin', 'superadmin']}><UserManagement /></ProtectedRoute>} />
  </Route>
</Router>
```

**라우트 권한:**
- **Superadmin/Admin:** 모든 페이지
- **Staff:** `/party-checkin`만 (/ 접근 시 리다이렉트)
- **Guest:** `/login`만

---

### 3.2 페이지별 기능

#### `pages/Dashboard.tsx` - 통계 대시보드

**기능:**
- 오늘 메시지 수, 예약 수, 성별 분포 stat-card
- 시간대별 메시지 차트
- 상태별 예약 분포 (pie)
- 일일 객실 배정 현황

**API 호출:** `dashboardAPI.getStats()`

---

#### `pages/Messages.tsx` - SMS 메시지 관리

**기능:**
- 메시지 목록 (pagination, 검색, 필터)
- 연락처 목록 (마지막 메시지 미리보기)
- SMS 시뮬레이터 (demo mode 전용)
- 인간 검토 큐 (needs_review=true 메시지)
- 메시지별 자동응답 생성 버튼

**API 호출:**
- `messagesAPI.getAll()` - 메시지 목록
- `messagesAPI.getContacts()` - 연락처
- `messagesAPI.simulateReceive()` - SMS 시뮬레이션
- `autoResponseAPI.generate()` - 자동응답 생성

---

#### `pages/Reservations.tsx` - 예약 관리

**기능:**
- 예약 목록 (상태, 날짜, 검색 필터)
- 예약 생성/수정 모달
- 예약 삭제 확인
- 객실 배정 버튼
- 네이버 동기화 버튼
- 성별 선택 UI

**API 호출:**
- `reservationsAPI.getAll()`, `create()`, `update()`, `delete()`
- `reservationsAPI.assignRoom(id, {room_number, date, apply_subsequent})`
- `reservationsAPI.syncNaver()`

---

#### `pages/RoomAssignment.tsx` - 객실 배정

**기능:**
- 드래그&드롭 기반 객실 배정 UI
- 좌측: 미배정 예약 목록
- 우측: 객실별 배정 현황 (날짜별 탭)
- 비밀번호 자동 생성 (6자)
- 객실 필터 (건물, 객실 타입)
- 자동배정 버튼

**SSE 연결:** `/api/events/room-assignment` → 다른 사용자의 배정 시 실시간 갱신

**API 호출:**
- `roomsAPI.getAll()`
- `reservationsAPI.getAll()` (미배정 필터)
- `reservationsAPI.assignRoom()`
- `roomsAPI.autoAssign()`

---

#### `pages/RoomSettings.tsx` - 객실 설정

**기능:**
- 객실 목록 CRUD
- 객실 타입, 용량 설정
- Building 관리
- NaverBizItem 링크 (N:M)
- 기숙사 설정 (침대 수)

**API 호출:**
- `roomsAPI.getAll()`, `create()`, `update()`, `delete()`
- `buildingsAPI.getAll()`, `create()`, `update()`, `delete()`
- `roomsAPI.getBizItems()`, `syncBizItems()`

---

#### `pages/Templates.tsx` - SMS 템플릿

**기능:**
- 템플릿 목록 CRUD
- Jinja2 변수 입력 UI
- 템플릿 분류 (room_guide, party_guide)
- 활성화/비활성화

**API 호출:**
- `templatesAPI.getAll()`, `create()`, `update()`, `delete()`

---

#### `pages/AutoResponse.tsx` - 자동응답 테스트

**기능:**
- 메시지 텍스트 입력
- 테스트 버튼 (저장 없이 응답 생성)
- 응답 텍스트 + confidence + source 표시
- 규칙 목록 조회

**API 호출:**
- `autoResponseAPI.test(message)`
- `rulesAPI.getAll()`

---

#### `pages/Settings.tsx` - 시스템 설정

**기능:**
- Naver 쿠키 관리
- 앱 상태 조회 (DEMO_MODE, 활성 job 등)

**API 호출:**
- `settingsAPI.getAppState()`, `updateNaverCookie()`

---

#### `pages/UserManagement.tsx` - 사용자 관리

**기능:**
- 사용자 목록 CRUD
- 역할 변경 (superadmin, admin, staff)
- 활성화/비활성화

**API 호출:** (auth 관련)
- `usersAPI.getAll()`, `create()`, `update()`, `delete()`

---

#### `pages/PartyCheckin.tsx` - 파티 체크인

**기능:**
- 파티 예약 조회
- 참가자 입실/퇴실 체크
- 성별별 인원 카운트
- 파티 규모 실시간 통계

**API 호출:**
- `partyCheckinAPI.getToday()`
- `partyCheckinAPI.checkIn()`, `checkOut()`

---

### 3.3 API 서비스 (`frontend/src/services/api.ts`)

Axios 기반 API 클라이언트. 각 도메인별 네임스페이스:

```typescript
messagesAPI = {
  getAll(), getContacts(), send(), getReviewQueue(), simulateReceive()
}

reservationsAPI = {
  getAll(), create(), update(), delete(), assignRoom(), syncNaver()
}

roomsAPI = {
  getAll(), create(), update(), delete(), getBizItems(), syncBizItems(), autoAssign()
}

rulesAPI = {
  getAll(), create(), update(), delete()
}

templatesAPI = {
  getAll(), create(), update(), delete()
}

templateSchedulesAPI = {
  getAll(), create(), update(), delete(), runNow()
}

autoResponseAPI = {
  generate(), test(), reloadRules()
}

dashboardAPI = {
  getStats()
}

// ... 기타 API
```

**인터셉터:**
- 요청: Authorization 헤더에 JWT 토큰 추가
- 응답: 401 에러 시 로그인 페이지 리다이렉트

---

### 3.4 공통 컴포넌트 (`frontend/src/components/`)

| 컴포넌트 | 설명 |
|---------|------|
| `Layout.tsx` | 전체 레이아웃 (헤더, 사이드바, 콘텐츠) |
| `ProtectedRoute.tsx` | 권한 검사 래퍼 |
| `FlowbiteTheme.tsx` | Flowbite 커스텀 테마 (Toss 색상) |
| `Sidebar.tsx` | 네비게이션 사이드바 |
| `Header.tsx` | 상단 헤더 (사용자, 알림) |

---

## 4. 인프라 및 배포

### 4.1 Docker Compose

```yaml
# docker-compose.yml
services:
  postgres:      # PostgreSQL (선택사항, demo는 SQLite)
  redis:         # Redis 캐시
  chromadb:      # ChromaDB 벡터 DB
```

**실행:**
```bash
docker compose up -d
```

---

### 4.2 CI/CD 파이프라인

`.github/workflows/` - GitHub Actions (선택사항)

예상 구성:
- Backend 테스트 (pytest)
- Frontend 빌드 (npm run build)
- Linting (flake8, eslint)

---

### 4.3 데이터베이스 마이그레이션

#### Alembic 사용 (PostgreSQL)

```bash
# 마이그레이션 파일 생성
cd backend
alembic revision --autogenerate -m "Add new column"

# 마이그레이션 적용
alembic upgrade head

# 롤백
alembic downgrade -1
```

#### SQLite (Demo)

`init_db()`에서 자동 마이그레이션 수행:
- 테이블 생성
- 누락된 컬럼 추가
- 레거시 필드명 변경

---

## 5. 데이터 흐름도

### 5.1 SMS 수신 → 자동응답 흐름

```
┌──────────────────────────────────┐
│ SMS 수신 (또는 시뮬레이션)         │
└────────────┬─────────────────────┘
             │
             ├─ from_: 010-1234-5678
             ├─ to: 010-9999-9999 (우리 번호)
             └─ content: "영업시간 어떻게 되나요?"
             │
             ▼
┌──────────────────────────────────┐
│ POST /webhooks/sms/receive       │
│ (또는 시뮬레이션)                 │
└────────────┬─────────────────────┘
             │
             ├─ 메시지 DB 저장 (status=received)
             ├─ direction=inbound
             └─ 자동응답 생성 호출
             │
             ▼
┌──────────────────────────────────┐
│ MessageRouter.generate_response()│
└────────────┬─────────────────────┘
             │
      ┌──────┴──────┐
      │             │
      ▼             ▼
┌───────────┐  ┌──────────────┐
│ Rule      │  │ LLM          │
│ Engine    │  │ Fallback     │
│ (regex)   │  │ (Claude API) │
└─────┬─────┘  └──────┬───────┘
      │ confidence=0.95  │ confidence=0.7-0.9
      │                  │
      └──────┬───────────┘
             │
             ▼
    ┌─────────────────┐
    │ confidence >=   │
    │ 0.6 ?          │
    └────┬────────┬──┘
         │        │
         │ NO     │ YES
         ▼        ▼
      ┌──┐    ┌──────────────┐
      │人│    │ 자동 발송     │
      │間│    │ send_sms()   │
      │檢│    └──────┬───────┘
      │査│           │
      └──┘           ▼
         │    ┌──────────────────┐
         │    │ Outbound Message │
         │    │ 저장 (sent)       │
         │    └──────────────────┘
         │
         └──→ 인간 검토 대기
              (needs_review=true)
```

---

### 5.2 네이버 예약 동기화 흐름

```
┌─────────────────────────────────────┐
│ Scheduler Job: sync_naver (10분마다) │
│ 시간대: 10:00~21:59                 │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ ReservationProvider.sync_reservations│
│ (Naver Smart Place API 호출)         │
└────────────┬────────────────────────┘
             │
             ├─ business_id로 조회
             ├─ date로 필터링
             └─ 예약 데이터 배열 반환
             │
             ▼
┌─────────────────────────────────────┐
│ 데이터베이스 병합                    │
│ (upsert: external_id 기준)          │
└────────────┬────────────────────────┘
             │
             ├─ 기존 예약: update
             ├─ 신규 예약: insert
             └─ 삭제됨: status=cancelled
             │
             ▼
┌─────────────────────────────────────┐
│ 자동배정 트리거 (미배정만)          │
│ auto_assign_rooms(today, tomorrow)  │
└─────────────────────────────────────┘
```

---

### 5.3 객실 자동배정 흐름

```
┌──────────────────────────────────────┐
│ 매일 08:00 또는 수동 트리거            │
└────────────┬─────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ auto_assign_rooms(target_date)       │
└────────────┬─────────────────────────┘
             │
             ├─ target_date 확정 예약 조회
             ├─ RoomAssignment 없는 것만
             └─ naver_biz_item_id로 필터
             │
             ▼
┌──────────────────────────────────────┐
│ 각 예약의 naver_biz_item_id로        │
│ 후보 객실 조회                       │
│ (BizItem → Room N:M 매핑)           │
└────────────┬─────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ 배정 가능 여부 확인                   │
│ - 용량 체크                          │
│ - 성별 lock (기숙사)                  │
│ - 수동 배정 제외                      │
└────────────┬─────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ RoomAssignment 생성                  │
│ (date, room_number, assigned_by)     │
└────────────┬─────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ SMS 태그 동기화                       │
│ sync_sms_tags()                      │
│ (section 업데이트 후 filters 재평가)  │
└────────────┬─────────────────────────┘
             │
             ▼
┌──────────────────────────────────────┐
│ SSE 이벤트 발행                       │
│ (프론트엔드 실시간 갱신)              │
└──────────────────────────────────────┘
```

---

### 5.4 템플릿 스케줄 발송 흐름

```
┌────────────────────────────────────────┐
│ APScheduler Trigger 발동               │
│ (schedule_type별 CronTrigger 또는      │
│  IntervalTrigger)                      │
└────────────┬─────────────────────────┘
             │
             ▼
┌────────────────────────────────────────┐
│ TemplateScheduleExecutor.execute()    │
└────────────┬─────────────────────────┘
             │
             ├─ 활성 시간대 확인
             │  (active_start_hour ~ active_end_hour)
             │
             ├─ 대상 예약 조회 (filters 평가)
             │  ├─ tag: 예약.tags 포함?
             │  ├─ assignment: section == 'room'?
             │  ├─ building: RoomAssignment의 room → building_id
             │  └─ room: RoomAssignment.room_number
             │
             ├─ 각 대상의 메시지 템플릿 렌더링
             │  (변수 치환: customer_name, room_number 등)
             │
             ▼
┌────────────────────────────────────────┐
│ SMS 발송 (Bulk)                       │
│ send_bulk(messages)                   │
└────────────┬─────────────────────────┘
             │
             ▼
┌────────────────────────────────────────┐
│ ReservationSmsAssignment.sent_at 업데이트│
│ (이후 exclude_sent=true로 중복 방지)    │
└────────────┬─────────────────────────┘
             │
             ▼
┌────────────────────────────────────────┐
│ 활동 로그 기록                          │
│ ActivityLog (action='sms_sent')        │
└────────────────────────────────────────┘
```

---

### 5.5 객실 배정 페이지 상호작용

```
┌──────────────────────────────────┐
│ RoomAssignment.tsx 마운트         │
└────────────┬─────────────────────┘
             │
             ├─ 미배정 예약 로드
             ├─ 객실 목록 로드
             └─ SSE 연결 수립
             │    (room-assignment 이벤트)
             │
             ▼
┌──────────────────────────────────┐
│ UI 렌더링                         │
│ 좌측: 예약 드래그 카드            │
│ 우측: 객실별 배정 현황 (날짜 탭)  │
└────────────┬─────────────────────┘
             │
      ┌──────┴──────┬──────────┐
      │             │          │
      ▼             ▼          ▼
  ┌──────┐   ┌────────────┐  ┌─────────┐
  │드래그│   │자동배정    │  │SSE 수신 │
  │드롭  │   │버튼 클릭   │  │(갱신)   │
  └──┬───┘   └────┬───────┘  └────┬────┘
     │            │               │
     │            ▼               ▼
     │       ┌────────────┐   ┌──────────┐
     │       │auto_assign │   │다른 사용자│
     │       │_rooms()    │   │의 배정    │
     │       └────┬───────┘   │감지, 화면│
     │            │           │갱신      │
     │            ▼           └──────────┘
     │       ┌────────────┐
     │       │배정 결과   │
     └──────→ 메시지      │
             └────┬───────┘
                  │
                  ▼
         ┌──────────────────┐
         │UI 즉시 업데이트   │
         │(낙관적 갱신)     │
         └──────────────────┘
```

---

## 6. 주요 데이터 구조 참고표

### 6.1 Reservation 객체

```json
{
  "id": 1,
  "external_id": "naver_12345",
  "customer_name": "김철수",
  "phone": "010-1234-5678",
  "check_in_date": "2026-03-20",
  "check_in_time": "15:00",
  "status": "confirmed",
  "section": "room",
  "room_number": "A101",
  "room_password": "123456",
  "naver_biz_item_id": "biz_item_001",
  "naver_room_type": "더블룸",
  "gender": "남",
  "age_group": "30대",
  "male_count": 1,
  "female_count": 1,
  "party_size": 2,
  "party_type": "1차만",
  "tags": "객후,1초,2차만",
  "naver_booking_id": "booking_5678",
  "created_at": "2026-03-18T10:30:00Z",
  "updated_at": "2026-03-18T12:00:00Z"
}
```

### 6.2 Message 객체

```json
{
  "id": 1,
  "message_id": "mock_1234567890",
  "direction": "inbound",
  "from_phone": "010-1234-5678",
  "to": "010-9999-9999",
  "message": "영업시간이 어떻게 되나요?",
  "status": "received",
  "auto_response": "08:00~22:00입니다.",
  "auto_response_confidence": 0.95,
  "is_needs_review": false,
  "response_source": "rule",
  "created_at": "2026-03-18T10:30:00Z"
}
```

### 6.3 TemplateSchedule 객체

```json
{
  "id": 1,
  "template_id": 2,
  "template_name": "객실안내",
  "template_key": "room_guide",
  "schedule_name": "체크인 객실안내",
  "schedule_type": "daily",
  "hour": 14,
  "minute": 0,
  "day_of_week": null,
  "interval_minutes": null,
  "active_start_hour": null,
  "active_end_hour": null,
  "timezone": "Asia/Seoul",
  "filters": [
    {"type": "assignment", "value": "room"}
  ],
  "date_filter": "today",
  "exclude_sent": true,
  "active": true,
  "next_run": "2026-03-20T14:00:00Z"
}
```

---

## 7. 개발 팁 및 문제 해결

### 7.1 로컬 개발 환경 설정

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
rm -f sms_demo.db  # 초기화
python -m app.db.seed  # 샘플 데이터 생성
uvicorn app.main:app --reload

# Frontend (새 터미널)
cd frontend
npm install
npm run dev
```

**API 문서:** http://localhost:8000/docs (Swagger UI)
**프론트엔드:** http://localhost:5173

---

### 7.2 Demo Mode에서 SMS 시뮬레이션

1. 프론트엔드 Messages 페이지 → SMS 시뮬레이터
2. From: 010-1234-5678, To: 010-9999-9999, Message: "영업시간?"
3. 백엔드 로그 확인: `[MOCK SMS RECEIVED]`
4. 메시지 목록에 나타남
5. 자동응답 생성 버튼 클릭 → 규칙 매칭 또는 LLM 호출

---

### 7.3 규칙 파일 핫 리로드

```bash
# 규칙 파일 수정 후
POST http://localhost:8000/api/auto-response/reload-rules

# 또는 UI에서 Settings 페이지에서 버튼 클릭
```

---

### 7.4 스케줄러 Job 수동 실행

```bash
# 특정 job 즉시 실행 (다음 일정까지 기다리지 않음)
POST http://localhost:8000/api/scheduler/jobs/{job_id}/run
```

**Job ID:** `sync_naver_reservations`, `daily_room_assign`, `template_schedule_{id}`

---

### 7.5 데이터베이스 초기화

```bash
# SQLite (Demo)
cd backend
rm -f sms_demo.db
python -m app.db.seed

# PostgreSQL (Prod)
# 1. Alembic 마이그레이션 실행
alembic upgrade head
# 2. init_db() 호출 (admin 생성, 데이터 마이그레이션)
```

---

### 7.6 프로덕션 배포 체크리스트

- [ ] `DEMO_MODE=false` 설정
- [ ] 모든 필수 환경변수 설정 (API 키, DB URL)
- [ ] JWT_SECRET_KEY 생성 및 설정
- [ ] ADMIN_DEFAULT_PASSWORD, STAFF_DEFAULT_PASSWORD 설정
- [ ] CORS_ORIGINS 설정 (와일드카드 제거)
- [ ] PostgreSQL 데이터베이스 생성
- [ ] SSL/TLS 인증서 설정
- [ ] 백엔드 및 프론트엔드 빌드 및 배포
- [ ] 헬스체크 확인 (`GET /health`)

---

## 8. 아키텍처 결정 사항

### 8.1 Protocol 기반 Provider Pattern (PEP 544)

**선택 이유:**
- Mock과 Real 구현을 언어 차원에서 호환 가능하게
- 타입 안정성 (mypy 지원)
- Duck typing 활용

**대안:** ABC (Abstract Base Class) - 더 명시적이지만 런타임 오버헤드 증가

---

### 8.2 APScheduler with AsyncIO

**선택 이유:**
- 비동기 작업 지원 (FastAPI와 통합)
- CRON 표현식 지원
- 다중 Trigger 조합 가능

**주의:** `scheduler = AsyncIOScheduler()`는 별도 event loop 필요

---

### 8.3 SQLAlchemy N:M 관계 (RoomBizItemLink)

**선택 이유:**
- 하나의 객실이 여러 네이버 상품에 매핑 가능
- 유연한 다대다 관계 관리

**레거시 호환:** `init_db()`에서 1:1 마이그레이션 자동 수행

---

### 8.4 ReservationSmsAssignment (SMS 태그)

**선택 이유:**
- 예약과 템플릿 간 N:M 관계 명시
- sent_at 추적으로 중복 발송 방지
- 수동 발송과 자동 발송 구분

**재계산 트리거:**
- 객실 배정 시
- 예약 상태 변경 시
- 템플릿 스케줄 변경 시

---

## 9. 확장 포인트

### 9.1 새로운 SMS 제공자 추가

1. `app/providers/base.py`에 Protocol 이미 존재
2. `app/real/sms_provider_name.py` 구현
3. `app/factory.py`의 `get_sms_provider()` 수정
4. 환경변수 추가 (필요 시)

### 9.2 새로운 필터 타입 추가

1. `app/scheduler/template_scheduler.py`의 `FILTER_BUILDERS` 수정
2. 조건 함수 추가: `def _condition_by_new_type(value, ctx) -> SQLAlchemy Clause`
3. 프론트엔드 필터 UI 추가

### 9.3 새로운 자동화 Job 추가

1. `app/scheduler/jobs.py`에 비동기 함수 정의
2. `setup_scheduler()`에서 `scheduler.add_job()` 호출
3. 선택사항: API 엔드포인트 추가 (scheduler.py)

---

**문서 작성일:** 2026-03-18
**최종 수정:** 현재 커밋 기준
