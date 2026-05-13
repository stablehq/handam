# 객실 업그레이드 후기 안내(`room_upgrade_review`) 커스텀 칩 — 구현 계획안 v4

**작성일**: 2026-05-13 (v4 — 코너 케이스 심층 검증 반영)
**custom_type**: `room_upgrade_review` (기존 운영 호칭: "객후")
**기준 패턴**: `services/surcharge.py` 와 동형 (유틸 함수만 공유, lifecycle 은 독립)

---

## 1. 도메인 룰

배정된 객실이 예약한 객실보다 상위 등급이고, **예약 인원이 예약 상품 기준 인원을 초과하지 않는** 경우 무료 업그레이드로 판정해 후기 요청 SMS 를 발송한다.

### 발송 조건 (모두 만족 시)
1. 배정 객실 등급 > 예약 상품 등급
2. `guest_count <= booked_product_base_capacity` (인원 초과면 추가요금 영역 — surcharge 가 처리)
3. `Room.grade`, `NaverBizItem.grade` 모두 NOT NULL
4. **stay 내 이미 객후 칩이 없을 것** (sent/unsent 무관 — stay 당 평생 1번)

### 차단 / 미발송
| 조건 | 동작 | diag |
|------|------|------|
| `room_upgrade_review` 스케줄 비활성 / 미존재 | 즉시 early return | (없음 — 진입 가드) |
| 인원 초과 (`guest_count > base`) | skip | `skipped_overcapacity` |
| 등급 동일하거나 다운그레이드 | skip | (없음 — 정상 케이스) |
| stay 내 이미 객후 칩 존재 (sent/unsent 무관) | skip | (없음 — stay 단위 dedup) |
| `Room.grade` 또는 `NaverBizItem.grade` NULL | skip | `grade_missing` (critical, 진입 가드 통과 후에만) |
| `_resolve_product_base_capacity` == 0 (biz_item 미상) | skip | `base_capacity_unknown` (critical) |

**중요**: surcharge 칩 존재 여부와 **무관하게** 자기 룰로 판정. 운영자가 surcharge 칩을 토글/면제해도 객후 동작에 영향 없음.

---

## 2. 객실 등급 체계

| Grade | 라벨 (헤더 가이드 전용) |
|-------|----------------------|
| 1 | 도미토리 |
| 2 | 더블 |
| 3 | 트윈 |
| 4 | 트윈3인실 |
| 5 | 스위트 |

- DB 컬럼: `Room.grade INT NULL`, `NaverBizItem.grade INT NULL`
- UI dropdown 표시: 숫자만 (`1`, `2`, …, `5`)
- 헤더 가이드 텍스트 (공통): `"1=도미 < 2=더블 < 3=트윈 < 4=트윈3인실 < 5=스위트"`
- 백엔드 validation: `1 <= grade <= 5` (프론트 dropdown 만으로는 불충분)
- NULL fallback: 비교 불가 → critical diag (스케줄 활성 시에만) + skip

---

## 3. 파이프라인 추가 지점

### ① 스키마

`backend/app/db/models.py`
- `Room.grade Integer nullable=True`
- `NaverBizItem.grade Integer nullable=True`

Alembic revision (신규):
- 두 컬럼 추가 (nullable, default 없음)
- backfill 없이 시작 — 운영자가 모달에서 직접 입력

**보존 메커니즘 명시 (방어적 문서화)**
- `backend/app/api/rooms.py:291` 부근에 주석:
  ```python
  # NaverBizItem 운영자 전용 컬럼(naver sync 가 덮어쓰면 안 되는 것):
  #   display_name, default_capacity, section_hint, default_party_type, grade
  # 아래 update 문에 이 컬럼들이 포함되지 않도록 유지할 것.
  ```

### ② 등급 유틸 (얇은 read)

`backend/app/services/room_grade.py` **★ 신규**

```python
ROOM_GRADE_LABELS = {
    1: "도미토리", 2: "더블", 3: "트윈",
    4: "트윈3인실", 5: "스위트",
}
GRADE_GUIDE_TEXT = "1=도미 < 2=더블 < 3=트윈 < 4=트윈3인실 < 5=스위트"
GRADE_MIN = 1
GRADE_MAX = 5

def grade_of_room(room) -> int | None:
    return room.grade if room else None

def grade_of_biz_item(biz_item) -> int | None:
    return biz_item.grade if biz_item else None

def is_valid_grade(value) -> bool:
    return isinstance(value, int) and GRADE_MIN <= value <= GRADE_MAX
```

키워드 매칭 없음 — 단순 DB 컬럼 read.

### ②-bis. 공통 인원/기준인원 유틸 추출

`backend/app/services/surcharge.py:85` 의 `_resolve_product_base_capacity` 는 underscore prefix 라 외부 import 어색. PR 1 에서:
- **rename**: `_resolve_product_base_capacity` → `resolve_product_base_capacity`
- surcharge.py 내부 호출 1곳도 함께 갱신
- `compute_guest_count` 는 prefix 없으니 그대로 import

이로써 `room_upgrade_review.py` 가 surcharge 내부 함수에 의존한다는 인상이 사라지고, 두 도메인이 공통 유틸을 공유한다는 의미가 명확해짐.

### ③ 도메인 reconcile 서비스

`backend/app/services/room_upgrade_review.py` **★ 신규** (surcharge.py 와 동형 — lifecycle 독립)

```python
ROOM_UPGRADE_REVIEW = 'room_upgrade_review'

def _find_schedule(db) -> TemplateSchedule | None:
    return db.query(TemplateSchedule).filter(
        TemplateSchedule.schedule_category == 'custom_schedule',
        TemplateSchedule.custom_type == ROOM_UPGRADE_REVIEW,
        TemplateSchedule.is_active == True,
    ).first()

def _has_existing_chip_in_stay(db, schedule, res_id) -> bool:
    """stay 내 같은 schedule_id 칩이 존재 (sent/unsent 무관)."""
    return db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == res_id,
        ReservationSmsAssignment.schedule_id == schedule.id,
    ).first() is not None

def decide_chip(db, reservation, target_date) -> bool:
    ra = get_room_assignment(db, reservation.id, target_date)
    if not ra or not ra.room:
        return False

    # 1. 인원 초과 가드 — surcharge 와 동일한 공통 유틸 재사용
    from app.services.surcharge import (
        compute_guest_count,
        resolve_product_base_capacity,  # PR 1 에서 prefix 제거
    )
    guest_count = compute_guest_count(reservation)
    booked_base = resolve_product_base_capacity(db, reservation, ra.room)
    if booked_base == 0:
        diag("room_upgrade_review.base_capacity_unknown", level="critical",
             res_id=reservation.id,
             biz_item_id=reservation.naver_biz_item_id)
        return False
    if guest_count > booked_base:
        diag("room_upgrade_review.skipped_overcapacity",
             res_id=reservation.id,
             guest_count=guest_count, base=booked_base, date=target_date)
        return False

    # 2. 등급 비교
    biz_item = (
        db.query(NaverBizItem)
        .filter(NaverBizItem.biz_item_id == str(reservation.naver_biz_item_id))
        .first()
        if reservation.naver_biz_item_id else None
    )
    booked_grade = grade_of_biz_item(biz_item)
    assigned_grade = grade_of_room(ra.room)
    if booked_grade is None or assigned_grade is None:
        diag("room_upgrade_review.grade_missing", level="critical",
             res_id=reservation.id,
             booked=booked_grade, assigned=assigned_grade,
             biz_item_id=reservation.naver_biz_item_id,
             room_id=ra.room.id, date=target_date)
        return False

    return assigned_grade > booked_grade


def reconcile_room_upgrade_review(db, res_id, date) -> None:
    """단건 reconcile.

    ★ 진입 가드: 스케줄 비활성/미존재 시 즉시 return — decide_chip 호출 안 함.
    이 가드로 PR 2 배포 직후 (스케줄 미활성) grade_missing critical 폭주 차단.
    """
    schedule = _find_schedule(db)
    if not schedule:
        return  # 안전망

    reservation = db.query(Reservation).filter(Reservation.id == res_id).first()
    if not reservation:
        return

    if decide_chip(db, reservation, date):
        # ★ stay 단위 1칩 가드: 이미 stay 내 객후 칩(sent/unsent 무관) 있으면 추가 생성 skip
        if _has_existing_chip_in_stay(db, schedule, res_id):
            return
        _ensure_chip(db, res_id, date, schedule)
    else:
        # 해당 date 의 미발송 칩만 삭제 (다른 date sent 칩은 보존)
        _remove_chip(db, res_id, date, schedule)


def reconcile_room_upgrade_review_batch(db, res_ids, date) -> None:
    schedule = _find_schedule(db)
    if not schedule:
        return  # 안전망
    for rid in res_ids:
        try:
            reconcile_room_upgrade_review(db, rid, date)
        except Exception as e:
            diag("room_upgrade_review.reconcile_failed",
                 level="critical", res_id=rid, error=str(e)[:200])


def _delete_all_room_upgrade_review_chips(db, res_id, date) -> None:
    # sent_at IS NULL 인 미발송 칩만 삭제 (surcharge 패턴과 동일)
    ...
```

**Diag emits**:
- `room_upgrade_review.chip_applied` (res_id, booked_grade, assigned_grade, delta) — info
- `room_upgrade_review.chip_deleted` (res_id, reason) — info
- `room_upgrade_review.skipped_overcapacity` (res_id, guest_count, base, date) — info
- `room_upgrade_review.grade_missing` (res_id, booked, assigned, biz_item_id, room_id, date) — **critical** (스케줄 활성 시에만)
- `room_upgrade_review.base_capacity_unknown` (res_id, biz_item_id) — **critical**
- `room_upgrade_review.reconcile_failed` (res_id, error) — **critical**

### ④ 레지스트리 등록

`backend/app/services/custom_schedule_registry.py`

```python
CUSTOM_SCHEDULE_TYPES["room_upgrade_review"] = "무료 업그레이드 후기 안내(객후)"

def _refresh_room_upgrade_review(db, target_date):
    """surcharge 와 동일 패턴 — (1) 배정된 예약 (2) 객후 미발송 칩 보유 예약 → batch reconcile.

    reconcile 자체에 _find_schedule 진입 가드가 있어 스케줄 비활성 시 no-op."""
    ...

PRE_SEND_REFRESH_HANDLERS["room_upgrade_review"] = _refresh_room_upgrade_review
```

**PER_DATE_DEDUP_CUSTOM_TYPES 미등록** — `exclude_sent` 가 날짜 무관 차단. 또한 ③의 stay 단위 1칩 가드가 칩 row 자체도 stay 당 1개로 제한.

### ⑤ 칩 변동 진입점 hook

| 파일 | 위치 | 추가 호출 | 비고 |
|------|------|----------|------|
| `services/reconcile.py` | `reconcile_all_chips()` | 4번째 칩으로 추가 | `assign_room` / `reconcile_dates` 자동 커버 |
| `services/room_assignment.py` | push-out (~443) | `_delete_all_room_upgrade_review_chips(...)` | surcharge 삭제 옆 |
| `services/room_assignment.py` | `unassign_room` (~638) | `_delete_all_room_upgrade_review_chips(...)` | surcharge 삭제 옆 |
| `services/room_auto_assign.py` | 113-114 | `reconcile_room_upgrade_review_batch(...)` | surcharge_batch 옆 |
| `services/naver_sync.py` | Phase 5 (~350) | `reconcile_room_upgrade_review_batch(...)` | surcharge_batch 옆 |
| `services/naver_sync.py` | 배정 삭제 (~791) | `_delete_all_room_upgrade_review_chips(...)` | surcharge 삭제 옆 |
| **`api/rooms.py` `PATCH /grades` (신규)** | grade 변경 직후 | **영향받는 예약 batch reconcile** | ★ v4 신규 |
| **biz_items grade 변경 API** | grade 변경 직후 | **영향받는 예약 batch reconcile** | ★ v4 신규 |
| `scheduler/template_scheduler.py` | — | **수정 불필요** | ④의 PRE_SEND_REFRESH 자동 dispatch |
| `services/filters.py:369` | — | **수정 불필요** | 주석 only |

`reconcile_all_chips()` 가 이미 `room_assignment.py:532-533` 와 `reconcile_dates(~945)` 에서 호출되므로 자동 커버. grade 변경 시 stale 칩 방지를 위해 PATCH 엔드포인트에서 batch reconcile 추가.

#### grade 변경 시 reconcile 범위
- `PATCH /api/rooms/grades`: 변경된 Room.id 들에 대해 → 오늘 이후 RoomAssignment.reservation_id 수집 → `reconcile_room_upgrade_review_batch` (date별 호출 또는 reconcile_all_chips 우회 호출)
- biz_items grade 변경: 변경된 biz_item_id 의 Reservation 수집 → 동일

PR 1 작업 시점에는 reconcile 함수가 아직 없으므로, PR 1 코드에서는 **TODO 주석으로 hook 자리만 표시** → PR 2 에서 채움. PR 1 단독 배포 시점에는 grade 변경 후 칩 상태가 stale 한데, 어차피 객후 스케줄 미활성이라 발송 영향 없음.

### ⑥ 프론트엔드 — 등급 설정 모달 (신규)

**객실 설정 페이지** (`frontend/src/pages/RoomSettings.tsx`)
- 상품설정 버튼 옆에 **"객실 등급"** 버튼 추가 (color="light", size="sm")
- 전체 객실의 grade 미설정 건수를 헤더에 배지로 표시 (예: "객실 등급 (3건 미설정)")

**객실 등급 모달** (`frontend/src/pages/RoomSettings/RoomGradeModal.tsx` **★ 신규**)
- Modal size: `lg`
- 객실 목록 세로 나열 (room_number, room_type, building 정보 표시)
- 각 행 우측에 등급 dropdown (Select, sizing="sm")
- 옵션: `1`, `2`, `3`, `4`, `5` (숫자만)
- 헤더 가이드 텍스트: `"1=도미 < 2=더블 < 3=트윈 < 4=트윈3인실 < 5=스위트"` (한 줄, text-caption)
- 미설정 객실 행: 노란 경고 배지 ("미설정")
- 저장: bulk PATCH 한 번 호출 (단일 트랜잭션)

**상품설정 모달 (기존)**
- 상품 행에 동일 등급 dropdown 추가
- 동일 헤더 가이드 노출

**백엔드 API**
- `PATCH /api/rooms/grades` — body: `{ items: [{id, grade}, ...] }`
  - 각 item 의 grade 1~5 범위 validation (`is_valid_grade`)
  - 범위 외 / 정수 아님 → 400 Bad Request
  - 단일 트랜잭션 (부분 실패 시 전체 rollback)
  - 권한: `require_admin_or_above`
  - **(PR 2 에서) 영향받는 예약 batch reconcile 호출**
- biz_items grade PATCH (단건 또는 bulk, 기존 패턴에 맞춰)

### ⑦ 마이그레이션

Alembic revision 1개 (PR 1):
- `Room.grade`, `NaverBizItem.grade` 컬럼 추가 (nullable, default 없음)

기존 "객후" 태그 필터 변환 (PR 3):
```sql
-- 기존 "객후" 태그 사용 스케줄 → custom_schedule + room_upgrade_review 로 전환
-- filters JSON 에서 객후 태그만 제거 (다른 필터는 보존)
UPDATE template_schedules
SET schedule_category = 'custom_schedule',
    custom_type = 'room_upgrade_review',
    filters = (
      -- filters JSON 배열에서 {"type":"tag","value":"객후"} 항목만 제거
      ...
    )
WHERE filters LIKE '%"객후"%';
```

**참고**: `alembic/004:45` 의 `'객후': 'post_checkout'` short_label 매핑은 이미 실행 완료된 마이그레이션이라 직접 영향 없음. 다만 기존 `template_key='post_checkout'` 의 ReservationSmsAssignment 가 남아있다면 PR 3 SQL 로 정리.

### 배포 절차
1. (로컬) DB 컬럼 추가 + Alembic 적용 → Supabase 동기화
2. (로컬) 객실/상품 등급 모달에서 등급 수동 입력 → Supabase 자동 저장
3. **사전 확인 SQL 로 등급 미설정 0건 확인** (아래 §5)
4. PR 2 배포 — reconcile 서비스 + hook (스케줄 미활성이라 `_find_schedule` 진입 가드로 실 발송 0건)
5. PR 3 배포 — 기존 "객후" 태그 스케줄 → custom_type 변환
6. 24h 모니터링: critical diag 0건 확인

### ⑧ Diag 정답지 + 테스트

**diag-golden draft** (`docs/diag-golden/actions/_draft/`)
- `room-upgrade-review-applied.yaml` — 무료 업그레이드 → 칩 발생
- `room-upgrade-review-skipped-overcapacity.yaml` — 인원 초과 시 차단
- `room-upgrade-review-grade-missing.yaml` — 등급 미설정 critical
- `room-upgrade-review-stay-dedup.yaml` — 다박 stay 당 1칩 검증
- 모두 `promotion_threshold=3`

**테스트** (`backend/tests/`)
- `test_room_upgrade_review.py`
  - 도미(1) → 더블(2) 배정 + 인원 ≤ base → 발송 대상
  - 더블(2) → 트윈(3) 배정 + 인원 > base → `skipped_overcapacity`
  - 같은 등급 배정 → 미발송 (diag 없음, 정상)
  - 더블 → 스위트 + biz_item.grade NULL → `grade_missing` critical + 미발송
  - biz_item_id NULL (수동 예약) → `grade_missing` critical + 미발송
  - **★ 다박 D1=더블/D2=스위트/D3=트윈 → stay 당 1칩만 (첫 업그레이드 박일에 생성, 다른 박일 추가 시도 시 skip)**
  - **★ 스케줄 비활성 상태 → reconcile 호출해도 `decide_chip` 호출 안 됨 (grade_missing critical 미발화)**
  - **★ Room.grade 변경 시 batch reconcile → 영향받은 예약의 칩 상태 갱신**
  - idempotent (reconcile 2회 호출 → no-op, 칩 1건만 존재)
  - **surcharge 상태와 무관성 검증**:
    - surcharge sent 칩 존재 + 인원 미초과 + 등급 업 → 객후 발송 (B안 핵심)
    - surcharge 미발송 칩 존재 + 인원 미초과 + 등급 업 → 객후 발송
- `test_rooms_grade_api.py`
  - PATCH bulk grade 업데이트 성공
  - grade=0 / grade=6 / grade="abc" → 400
  - 권한 (admin or above)
  - 단일 트랜잭션 (한 행 실패 시 전체 rollback)
  - **★ grade 변경 후 영향받은 예약의 reconcile hook 호출 검증 (PR 2)**

---

## 4. 사전작업 체크리스트 (★ v4 신규 — 누락/중복/에러 방지)

### PR 1 시작 전

- [ ] **`_resolve_product_base_capacity` rename 결정** — prefix 제거 + `surcharge.py` 내부 호출 1곳 동시 갱신. 또는 `services/room_capacity.py` 추출 (rename 권장)
- [ ] **`rooms.py:291` 보존 필드 주석 추가** — naver sync 가 운영자 컬럼을 덮어쓰지 않는다는 암묵적 규약을 명시
- [ ] **현재 객실/상품 데이터 현황 SQL 확인**:
  ```sql
  SELECT room_type, COUNT(*) FROM rooms WHERE is_active = TRUE GROUP BY room_type;
  SELECT name, biz_item_id, default_capacity FROM naver_biz_items WHERE is_active = TRUE;
  ```
  → 운영자가 등급 입력할 대상 객실/상품 개수 파악
- [ ] **기존 "객후" 태그 스케줄 영향 범위 SQL**:
  ```sql
  SELECT id, schedule_name, filters FROM template_schedules WHERE filters LIKE '%"객후"%';
  ```
- [ ] **PR 1 alembic revision 의 nullable 보장** — backfill 없이 NULL 시작
- [ ] **PR 1 grade PATCH API 의 hook 자리 TODO 주석 합의** — PR 2 에서 채울 위치 명시

### PR 1 배포 후, PR 2 시작 전

- [ ] **등급 입력 진행률 0건 확인**:
  ```sql
  SELECT COUNT(*) - COUNT(grade) AS missing FROM rooms WHERE is_active = TRUE;
  SELECT COUNT(*) - COUNT(grade) AS missing FROM naver_biz_items WHERE is_active = TRUE;
  ```
  → 양쪽 모두 missing=0 확인
- [ ] **운영자가 양쪽 모달에서 동일 척도로 입력했는지 spot check** — 예: 더블 객실 = grade 2, 더블 상품 = grade 2 일관성
- [ ] **PR 2 코드 작성 시 `_find_schedule` 진입 가드 필수 포함** — `reconcile_room_upgrade_review` / `reconcile_room_upgrade_review_batch` 둘 다
- [ ] **stay 단위 1칩 가드 (`_has_existing_chip_in_stay`) 구현 확정** — sent/unsent 무관 카운트
- [ ] **grade PATCH API 의 reconcile hook 추가** — PR 1 의 TODO 자리를 채움

### PR 2 배포 후, PR 3 시작 전

- [ ] **24h 모니터링** — diag 로그에 `room_upgrade_review.grade_missing`, `base_capacity_unknown` critical 0건 확인 (스케줄 미활성이라 진입 가드로 차단되어야 정상)
- [ ] **reconcile_all_chips 성능 영향 확인** — assign/unassign API 응답 시간 회귀 없는지 모니터링
- [ ] **기존 "객후" 태그 스케줄 재확인** (운영 중 변경됐을 수 있음)
- [ ] **기존 `template_key='post_checkout'` ReservationSmsAssignment 잔존 여부 확인**:
  ```sql
  SELECT COUNT(*) FROM reservation_sms_assignments WHERE template_key = 'post_checkout';
  ```
  → 있으면 PR 3 SQL 에서 함께 처리

### PR 3 배포 후

- [ ] **24h 모니터링** — `room_upgrade_review.*` critical 0건
- [ ] **첫 발송 추적** — `chip_applied` diag 발화 → 실제 발송된 SMS 가 예상한 예약/박일 맞는지 spot check
- [ ] **다박 stay 단위 1칩 실 검증** — 다박 예약의 미발송 칩 row 수 SQL 확인:
  ```sql
  SELECT reservation_id, COUNT(*) FROM reservation_sms_assignments
  WHERE template_key = 'room_upgrade_review' AND sent_at IS NULL
  GROUP BY reservation_id HAVING COUNT(*) > 1;
  ```
  → 결과 0건 (1 res 당 미발송 칩 최대 1개)

---

## 5. 사전 확인 SQL 통합

```sql
-- 1. PR 1 배포 후: 등급 입력 진행률
SELECT COUNT(*) AS total, COUNT(grade) AS graded,
       COUNT(*) - COUNT(grade) AS missing
FROM rooms WHERE is_active = TRUE;

SELECT COUNT(*) AS total, COUNT(grade) AS graded,
       COUNT(*) - COUNT(grade) AS missing
FROM naver_biz_items WHERE is_active = TRUE;

-- 2. 기존 "객후" 태그 사용 스케줄 (마이그레이션 영향 범위)
SELECT id, schedule_name, filters FROM template_schedules
WHERE filters LIKE '%"객후"%';

-- 3. 기존 post_checkout 칩 잔존
SELECT COUNT(*) FROM reservation_sms_assignments
WHERE template_key = 'post_checkout';

-- 4. PR 3 배포 후: 다박 stay 1칩 무결성
SELECT reservation_id, COUNT(*) FROM reservation_sms_assignments
WHERE template_key = 'room_upgrade_review' AND sent_at IS NULL
GROUP BY reservation_id HAVING COUNT(*) > 1;
```

---

## 6. 코너 케이스 시나리오 정합성

| 시나리오 | 예상 동작 | 가드 |
|---------|----------|------|
| 1. Room.grade 2→3 변경 | PATCH 직후 영향 예약 batch reconcile → 미발송 칩 갱신 | ⑤ grade PATCH hook |
| 2. 객실 변경 (D1=더블 → D1=스위트) | `assign_room` → `reconcile_all_chips` → 새 객실 grade 기준 재평가 | ⑤ reconcile.py 4번째 칩 |
| 3. 네이버 sync 가 NaverBizItem 새로 추가 (grade NULL) | 다음 배정 시 grade_missing critical + skip | ③ critical diag + 모달 미설정 배지 |
| 4. surcharge 칩 수동 토글 off | 객후 무관 (B안) | (B안 채택으로 자동 해결) |
| 5. PR 2 배포 후 PR 3 적용 전 daily_room_assign | `_find_schedule` 진입 가드로 reconcile 무동작 | ③ 진입 가드 |
| 6. 다박 D1(더블)/D2(스위트)/D3(트윈) + 예약=더블 | D2 reconcile 시 칩 1개 생성. D3 reconcile 시 stay 1칩 가드로 skip. 발송 1회. UI 칩 row 1개 | ③ `_has_existing_chip_in_stay` |
| 7. D2 칩 발송 후 D3 재배정으로 더 큰 업그레이드 | sent 칩 보존 + `_has_existing_chip_in_stay` True → D3 칩 추가 생성 skip. exclude_sent 가 stay 단위라 어차피 재발송 안 함 | ③ stay 가드 |
| 8. 운영자가 객실 등급 1→NULL 로 되돌리려 함 | dropdown 1~5 만 있고 NULL 옵션 없음 — 일단 정책상 변경 후 NULL 만들기는 어려움. 필요 시 PR 1 모달에 "미설정" 옵션 명시적 추가 가능 | ⑥ UI 결정 |
| 9. 새 객실 추가 시 grade NULL | 모달 미설정 배지로 가시화. 배정 시 grade_missing critical (스케줄 활성 시) | ⑥ 미설정 배지 |

---

## 7. 핵심 결정 사항 (확정)

| # | 결정 | 변경 이력 |
|---|------|----------|
| 등급 범위 | 1~5 | v2 확정 |
| dropdown 표시 | 숫자만 (`3`), 헤더에 가이드 | v2 확정 |
| 등급 입력 타이밍 | 로컬에서 PR 1 적용 후 수동 입력 → Supabase | v2 확정 |
| custom_type 명 | `room_upgrade_review` | v2 확정 |
| 동적 변수 | 불필요 (`variables.py` 수정 없음) | v2 확정 |
| PER_DATE_DEDUP | 미등록 (stay 당 1회) | v2 확정 |
| 차단 로직 | 인원 초과 시 skip (B안 — surcharge 칩 의존 제거) | v3 확정 |
| 도미 → 일반실 무료 업그레이드 | 발송 대상 | v2 확정 |
| grade 범위 validation | 백엔드에서 1~5 강제 | v3 신규 |
| room_auto_assign hook | 113-114 추가 | v3 신규 |
| assign_room 중복 호출 | reconcile.py 경유로 통일 | v3 신규 |
| **stay 단위 1칩 가드** | `_has_existing_chip_in_stay` 가드 | **v4 신규** |
| **`_find_schedule` 진입 가드** | reconcile 진입 시 첫 호출 — critical 폭주 방지 | **v4 신규** |
| **grade 변경 API → reconcile hook** | PATCH 직후 영향 예약 batch reconcile | **v4 신규** |
| **공통 유틸 prefix 제거** | `_resolve_product_base_capacity` → `resolve_product_base_capacity` | **v4 신규** |

---

## 8. 위험 요소 및 완화책

| 위험 | 완화책 | 가드 |
|------|--------|------|
| 운영자가 등급을 미설정 → 객후 누락 | `grade_missing` critical + 모달 미설정 배지 | ⑥ |
| 운영자가 양쪽 척도를 다르게 입력 | 양쪽 모달 헤더에 같은 가이드 텍스트 | ⑥ |
| 기존 "객후" 태그 필터 잔존 | PR 3 마이그레이션 SQL 일괄 변환 | ⑦ |
| 등급 모달 저장 부분 실패 | bulk PATCH 단일 트랜잭션 | ⑥ |
| 백엔드 우회 (curl) grade=99 | `is_valid_grade` 백엔드 validation | ② |
| `room_auto_assign` 후 객후 누락 | hook 추가 (113-114) | ⑤ |
| `assign_room` 객후 2회 호출 | reconcile.py 경유로 통일 | ⑤ |
| `_resolve_product_base_capacity` underscore | PR 1 에서 rename | ②-bis |
| **다박 stay 의 미발송 칩 복수** | `_has_existing_chip_in_stay` 가드 | ③ |
| **PR 2 배포 직후 critical 폭주** | `_find_schedule` 진입 가드 | ③ |
| **Room/biz_item.grade 변경 후 stale 칩** | PATCH API 에서 reconcile hook | ⑤ |
| **NaverBizItem.grade 휘발 (naver sync)** | upsert 가 명시 컬럼만 update — 자동 보존. 주석으로 방어적 명시 | ① |

---

## 9. 변경 이력

- **v1** (2026-05-13): 초안 — 키워드 매칭 방식
- **v2** (2026-05-13): DB 컬럼 + 등급 모달로 전환, 1~5 범위 확정
- **v3** (2026-05-13): 1차 Impact Analysis 반영
  - B안 (인원 직접 계산) 채택 — surcharge 칩 의존 제거
  - `room_auto_assign.py:113` hook 누락 보강
  - `assign_room` 중복 호출 → `reconcile.py` 경유로 통일
  - grade 범위 백엔드 validation
- **v4** (2026-05-13): 코너 케이스 심층 검증 반영
  - **다박 stay 단위 1칩 가드** (`_has_existing_chip_in_stay`) — UI 칩 row 중복 방지
  - **`_find_schedule` 진입 가드** — PR 2 배포 직후 critical diag 폭주 차단
  - **grade PATCH API → reconcile hook** — Room/biz_item 등급 변경 후 stale 칩 방지
  - **`_resolve_product_base_capacity` prefix 제거** (PR 1)
  - **사전작업 체크리스트 §4 신설** — PR 1/2/3 각 단계별 사전·사후 확인 항목
  - **코너 케이스 시나리오 정합성 표 §6 신설**
  - rooms.py 보존 필드 주석 권장
