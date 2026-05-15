# Room Assignment 코드 정리 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: 사전조사 완료 — PR1 진입 가능
> 관련 계획: [sync-sms-tags-consolidation-plan.md](./sync-sms-tags-consolidation-plan.md) (이슈 #3 별도 추적)

---

## 배경

`room_assignment.py` / `room_assignment_invariants.py` / `room_auto_assign.py` 세 파일에서
코드 점검 중 발견된 5가지 문제. 기능 버그는 아니지만 테스트 파손·DEPRECATED 코드 실행·
모듈 경계 위반이 포함되어 정리가 필요하다.

---

## 원칙

1. **각 단계는 별도 PR** — 롤백 가능 단위
2. **Before/After 코드 명시** — 사전조사 문서에 라인 단위 인용
3. **기능 변화 0** — 이름 변경·dead code 제거·모듈 이동만
4. **테스트 함께 수정** — 파손된 테스트 import 포함

---

## 발견된 문제 5가지

### 이슈 #1 — `sync_denormalized_field` DEPRECATED 호출 잔존

**심각도**: 중간 (불필요한 쿼리 실행)

`room_assignment.py:777` 에 이미 deprecated 선언:
```python
def sync_denormalized_field(db, reservation):
    """DEPRECATED: Phase 3-1 이후 미사용. 호출 제거됨."""
```

그런데 `room_auto_assign.py:577` 에서 아직 호출 중:
```python
# reconcile_stale_chips 루프 내부
res = db.query(Reservation).filter(Reservation.id == rid).first()
if res:
    room_assignment.sync_denormalized_field(db, res)  # ← 이 줄
db.commit()
```

Phase 3-1 이후 `Reservation.room_number` / `room_password` 를 직접 조회하는 코드가 전부
`RoomAssignment` 직접 조회로 전환됐으므로 이 동기화 자체가 불필요하다.
`reconcile_stale_chips` 가 처리하는 예약 수만큼 쿼리가 낭비된다.

**수정**: `room_auto_assign.py:575~578` 블록에서 `sync_denormalized_field` 호출 2줄 삭제.

---

### 이슈 #2 — `_reconcile_dates` / `_shift_daily_records` 이름 컨벤션 불일치 + 테스트 파손

**심각도**: 높음 (테스트 ImportError 실제 파손)

`room_assignment.py` 에 두 함수가 `_`(private) 접두어로 정의됨:
```python
def _shift_daily_records(db, reservation, old_check_in, old_check_out): ...
def _reconcile_dates(db, reservation): ...
```

#### (a) `reservation_lifecycle.py` 에서 private 함수를 외부 import

```python
# reservation_lifecycle.py:45
from app.services.room_assignment import _shift_daily_records, _reconcile_dates
```

`_` 접두어는 "파일 내부용"이라는 Python 관례. 외부에서 import 하면 "건드려도 되는 내부 구현"으로
오해할 수 있다.

#### (b) 테스트 파일이 이미 public 이름으로 import → ImportError

```python
# test_reconcile_dates.py:4
from app.services.room_assignment import assign_room, reconcile_dates  # ← 언더스코어 없음

# test_reconcile_dates_extension.py:3
from app.services.room_assignment import assign_room, reconcile_dates  # ← 동일
```

`room_assignment.py` 에는 `reconcile_dates` (언더스코어 없는 버전) 가 존재하지 않는다.
이 두 테스트 파일을 실행하면 `ImportError: cannot import name 'reconcile_dates'` 가 발생한다.

**수정**:
- `_reconcile_dates` → `reconcile_dates` 이름 변경
- `_shift_daily_records` → `shift_daily_records` 이름 변경
- `reservation_lifecycle.py` import 문 수정
- 테스트 파일은 이미 underscore 없는 이름을 쓰므로 변경 불필요 (자동으로 해결됨)

---

### 이슈 #3 — `sync_sms_tags` 가치 없는 래퍼 레이어

**심각도**: 낮음 (기능 영향 없음, 구조 문제)

이 이슈는 **[sync-sms-tags-consolidation-plan.md](./sync-sms-tags-consolidation-plan.md)** 에서
별도로 추적 중. 본 계획 범위 외.

요약:
- `sync_sms_tags` (room_assignment.py) 는 `chip_reconciler.reconcile_chips_for_reservation` 를
  그대로 위임하는 2줄 껍데기
- `reconcile_all_chips` → `sync_sms_tags` → `chip_reconciler` 의 3단계 체인이
  `reconcile_all_chips` → `chip_reconciler` 2단계로 줄어들 수 있음
- Group A (배치 최적화 의도 3곳) 는 유지, Group B (6곳) 만 교체 예정

---

### 이슈 #4 — `reconcile_stale_chips` 가 room_auto_assign.py 에 위치

**심각도**: 낮음 (기능 영향 없음, 모듈 경계 위반)

`reconcile_stale_chips` 는 "이미 배정된 예약의 SMS 칩이 누락됐으면 복구"하는 칩 정합성 함수인데
`room_auto_assign.py` (방 자동배정 담당) 안에 있다.

이유: `daily_assign_rooms` (매일 스케줄러 진입점) 가 이걸 호출하기 때문에 같이 둔 것.

```python
# room_auto_assign.py
def daily_assign_rooms(db):
    auto_assign_rooms(db, today)      # 방 배정
    auto_assign_rooms(db, tomorrow)   # 방 배정
    reconcile_stale_chips(db, today)  # 칩 복구 ← 왜 여기?
```

`reconcile_stale_chips` 내부는 `chip_reconciler.reconcile_chips_for_reservation` 호출이 핵심이므로
`chip_reconciler.py` 또는 별도 `chip_repair.py` 가 논리적으로 맞는 위치다.

**수정 방향**: `reconcile_stale_chips` 를 `chip_reconciler.py` 로 이동.
`daily_assign_rooms` 에서는 `from app.services.chip_reconciler import reconcile_stale_chips` 로 import.

**단, 이 이슈는 낮은 우선순위** — 기능 동작에 영향 없음. #1·#2 완료 후 진행.

---

### 이슈 #5 — `clear_all_for_reservation` 의 surcharge 칩 미정리

**심각도**: 중간 (잠재적 stale 칩 누적)

`unassign_room` 과 `unassign_dates` 는 방 해제 시 surcharge / room_upgrade 칩을 정리한다:

```python
# unassign_room (L646~656)
for d in cleanup_dates:
    _delete_all_surcharge_chips(db, reservation_id, d)
    _delete_all_room_upgrade_promise_chips(db, reservation_id, d)
    _delete_all_room_upgrade_review_chips(db, reservation_id, d)

# unassign_dates (L714~724) — 동일 패턴
```

그런데 `clear_all_for_reservation` 에는 이 정리가 없다:

```python
# clear_all_for_reservation (L736~774)
count = db.query(RoomAssignment).filter(...).delete(...)
if reservation:
    reservation.room_number = None
    reservation.room_password = None
# ← surcharge / room_upgrade 칩 정리 없음
```

`clear_all_for_reservation` 의 호출처:
- `reservation_lifecycle.py:176` — 예약 status 변경 시 (취소)
- `reservation_lifecycle.py:245` — 예약 삭제 시

예약 취소·삭제 시 `reservation_lifecycle.py` 가 chip_store 의 `delete_chips_for_reservation` 를
별도 호출하는지 **먼저 확인이 필요**하다. lifecycle 에서 이미 처리한다면 중복이라 문제없고,
처리 안 한다면 surcharge / upgrade 칩이 orphan 으로 남는다.

**수정 방향**: `reservation_lifecycle.py` 의 취소/삭제 경로를 확인 후 결정.
- lifecycle 에서 이미 처리: no-op
- lifecycle 에서 미처리: `clear_all_for_reservation` 에 surcharge 칩 정리 추가

---

## 단계 분해 (PR 순서)

우선순위 · 리스크 · 의존성 기준:

| # | PR | 변경 파일 | 규모 | 우선순위 |
|---|---|---|---|---|
| 1 | `sync_denormalized_field` 호출 제거 | `room_auto_assign.py` | 2줄 삭제 | 높음 |
| 2 | `_reconcile_dates` / `_shift_daily_records` 공개화 | `room_assignment.py`, `reservation_lifecycle.py` | 이름 변경 | 높음 (테스트 파손) |
| 3 | `clear_all_for_reservation` 칩 누락 조사 → 수정 | `reservation_lifecycle.py` 확인 후 결정 | TBD | 중간 |
| 4 | `reconcile_stale_chips` 모듈 이동 | `room_auto_assign.py` → `chip_reconciler.py` | 중간 | 낮음 |

이슈 #3 (`sync_sms_tags`) 는 `sync-sms-tags-consolidation-plan.md` 에서 별도 진행.

---

## 진행 상태

- [ ] PR1: `sync_denormalized_field` 호출 제거
- [ ] PR2: `_reconcile_dates` / `_shift_daily_records` 이름 공개화 + 테스트 수정
- [ ] PR3: `clear_all_for_reservation` 칩 누락 조사 및 수정
- [ ] PR4: `reconcile_stale_chips` 모듈 이동 (낮은 우선순위)
