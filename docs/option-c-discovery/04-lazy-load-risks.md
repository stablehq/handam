# Phase 0 산출물 #4: ORM lazy-load 위험 사이트 표

> 옵션 C 후 session 종료 후 ORM 객체에 lazy attribute 접근 시 동작 변화 위험.

## relationship() 정의 17개

| 모델 | 관계 | 모드 | back_populates / backref | cascade |
|--|--|--|--|--|
| `Reservation.room_assignments` | RoomAssignment | **lazy=select** (기본) | back_populates | all,delete-orphan |
| `ReservationSmsAssignment.reservation` | Reservation | lazy=select | backref="sms_assignments" | - |
| `ReservationSmsAssignment.schedule` | TemplateSchedule | lazy=select | - | - |
| `RoomBizItemLink.room` | Room | lazy=select | back_populates | - |
| `RoomBizItemLink.biz_item` | NaverBizItem | lazy="joined" + viewonly=True | primaryjoin | - |
| `Building.rooms` | Room | lazy=select | back_populates | - |
| `RoomGroup.rooms` | Room | lazy=select | back_populates | - |
| `Room.biz_item_links` | RoomBizItemLink | lazy=select | back_populates | all,delete-orphan |
| `Room.building` | Building | lazy=select | back_populates | - |
| `Room.room_group` | RoomGroup | lazy=select | back_populates | - |
| `RoomAssignment.reservation` | Reservation | lazy=select | back_populates | - |
| `RoomAssignment.room` | Room | lazy=select | - | - |
| `TemplateSchedule.template` | MessageTemplate | lazy=select | backref="schedules" | - |
| `PartyCheckin.reservation` | Reservation | lazy=select | backref="party_checkins" | - |
| `ReservationDailyInfo.reservation` | Reservation | lazy=select | backref="daily_info" | - |
| `UserTenantRole.user` | User | lazy=select | backref | - |
| `UserTenantRole.tenant` | Tenant | lazy=select | - | - |

→ **17개 중 16개가 lazy=select (기본)**. 1개만 lazy=joined.

## 명시 eager load (selectinload / joinedload) 사용처

| 위치 | 관계 | 의도 |
|--|--|--|
| `dashboard.py:136` | `selectinload(TemplateSchedule.template)` | 대시보드 N+1 방지 |
| `templates.py:94` | `selectinload(MessageTemplate.schedules)` | 템플릿 목록 + 연결 스케줄 |
| `template_schedules.py:267` | `selectinload(TemplateSchedule.template)` | 동일 |
| `room_assignment_invariants.py:40` | `joinedload(RoomAssignment.room)` | 배치 검증 N+1 방지 |
| `buildings.py:67/85/128/163` | `selectinload(Building.rooms)` | 빌딩 목록 + 방 |
| `rooms.py:201` | `selectinload(Room.biz_item_links)` | 방 + biz_item |
| `room_auto_assign.py:59` | `selectinload(Room.biz_item_links)` | 자동 배정 입력 |

→ **8곳 명시 eager**. 나머지 lazy 의존 패턴은 잠재적 위험 사이트.

## 위험 사이트 분류

### 🔴 [Critical] session 종료 후 객체 접근 패턴

**Pattern X: API endpoint 응답 변환 시 lazy load**

FastAPI 가 Pydantic 응답 모델로 변환할 때 ORM 객체의 lazy attribute 를 접근. session 이 close 되면 `DetachedInstanceError`.

검사 필요:
```bash
grep -rn "@router\.\(get\|post\|patch\|put\|delete\)" backend/app/api --include="*.py" | wc -l
# 200+ endpoints, 각각 응답 변환 시점 확인 필요
```

옵션 C 후엔 session.close() 시점에 ORM 객체가 detached 되며, 이 객체가 응답 변환 후에도 살아있다가 lazy 접근하면 새 query 가 필요. 새 session 에 tenant 가 없으면 RuntimeError.

**대응**: response_model 정의에서 nested relationship 사용하는 곳은 endpoint 안에서 explicit `selectinload` 강제 또는 dict 변환.

### 🟠 [High] backref 자동 생성 관계

`Reservation.sms_assignments` (backref) - 현재 다음 위치에서 사용:
```bash
grep -rn "\.sms_assignments\b" backend/app --include="*.py"
```

이 attribute 접근 시점이 session close 후일 가능성. lazy load 트리거 위험.

### 🟠 [High] event_sms_hook 백그라운드 task 객체 전달

```python
# event_sms_hook.py:52
task = loop.create_task(_run_event_hook(ids, tenant_id))
```

ID 리스트만 전달하므로 ORM 객체 detach 위험 없음. 안전. 옵션 C 후에도 동일.

### 🟡 [Medium] schedule_manager.py:84 — 이미 ID 만 capture
주석: "Capture only schedule ID to avoid detached instance errors"

이미 의식하고 ID 만 capture 중. 옵션 C 후에도 안전.

### 🟡 [Medium] settings.py:301-303 — merge 패턴
```python
merged_tenant = db.merge(tenant)
```
다른 session 에서 가져온 tenant 객체를 merge. 옵션 C 후에도 동일 패턴 유효.

## 옵션 C 후 새로 생기는 lazy-load 위험

### Pattern A: API endpoint 의 yield 후 lazy load
`get_tenant_scoped_db` 가 yield 하는 db 가 endpoint 종료 후 close. 이 시점에 응답 객체의 lazy attribute 가 평가되면 — 옵션 C 후엔 새 session 이 필요한데, 새 session 의 tenant 정보가 명시되어야 함.

**검증 필요**: 모든 endpoint 의 응답 모델 + ORM 객체 변환 시점을 audit. 잠재 위험 사이트 표 작성 후 explicit eager load 추가.

### Pattern B: 스케줄러 잡 내부에서 객체를 다른 함수에 전달
```python
# template_scheduler.py 안
schedule = self.db.query(TemplateSchedule).filter(...).first()
# ... 한참 후 ...
template_key = schedule.template.template_key  # ← lazy load
```
옵션 C 후엔 db.info['tenant_id'] 가 self.db 에 있으므로 동작. 단, `self.db` 가 여전히 살아있어야 함.

### Pattern C: SSE long-lived connection
`events.py:73-99` 의 `event_stream` 안에서 SSE 가 분 단위 유지. 그 동안 db 는 어떻게 유지?

```bash
grep -A 30 "async def event_stream" backend/app/api/events.py
```

검증 필요.

## 권장 조치 (Phase 별)

### Phase 1 (호환 shim 도입 시점)
- 새 session factory 가 detach 시에도 `session.info['tenant_id']` 가 객체에 metadata 로 박히도록 처리 (불필요할 수 있음 — 검증)
- detached object 가 session 다시 attach 시 어떤 session 으로 가는지 결정

### Phase 2 (API layer)
- 모든 endpoint 응답 모델 audit
- response_model 에 nested relationship 있는 곳은 explicit eager load 추가
- 검증 테스트: endpoint 호출 → 응답 정상 + DetachedInstanceError 0건

### Phase 4 (service layer) 후
- 백그라운드 task 가 ORM 객체 받으면 → ID 만 받도록 변환
- 또는 새 session_for_tenant 안에서 다시 query

## 위험 점수 종합

| 사이트 종류 | 개수 | 위험도 |
|--|--|--|
| API 응답 변환 시 lazy load 의심 | 200+ endpoints | 🔴 Critical (audit 필수) |
| 명시 eager load 적용된 곳 | 8곳 | 🟢 Safe |
| 백그라운드 task ID 전달 | 1곳 | 🟢 Safe |
| Detached merge 패턴 | 1곳 | 🟢 Safe |
| SSE long-lived | 1곳 | 🟡 Medium (별도 audit) |

## 다음 단계

Phase 0 의 후속 작업으로 **API endpoint 응답 변환 정밀 audit** 추가 산출물 필요할 수 있음. 200+ endpoint 전부 검사 어려우면 다음 우선순위로:

1. 가장 자주 호출되는 endpoint (dashboard, reservations 목록)
2. 응답 model 에 nested 가 명시된 곳
3. 운영 로그에서 DetachedInstanceError 발생 이력 확인
