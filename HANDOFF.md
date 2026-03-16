# HANDOFF

## Current [1773666411]
- **Task**: 전체 프로젝트 감사 + CRITICAL/HIGH/MEDIUM 이슈 해결 + 객실-상품 N:M 개선 + 다중 필터 스케줄 + 건물 관리 + 네이밍 컨벤션 정리
- **Completed**:
  - 프로젝트 전체 감사 (9개 전문가 에이전트 병렬 분석)
  - CRITICAL 7건 해결: 인증 추가(7 엔드포인트), JWT Secret 하드코딩 제거, 비밀번호 정책+Rate Limiting, Mock/Real SMS 반환값 통일, 타입 버그 수정, DB 롤백 추가
  - HIGH 26건 해결: N+1 쿼리 6건, SMS 추적 헬퍼 추출, factory 역방향 import 수정, API prefix 통일, 인덱스 8개 추가, Dashboard 쿼리 통합, Alembic env.py 복구, Docker 멀티스테이지+비루트, CI 테스트+캐시+롤백, 서버사이드 필터링
  - MEDIUM 16건 해결: datetime 통일, 하드코딩 설정 외부화, ReDoS/Path Traversal 방어, Provider 싱글톤, import 스타일 통일
  - Room-BizItem N:M 관계 구현 (RoomBizItemLink 중간 테이블, 멀티셀렉트 토글 칩 UI)
  - 도미토리 배정 로직 N:M 기반 전환 (성별만 분리, 인실 그룹핑 제거)
  - Building 테이블 + 건물 관리 CRUD + 건물별 객실 그룹핑
  - 다중 필터 스케줄 시스템 (FILTER_BUILDERS AND 체이닝: assignment/building/room/tag)
  - 활동 로그 시스템 (ActivityLog 테이블 + 페이지 + 5곳 연동)
  - campaigns 시스템 제거 → SmsSender + ActivityLog로 대체
  - SMS 추적 통합 (3중 체계 → ReservationSmsAssignment 단일 source of truth)
  - NotificationService dead code 제거
  - CampaignLog → ActivityLog 완전 이전
  - 네이밍 컨벤션 정리 16건 (파일명, Relationship, Boolean is_, 날짜 _at, Config 접두사)
  - 객실 배정 페이지 UX 개선 (날짜 전환 깜빡임 제거, 자동배정 플로팅 카드+오버레이, 연박자 파스텔톤)
- **Next Steps**:
  - M18~M22 의존성 정리 (미사용 패키지 제거, CVE 패치)
  - H10 FK 제약 추가 (Alembic 마이그레이션)
  - DEPRECATED 필드 최종 제거 (room_sms_sent, party_sms_sent, sent_sms_types, naver_biz_item_id, target_type/value, CampaignLog)
  - 향후 확장: 객실 배정 우선순위 시스템 (_future/room_priority_assignment.md)
  - 테스트 인프라 구축 (pytest + conftest.py)
- **Blockers**: None
- **Related Files**:
  - `backend/app/db/models.py` - 전체 모델 (Building, RoomBizItemLink, ActivityLog 추가)
  - `backend/app/scheduler/template_scheduler.py` - FILTER_BUILDERS 다중 필터 엔진
  - `backend/app/scheduler/room_auto_assign.py` - N:M 기반 자동배정 (renamed)
  - `backend/app/services/sms_sender.py` - SMS 발송 서비스 (campaigns에서 이동)
  - `backend/app/services/sms_tracking.py` - SMS 추적 공통 헬퍼
  - `backend/app/services/activity_logger.py` - 활동 로그 헬퍼
  - `backend/app/api/buildings.py` - 건물 관리 API
  - `backend/app/api/activity_logs.py` - 활동 로그 API
  - `backend/app/_future/` - 향후 확장 기능 (notifier, 배정 우선순위)
  - `frontend/src/pages/RoomSettings.tsx` - 객실+건물 설정 (renamed)
  - `frontend/src/pages/RoomAssignment.tsx` - 객실 배정 (UX 개선)
  - `frontend/src/pages/ActivityLogs.tsx` - 활동 로그 페이지
  - `frontend/src/pages/Templates.tsx` - 다중 필터 스케줄 UI

## Past 1 [1773391397]
- **Task**: Lightsail 서버 배포 + Supabase 연결 + 기존 CRM 분석
- **Completed**: 기존 CRM 완전 분석, AWS Lightsail 배포, Supabase PostgreSQL 연결, Enum 호환성 수정
- **Note**: commit 6043e3c, 고정 IP 43.201.235.206

## Past 2 [1773333022]
- **Task**: 코드 정리 + SMS 태그 자동 관리 + 발송 확인 모달
- **Completed**: 백엔드/프론트 dead code 정리, sync_sms_tags 중앙 함수 구현, SMS 발송 확인 모달
- **Note**: StorageProvider 제거, mock/rules 삭제
