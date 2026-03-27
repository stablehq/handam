# HANDOFF

## Current [1774603943]
- **Task**: SMS 칩 배정 로직 통합 + column_match AND 수정 + 도미토리 인원수 버그 수정 + 객실 그룹 UX 개선
- **Completed**:
  - **칩 배정 로직 통합 (chip_reconciler)**
    - `chip_reconciler.py` 신규: 단일 매칭 소스 + 생성/삭제 양방향
    - `schedule_utils.py` 신규: 순환 의존 해소 (get_schedule_dates 추출)
    - `sync_sms_tags` → chip_reconciler 위임 래퍼
    - `auto_assign_for_schedule` → chip_reconciler 위임 (create+delete)
    - 스케줄 PUT에서 필터 변경 시 자동 reconcile 호출
    - `filters.py`에 `apply_structural_filters()` standalone 함수 추가
    - `matches_schedule()` deprecated
  - **column_match 필터 AND 수정**
    - `_build_filter_groups`: 같은 컬럼 column_match OR → AND 변경
    - `notes:contains:추2 OR notes:contains:테스트` → AND로 수정
  - **네이버 API USEDATE 수정**
    - reconcile job의 `dateFilter=STARTDATE` → `USEDATE` 변경
    - STARTDATE가 네이버 API 422 에러 → 처음부터 작동 안 했었음
    - USEDATE로 수정 후 59건 조회 성공, party_participants 정상 갱신
  - **sync 엔드포인트에 reconcile_date 파라미터 추가**
  - **인라인 is_long_stay → compute_is_long_stay() 통일** (naver_sync.py)
  - **프론트엔드 dead code 정리**: isMultiNight 삭제, stayGroupAPI.detect 삭제
  - **미사용 import 14개 정리** (3개 백엔드 파일 + template_scheduler.py)
  - **객실 그룹 UX**: 체크박스 그리드 → 구분선 삽입 방식, 테두리 → 하단 1px 라인
- **Next Steps**:
  - TODO #7: 객실 배정 드래그 중 자동 스크롤 (필수)
  - TODO #1: ParticipantSnapshot 시간대별 갱신
  - TODO #5: 모바일 버튼 레이아웃 정리
  - TODO #6: PWA 설정 (iOS 탭 전환 방지)
  - B206 등 기존 초과배정 수동 재배정 필요
  - 미커밋 프론트엔드 변경 정리 (UI 컴포넌트 마이그레이션 관련 14개 파일)
- **Blockers**: None
- **Related Files**:
  - `backend/app/services/chip_reconciler.py` — 통합 칩 동기화 모듈
  - `backend/app/services/schedule_utils.py` — get_schedule_dates 추출
  - `backend/app/services/filters.py` — apply_structural_filters + AND 수정
  - `backend/app/real/reservation.py` — USEDATE 수정
  - `backend/app/api/reservations.py` — reconcile_date 파라미터 추가
  - `backend/app/services/naver_sync.py` — is_long_stay 리팩토링
  - `frontend/src/pages/RoomAssignment.tsx` — 그룹 구분선 UX + isMultiNight 삭제

## Past 1 [1774540510]
- **Task**: 모바일 반응형 디자인 + 연박 수동 묶기/해제 + 로그인 저장
- **Completed**: 모바일 반응형 (Layout/Dashboard/Reservations/RoomSettings/Templates/ActivityLogs), 연박 묶기/해제 UI, 예약자 추가 버튼 복원, 로그인 저장
- **Note**: 객실배정은 PC와 동일 가로스크롤 방식으로 결정

## Past 2 [1774345481]
- **Task**: Flowbite → shadcn/ui 완전 마이그레이션 + 반응형 디자인 계획 수립
- **Completed**: 16개 shadcn 컴포넌트 생성, 12개 페이지 교체, flowbite-react 패키지 제거
- **Note**: Phase 1-7 마이그레이션 완료
