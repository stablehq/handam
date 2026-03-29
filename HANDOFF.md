# HANDOFF

## Current [1774678131]
- **Task**: Timezone 통일 + 코드 잔재 정리 + 스킬 업그레이드
- **Completed**:
  - **Timezone 통일** (13개 파일, commit `71fcefb`)
    - `config.py`에 `today_kst()` / `today_kst_date()` 헬퍼 추가
    - 백엔드 5개 파일의 `date.today()` 17곳 → KST 헬퍼로 교체
    - `activity_logs.py` 날짜 필터 + 통계 엔드포인트 KST→UTC 변환 수정
    - 프론트 `normalizeUtcString()` 유틸 추가 (date-only 보호 포함)
    - 6개 페이지에서 UTC-naive 파싱 정규화 적용
  - **코드 잔재 정리** (6개 파일, -74줄, commit `07ce15e`)
    - 28개 커밋 일괄 점검 (architect + critic 교차 검증)
    - 죽은 함수 `matches_schedule()` 삭제, 미사용 import 6건, 죽은 state/function 4건
    - `modal.tsx` onClose prop은 UI 라이브러리 호환성으로 유지 판단
  - **스킬 업그레이드** (3개 스킬)
    - `ooo-change-validator`: Phase 4 교차 검증 토론 (architect + critic) 추가
    - `ooo-code-cleaner`: Phase 3B 교차 검증 (architect + critic) 추가
    - `ooo-e2e-sync`: Phase 2.3 기존 항목 중복 체크 추가
  - **노션 투두 추가**: #8 객실 이동 로그 시간별 묶기, #9 수동배정 인원 제한 허용
  - **이은지 예약 SMS 칩 조사**: `party_alert` 칩이 수동(manual) 할당된 것 확인, 타 예약에서 번진 것 아님
- **Next Steps**:
  - SMS 테스트 실행 (3/28부터 매일 체크리스트 확인)
  - TODO #1: ParticipantSnapshot 시간대별 갱신
  - TODO #7: 객실 배정 드래그 중 자동 스크롤
  - TODO #8: 객실 이동 로그 시간별 묶기
  - TODO #9: 수동배정 시 일반실 인원 제한 허용
  - TODO #5: 모바일 버튼 레이아웃 정리
  - TODO #6: PWA 설정 (iOS 탭 전환 방지)
- **Blockers**: None
- **Related Files**:
  - `backend/app/config.py` — today_kst() / today_kst_date() 헬퍼
  - `backend/app/scheduler/template_scheduler.py` — KST 통일 적용
  - `frontend/src/lib/utils.ts` — normalizeUtcString() 유틸
  - `~/.claude/skills/ooo-change-validator/SKILL.md` — 교차 검증 Phase 4 추가
  - `~/.claude/skills/ooo-code-cleaner/SKILL.md` — Phase 3B 교차 검증 추가
  - `~/.claude/skills/ooo-e2e-sync/SKILL.md` — Phase 2.3 중복 체크 추가

## Past 1 [1774619519]
- **Task**: 도미토리 bed_order + 커스텀 드래그 전환 + UX 개선 + SMS 테스트 데이터
- **Completed**: bed_order 도입, HTML5→pointer 드래그 전환, sticky 헤더/stripe/구분선 UX, SMS 테스트 예약자 11건 생성, Click-Select 계획서 작성
- **Note**: commits f911c86..5b236cd

## Past 2 [1774603943]
- **Task**: SMS 칩 배정 로직 통합 + column_match AND 수정 + 도미토리 인원수 버그 수정 + 객실 그룹 UX 개선
- **Completed**: chip_reconciler 통합, column_match AND 수정, 네이버 API USEDATE 수정, sync reconcile_date 파라미터, is_long_stay 리팩토링, dead code 정리
- **Note**: commits a2da705..432318f
