# HANDOFF

## Current [1774117636]
- **Task**: 스케줄 필터 확장 계획 수립 — 5가지 실제 문자 발송 시나리오 분석 및 필터 설계
- **Completed**:
  - 현재 템플릿 스케줄 필터 로직 전체 정리 (FILTER_BUILDERS, date_filter, target_mode, exclude_sent, once_per_stay)
  - 5가지 실제 문자 케이스 vs 현재 필터 호환성 분석 (case 5만 현재 가능, 나머지 4개 신규 필요)
  - 신규 필터/변수 기능 6가지 설계: 체크아웃 필터, 연박자 필터(stay_group_id 기반), 통계 날짜 분리, 성별별 버퍼, 성비 조건부 버퍼, 반올림
  - 프론트 UI 배치 계획 (기존 토글 버튼 패턴 유지 + 접이식 인원 설정 섹션)
  - 계획서 저장: `.omc/plans/schedule-filter-expansion.md`
- **Next Steps**:
  - 계획 검토 후 확정 (사용자가 더 좋은 방안 검토 중)
  - 확정 시 구현 순서: 체크아웃+연박자 필터 → 성별 버퍼+통계 날짜 → 반올림 → 성비 조건부 버퍼
  - (이전 세션) 코드 커밋/푸시, /ooo-tenant-check 시나리오 테스트, STABLE 데이터 세팅
- **Blockers**: 사용자 검토 대기 (계획 확정 전 구현 보류)
- **Related Files**:
  - `.omc/plans/schedule-filter-expansion.md` — 스케줄 필터 확장 계획서
  - `backend/app/scheduler/template_scheduler.py` — 현재 필터 로직 (FILTER_BUILDERS, get_targets)
  - `backend/app/templates/variables.py` — 템플릿 변수 계산 (participant_count, male/female_count)
  - `backend/app/db/models.py` — TemplateSchedule 모델 (신규 컬럼 추가 대상)
  - `frontend/src/pages/Templates.tsx` — 스케줄 필터 UI (모달 내 필터 섹션)

## Past 1 [1774072712]
- **Task**: 객실 자동배정 버그 수정 + 멀티테넌트 격리 전체 감사 + SMS 태그 해제 버그 수정
- **Completed**: DELETE/UPDATE 7곳 tenant_id 필터 추가, before_compile hook 보강, User 관리 테넌트 범위, SMS excluded 태그, /ooo-tenant-check 스킬 생성
- **Note**: tenant_context.py RecursionError 수정 포함

## Past 2 [1773998617]
- **Task**: 테넌트 격리 싱글톤/글로벌 상태 수정 + UI 개선
- **Completed**: SSE 테넌트별 큐 격리, MessageRouter 싱글톤 제거, MockLLMProvider 생성, factory lru_cache 제거, 파티 체크인 토스 스타일 UI
- **Note**: commits 36c6ce3~a3bd062
