# HANDOFF

## Current [1773895714]
- **Task**: 도미토리 자동 배정 버그 수정 + 스케줄러/동기화 개선 + 리팩토링 누락 정리 + 연박 매일 발송 기능
- **Completed**:
  - 도미토리 자동 배정 버그 2건 수정 (people_count 실제 인원수, 성별 전원 체크)
  - 네이버 동기화 24시간 운영 (hour 제한 제거)
  - 스케줄러/프론트 버튼 역할 재정의 (스케줄러: auto 초기화→재배정, 버튼: 미배정자만 추가)
  - 동기화 후 자동 배정: 오늘은 미배정 유지, 내일 이후만 배정
  - 6시간 동기화 상태 활동 로그 추가
  - 스케줄 발송 로그에 객실 정보 표시 (Room→Building 관계)
  - _build_template_context 삭제 → calculate_template_variables 통합
  - participant_count: 예약 건수 COUNT → SUM(male_count+female_count) 실제 인원수
  - status Enum 통일 3곳 (문자열→ReservationStatus)
  - dead code 삭제 (get_targets_by_tag, send_campaign, render_room_guide)
  - GenderAnalyzer/GenderStat 제거 → 대시보드 실시간 SUM 계산
  - 예약자 추가 모달 연박 UI (체크박스+박수 인풋)
  - 연박 매일 발송: TemplateSchedule.target_mode (once/daily), ReservationSmsAssignment.date 컬럼
  - Alembic 마이그레이션 + 기존 데이터 백필
  - 스케줄 생성 모달 연박 발송 방식 UI (필터 영역에서 분리)
- **Next Steps**:
  - SMS 발송 로직 단순화 (execute_schedule 내부 → send_single_sms 호출로 통합)
  - target_mode 헬퍼 함수 추출 (3곳 중복 제거)
  - 필터 매칭 로직 단일화 (Python 버전 삭제 → SQLAlchemy 버전 통합)
  - send_by_assignment 날짜 필터 수정 (daily 모드 호환)
- **Blockers**: None
- **Related Files**:
  - `backend/app/scheduler/room_auto_assign.py` — 자동 배정 (용량/성별 체크)
  - `backend/app/scheduler/jobs.py` — 스케줄러 (24h 동기화, 10시 재배정, 6h 로그)
  - `backend/app/api/reservations_sync.py` — 동기화 후 자동 배정 (오늘 제외)
  - `backend/app/templates/variables.py` — calculate_template_variables (통합 함수)
  - `backend/app/services/room_assignment.py` — sync_sms_tags (date-aware 칩 생성)
  - `backend/app/scheduler/template_scheduler.py` — get_targets/execute_schedule (target_mode 분기)
  - `backend/app/services/sms_tracking.py` — record_sms_sent (date 파라미터)
  - `backend/app/api/dashboard.py` — 성별 통계 실시간 SUM
  - `frontend/src/pages/RoomAssignment.tsx` — 연박 UI, SmsAssignment.date
  - `frontend/src/pages/Templates.tsx` — 연박 발송 방식 설정 UI

## Past 1 [1773736337]
- **Task**: 파티만 태그 분리 리팩토링 + SMS 시스템 안정화 + 스태프 페이지
- **Completed**: 알리고 SMS 연동, send_single_sms 통합, sync_sms_tags 필터 매칭, 타임존 통일, 스태프 파티 체크인 페이지
- **Note**: commits including f59e3c0~592f068

## Past 2 [1773729796]
- **Task**: 알리고 SMS 연동 + 필드명 수정 + SMS 태그 시스템 개선 + 타임존 통일
- **Completed**: 알리고 연동, 필드명 수정, 건물관리 모달, SMS 통합 발송, 태그 필터 매칭, N+1 해소, 타임존 UTC 통일
- **Note**: commits f59e3c0~592f068
