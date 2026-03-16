# _future/ — 추후 확장 예정 기능

이 폴더에는 **아직 활성화되지 않은 확장 기능 코드**가 보관되어 있습니다.
코드는 참조용으로 작성되어 있으며, 활성화하려면 수정 및 통합 작업이 필요합니다.

## 파일 목록

### reservation_notifier.py
- **기능**: 예약 생성/수정 시 SQLAlchemy 이벤트 리스너로 자동 SMS 발송
- **원래 위치**: `app/reservation/notifier.py`
- **활성화 방법**:
  1. `send_sms_sync()`의 `asyncio.get_event_loop()` → FastAPI 호환 async 방식으로 수정
  2. `main.py`에서 `import app._future.reservation_notifier` 추가 (이벤트 리스너 등록)
  3. `notifications/service.py`, `scheduler/template_scheduler.py`와 역할 중복 검토
- **주의사항**: 현재 SMS 발송은 `notifications/service.py`와 `scheduler/template_scheduler.py`에서 처리 중. 이 모듈 활성화 시 중복 발송 가능성 체크 필요.

### room_priority_assignment.md
- **기능**: 상품별 + 성별별 객실 배정 순서 커스텀
- **핵심**: `RoomBizItemLink`에 `male_priority`, `female_priority` 컬럼 추가
- **예시**: 트윈룸 여자는 105→104→103 순서, 남자는 101→102→103 순서로 배정
- **의존성**: Room-BizItem N:M 구조 (완료), 성별 분리 배정 (완료)
- **구현 범위**: DB 마이그레이션 + 배정 로직 sort 변경 + 프론트엔드 우선순위 설정 UI

## 새 기능 추가 시
1. 이 폴더에 파일 생성 (`기능명.py`)
2. 이 README에 설명 추가
3. 활성화 시 적절한 위치로 이동 후 `main.py`에서 연결
