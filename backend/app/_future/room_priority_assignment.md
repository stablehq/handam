# 객실 배정 우선순위 시스템

## 개요
상품별 + 성별별로 객실 배정 순서를 커스텀할 수 있는 기능.

## 현재 상태 (구현 완료)
- Room ↔ NaverBizItem N:M 관계 (`RoomBizItemLink` 중간 테이블)
- 도미토리 성별 분리 배정 (혼숙 방지)
- 배정 순서: `Room.sort_order` 고정 순서

## 향후 구현 내용

### DB 변경
`room_biz_item_links` 테이블에 우선순위 컬럼 추가:

```python
class RoomBizItemLink(Base):
    # 기존 필드
    room_id = Column(Integer, ForeignKey("rooms.id"))
    biz_item_id = Column(String(100), ForeignKey("naver_biz_items.biz_item_id"))
    created_at = Column(DateTime)

    # 추가 필드
    male_priority = Column(Integer, default=0)      # 남성 배정 순서 (낮을수록 먼저)
    female_priority = Column(Integer, default=0)     # 여성 배정 순서 (낮을수록 먼저)
```

### 사용 예시

```
트윈룸 상품:
| 객실 | male_priority | female_priority |
|------|---------------|-----------------|
| 101  | 1 (첫번째)    | 5 (마지막)      |
| 102  | 2             | 4               |
| 103  | 3             | 3               |
| 104  | 4             | 2               |
| 105  | 5 (마지막)    | 1 (첫번째)      |

4인 도미토리 상품:
| 객실 | male_priority | female_priority |
|------|---------------|-----------------|
| 201  | 1             | 5               |
| 202  | 2             | 4               |
| 203  | 3             | 3               |
| 204  | 4             | 2               |
| 205  | 5             | 1               |
```

### 배정 흐름

```
트윈룸 예약자 (여자):
  → 연결된 객실을 female_priority 순 정렬: 105→104→103→102→101
  → 빈 방에 순차 배정, 부족하면 미배정

트윈룸 예약자 (남자):
  → 연결된 객실을 male_priority 순 정렬: 101→102→103→104→105
  → 이미 여자가 배정된 방은 스킵 (혼숙 방지)
  → 빈 방에 순차 배정, 부족하면 미배정

4인 도미토리 예약자 (여자):
  → female_priority 순: 205→204→203→202→201
  → 방의 dormitory_beds까지 채움

4인 도미토리 예약자 (남자):
  → male_priority 순: 201→202→203→204→205
  → 여자가 배정된 방 스킵
```

### 코드 변경 범위

1. `models.py` — `RoomBizItemLink`에 `male_priority`, `female_priority` 추가
2. `room_reassign.py` — 배정 시 sort 기준을 priority로 변경

```python
# 현재
rooms = biz_to_rooms[biz_item_id]
rooms.sort(key=lambda r: r.sort_order)

# 변경 후
rooms = biz_to_rooms[biz_item_id]
if gender == '여':
    rooms.sort(key=lambda r: r._female_priority)  # link의 female_priority
else:
    rooms.sort(key=lambda r: r._male_priority)     # link의 male_priority
```

3. `rooms.py` API — 우선순위 설정 엔드포인트 추가
4. `RoomManagement.tsx` — 드래그앤드롭 또는 숫자 입력으로 우선순위 설정 UI

### 프론트엔드 UI 방향
- 객실 모달에서 연결된 상품별로 "남성 순서", "여성 순서" 설정
- 또는 별도 "배정 순서 관리" 페이지에서 드래그앤드롭으로 순서 조정

### 의존성
- RoomBizItemLink N:M 구조 (완료)
- 성별 분리 배정 (완료)
- Alembic 마이그레이션 (priority 컬럼 추가)
