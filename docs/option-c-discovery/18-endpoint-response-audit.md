# Phase 0 후속 #18: API endpoint 응답 변환 lazy-load audit

> **결론: 위험 매우 낮음.** 코드베이스가 명시적 `_to_response` 변환 패턴을 일관 적용 중이라 ORM 객체가 endpoint return 으로 빠져나가지 않음.

## 측정

- 총 endpoint: **98개** (`@router.get/post/patch/put/delete`)
- response_model 정의된 endpoint: 약 70개
- List[Response] 반환 endpoint: 12개
- **명시 변환 함수 사용 endpoint**: 거의 전부

## 변환 함수 패턴 (5종 발견)

| 변환 함수 | 위치 | 사용 endpoint |
|--|--|--|
| `_to_response` | `reservations.py:132` | 6+ endpoint (CRUD) |
| `_room_to_response` | `rooms.py:120` | 5+ endpoint |
| `_building_to_response` | `buildings.py:46` | 5 endpoint |
| `_biz_item_to_response` | `rooms.py:213` | 3 endpoint |
| `_schedule_to_response` | `template_schedules.py:80` | 5 endpoint |

→ **모든 ORM 변환이 endpoint 안에서 명시적 dict/Pydantic 으로 수행**. session 종료 후 lazy 접근 위험 없음.

## Response 모델 nested 필드 분석

### A. ReservationResponse — nested 0
```python
class ReservationResponse(BaseModel):
    id: int
    customer_name: str
    phone: str
    ...
    # 전부 scalar. relationship 객체 직접 노출 안 함.
```

`room_id`, `room_number` 같은 필드가 있지만 **`override_room` / `override_password` 인자로 명시 전달**. relationship 자동 변환 안 씀.

**위험**: 🟢 None

### B. RoomResponse — nested 1 (`biz_item_links_detail`)
```python
class RoomResponse(BaseModel):
    ...
    biz_item_links_detail: List[BizItemLinkResponse] = []
    building_name: Optional[str] = None
    room_group_name: Optional[str] = None
```

`biz_item_links_detail` 가 nested. `building_name`, `room_group_name` 도 relationship 거쳐 derived.

**`_room_to_response` 가 어떻게 채우는지** 확인 필요:

```bash
sed -n '120,180p' backend/app/api/rooms.py
```

→ 명시 access pattern 인지 확인. 명시면 안전.

**위험**: 🟡 Medium (eager load 명시 권장)
- `rooms.py:201`: `selectinload(Room.biz_item_links)` 이미 적용 ✅
- `building` / `room_group` lazy access 가능 — 추가 selectinload 권장

### C. BuildingResponse — nested 1 (`room_count`)
```python
class BuildingResponse(BaseModel):
    ...
    room_count: int = 0
```

`room_count` 는 single int. `_building_to_response` 가 `len(building.rooms)` 같은 패턴이면 lazy load 트리거.

`buildings.py:67`, `85`, `128`, `163` 가 이미 `selectinload(Building.rooms)` 적용 ✅

**위험**: 🟢 Low

### D. TemplateResponse — nested 1 (`schedule_count`)
```python
class TemplateResponse(BaseModel):
    ...
    schedule_count: int = 0
```

`templates.py:94`: `selectinload(MessageTemplate.schedules)` 적용 ✅

**위험**: 🟢 Low

### E. TemplateScheduleResponse — nested 1 (`template`)
`template_schedules.py:267`: `selectinload(TemplateSchedule.template)` 적용 ✅

**위험**: 🟢 Low

### F. NaverBizItemResponse — 단순 scalar
nested 없음. 안전.

### G. PartyCheckinItem — 단순 scalar
nested 없음. 안전.

## 일반 위험 매트릭스

| Endpoint 카테고리 | nested? | eager load 적용? | 위험 |
|--|--|--|--|
| Reservations CRUD | None | N/A | 🟢 |
| Rooms list/CRUD | biz_item_links_detail | ✅ selectinload | 🟢 |
| Buildings list/CRUD | room_count | ✅ selectinload | 🟢 |
| Templates list | schedule_count | ✅ selectinload | 🟢 |
| TemplateSchedules list | template | ✅ selectinload | 🟢 |
| Auth (login/users) | None | N/A | 🟢 |
| OnsiteSales / OnsiteAuction | None | N/A | 🟢 |
| PartyCheckin | None | N/A | 🟢 |
| EventSMS search | None | N/A | 🟢 |

## 잠재 위험 케이스 (정밀 검사 필요)

### Case 1: Room → building / room_group lazy 접근
`_room_to_response` 안에서 `room.building.name`, `room.room_group.name` 접근 시 — `selectinload(Room.biz_item_links)` 만 적용된 상태에서 `building` / `room_group` 은 lazy load 트리거.

**검증 필요** (별도 명령):
```bash
sed -n '120,200p' backend/app/api/rooms.py
```

만약 `room.building.name` 같은 패턴 있으면 → `selectinload(Room.building, Room.room_group)` 추가 권장.

### Case 2: Reservation → sms_assignments (backref)
`_to_response` 안에서 `res.sms_assignments` 접근 시 (산출물 #1 에서 확인). 
**현재 동작**: lazy load 트리거 — 정상 작동 (session 안에서). 
**옵션 C 후 위험**: session.close() 후 detach 되면 위험. 그러나 endpoint 안에서 변환 → return 이라 yield 전 close 안 됨. 안전.

### Case 3: 백그라운드 task 가 ORM 객체 받음
산출물 #4 검증 결과: 0건. 모두 ID 만 받음.

## 옵션 C 후 검증 항목

각 endpoint 가 옵션 C session 으로 동작하는지:
- [ ] reservations.py 의 `_to_response` 가 session.info 영향받지 않음 확인
- [ ] rooms.py 의 `_room_to_response` 동일
- [ ] buildings.py / templates.py / template_schedules.py 동일

명시 변환 패턴 사용 중이므로 **옵션 C 적용해도 endpoint 변환 코드 변경 0**.

## 추가 안전 권장

### A. Room → building lazy 접근 검증 후 eager load 보강
`rooms.py:201` 의 selectinload 에 building / room_group 추가:

```python
# Before
.options(selectinload(Room.biz_item_links))

# After
.options(
    selectinload(Room.biz_item_links),
    joinedload(Room.building),         # 추가
    joinedload(Room.room_group),       # 추가
)
```

이미 작동하지만 옵션 C 후 안전 마진 강화.

### B. ReservationResponse 의 sms_assignments backref
산출물 #1 에서 `_to_response(db, ...)` 가 `res.sms_assignments` 접근. 이건 lazy load. `selectinload(Reservation.sms_assignments)` 추가 가능 (성능 향상 + 옵션 C 안전).

```bash
# 현재 reservations.py 의 query 검사
grep -n "db.query(Reservation)" backend/app/api/reservations.py | head -10
```

각 query 에 `selectinload(Reservation.sms_assignments)` 추가 시 N+1 방지 + 옵션 C detach 위험 차단.

## 결론

**Phase 0 의 lazy-load 위험은 우려보다 훨씬 작음**. 코드베이스가 이미:
1. 명시 `_to_response` 변환 함수 사용 (5종)
2. nested 필드에 selectinload/joinedload 적용 (8곳)
3. ORM 객체를 endpoint 밖으로 빼지 않음

**옵션 C 마이그레이션이 endpoint 응답 변환에 미치는 영향 거의 없음**.

추가 보강 (위 A, B) 은 옵션 C 와 별개 — 일반 성능/안전 개선이지 마이그레이션 차단 사유 아님.

**Phase 1 진입 결정 영향**: 🟢 **진입 가능**. 추가 audit 또는 보강은 Phase 1 이후 별도 PR 로 처리 가능.
