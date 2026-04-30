# Key Patterns & Gotchas

## 1. Multi-Tenant Isolation
- ContextVar 기반 (`backend/app/db/tenant_context.py`)
- SQLAlchemy `before_compile` → 모든 SELECT 에 `WHERE tenant_id = X` 자동 추가
- SQLAlchemy `before_flush` → 모든 INSERT 에 `tenant_id` 자동 주입
- **함정**: 스케줄러/마이그레이션처럼 전역 작업이 필요하면 반드시 `bypass_tenant_filter` 컨텍스트 매니저 사용. 안 그러면 빈 결과/오작동.
- 프론트엔드 모든 요청에 `X-Tenant-Id` 헤더 필요 → `src/services/api.ts` Axios 인터셉터가 처리.

## 2. Provider Factory + DEMO_MODE Hot-Swap
- `backend/app/factory.py` 의 `get_*_provider_for_tenant(tenant)` 만 사용.
- 라우터/서비스가 `httpx`, `anthropic` 등을 직접 import 금지 — 항상 provider 레이어 통과.
- 테넌트마다 `aligo_testmode`, `naver_cookie` 등 설정이 다르므로 provider는 테넌트 인자 필수.

## 3. SMS Template Schedule 흐름
1. `TemplateSchedule` (DB) ↔ APScheduler 트리거 (`scheduler/schedule_manager.py`)
2. 트리거 시 `TemplateScheduleExecutor.execute_schedule()` 호출 (`scheduler/template_scheduler.py`)
3. 대상 예약 필터링 (building/room/assignment/column_match)
4. 변수 계산 (`templates/variables.py`) → 렌더링 (`templates/renderer.py`)
5. SMS 발송 (`services/sms_sender.py`) → ActivityLog 기록
- **함정**: 템플릿 변수 누락(`{{}}`) 검증은 `tests/unit/test_unreplaced_vars.py` 가 담당 — 새 변수 추가 시 테스트도 갱신.

## 4. Room Assignment
- `services/room_assignment.py`: `assign_room()` 은 SELECT FOR UPDATE 로 동시성 제어.
- 배정 변경 시 `sync_sms_tags()` 가 ReservationSmsAssignment 자동 동기화 — 직접 ReservationSmsAssignment 만지지 말 것.
- 자동 배정(`scheduler/room_auto_assign.py`)은 도미토리 성별 잠금 + 용량 체크 적용.

## 5. SMS Sender
- Aligo: SMS(≤90바이트) / LMS(>90바이트) 자동 감지, 500건 배치.
- 전화번호 형식 검증 가드 존재(최근 커밋 `9196347`) — 숫자 아니면 발송 차단.
- 발송 시 ActivityLog (target/success/failed_count) 기록 필수.

## 6. 네이버 동기화
- 쿠키 인증 (DB Tenant 레코드에 저장, 런타임 업데이트 가능).
- Semaphore(10) 동시성 제한.
- `extend_stay` 에 `original_group_kind` 추가됨(커밋 `ab49b1b`) — 네이버→manual 변환 모니터링용.
- 5분 주기 자동 동기화 + 6시간마다 상태 로그.

## 7. Auto-Response
- 우선순위: DB Rules → YAML Rules → LLM → Review Queue.
- confidence ≥ 0.6 자동 발송, 미만은 검토 큐.

## 8. 프론트엔드 디자인 시스템
- **Flowbite React + Toss Invest 디자인** (Ant Design 아님!).
- 디자인 토큰/클래스는 `frontend/src/index.css` 에 집중.
- 새 컴포넌트는 CLAUDE.md "Frontend Design Guidelines" 표 그대로 따를 것 (버튼 size/color/아이콘 크기, 간격, 라운딩, 다크 모드).

## 9. 인증
- JWT access 1h + refresh 7d, bcrypt 해싱.
- 역할: SUPERADMIN > ADMIN > STAFF (STAFF 는 파티 체크인만 접근).
- 토큰 자동 갱신은 Axios 인터셉터에서 처리 — 프론트 코드는 신경 쓸 필요 없음.

## 10. 시간대
- Asia/Seoul (KST) 기준. UTC 직접 사용 금지. dayjs/datetime 모두 KST.

## 11. Diag / 로그 검증
- 진단 로그 시스템 + 매일 정답지(diag-golden) 검증 워크플로 운영 중 (최근 커밋 다수).
- 로그 검증 요청 시 `/oh-my-claudecode:ooo-log-validation` 스킬 활용 가능.

## 12. CampaignLog 레거시
- 신규 활동 기록은 항상 `ActivityLog`. CampaignLog 는 읽기 전용 레거시.
