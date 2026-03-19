# HANDOFF

## Current [1773938700]
- **Task**: 객실 배정 우선순위 + 멀티테넌트 인프라 구축
- **Completed**:
  - 객실 배정 우선순위: RoomBizItemLink에 male_priority/female_priority 추가
  - 자동 배정 시 여자 선배정 + 성별별 priority 순 객실 정렬
  - API: BizItemLinkInput/Response 스키마, upsert 패턴 (priority 보존)
  - 프론트: 배정 순서 관리 모달 (상품별 객실 우선순위 한번에 설정)
  - 멀티테넌트: TenantMixin 18개 모델, Tenant/UserTenantRole 신규 모델
  - before_compile SELECT 자동 필터 + before_flush INSERT 자동 주입
  - 모든 API get_db → get_tenant_scoped_db 전환 (auth/tenants 제외)
  - 사용자-테넌트 접근 권한 검증 (get_current_tenant_id에 UserTenantRole 체크)
  - JOIN 쿼리에 명시적 tenant_id 매칭 추가
  - 프론트: tenant store, X-Tenant-Id 헤더, 사이드바 전환기
  - 스케줄러: _for_each_tenant 테넌트 순회, factory _for_tenant 변형
  - Alembic 011(priority) + 012(multi-tenant) + 013(constraint scoping)
  - HANDAM 테넌트만 운영, STABLE은 준비되면 추가
- **Next Steps**:
  - STABLE 펜션 추가 시 _future/multi_tenant.md 참조
  - settings.py 네이버 쿠키 관리를 Tenant 테이블로 이전
  - SSE event_bus 테넌트 격리 (현재 글로벌 브로드캐스트)
  - matches_schedule의 target_date 인자화 (내일 예약 칩 생성 정확도)
  - fetchReservations마다 autoAssign 백그라운드 호출 → 불필요한 요청 제거 검토
- **Blockers**: None
- **Related Files**:
  - `backend/app/db/tenant_context.py` — ContextVar, before_compile, before_flush, TENANT_MODELS
  - `backend/app/api/deps.py` — get_tenant_scoped_db, get_current_tenant_id (접근 권한 검증 포함)
  - `backend/app/db/models.py` — TenantMixin, Tenant, UserTenantRole, 18개 모델
  - `backend/app/scheduler/jobs.py` — _for_each_tenant, bypass_tenant_filter
  - `backend/app/factory.py` — get_sms_provider_for_tenant, get_reservation_provider_for_tenant
  - `backend/app/_future/multi_tenant.md` — 전체 계획서 (Architect+Critic 리뷰 완료)
  - `frontend/src/stores/tenant-store.ts` — 테넌트 상태 관리
  - `frontend/src/pages/RoomSettings.tsx` — 배정 순서 관리 모달

## Past 1 [1773907001]
- **Task**: 연박 매일 발송 + SMS 시스템 단순화 + 날짜별 파티 정보 + 버그 수정
- **Completed**: 도미토리 버그, 네이버 동기화, 리팩토링, 연박 매일 발송, 칩 date-aware, 파티 체크인 연박, 예약 모달 연박 UI
- **Note**: commits bb4a5ec~e76c93b

## Past 2 [1773895714]
- **Task**: 도미토리 버그 수정 + 스케줄러/동기화 개선 + 리팩토링 정리 + 연박 매일 발송
- **Completed**: 도미토리 용량/성별 버그, 24h 동기화, 스케줄러 역할 재정의, 템플릿 변수 통합, dead code 삭제, 연박 발송 기본 구조
- **Note**: commits bb4a5ec~ee51035
