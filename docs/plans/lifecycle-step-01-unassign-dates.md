# 단계 #1 사전조사 — `unassign_dates` 함수 신규 추가

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §A
> 분류: ⚪ 동작 변화 없음 (인프라)
> 변경 규모: `app/services/room_assignment.py` ~30 라인 추가, 기존 파일 0 수정
> caller 호출 0 건 (단계 #3 / #4 에서 사용)

---

## 1. 목적

`services/room_assignment.py` 에 `unassign_dates(reservation_id, dates: list[str])` 함수 신규 추가. 비연속 날짜 list 의 RoomAssignment 를 안전하게 삭제 + bed_order 재정렬 + 칩 cleanup 까지 보장.

본 단계 시점에서는 어디서도 호출되지 않음. 단계 #3 (`_do_reduce_extension`) 과 #4 (`naver_sync` cc1) 에서 호출 시작.

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| `reservations_stay.py:378 db.delete(ra)` → 본 함수 호출로 교체 | #3 |
| `naver_sync.py:795~807 db.query(RA).delete()` → 본 함수 호출로 교체 | #4 |
| lifecycle 함수 5종 | #5~#9 |
| caller 전환 | #10~#19 |

---

## 2. 변경 대상 코드

**기존 파일 변경**: 없음.
**신규 함수**: `app/services/room_assignment.py` 에 추가 (`unassign_room` 함수 직후 적합 위치).

### 2-1. 함수 시그니처 + 본문

```python
def unassign_dates(db: Session, reservation_id: int, dates: list[str]) -> int:
    """특정 날짜 목록의 RoomAssignment 삭제 + bed_order 재정렬 + 칩 cleanup.

    `unassign_room` (range 기반) 과 달리 비연속 날짜 list 를 받음.
    사용처:
      - `_do_reduce_extension` 의 dates_to_remove (단계 #3 에서 위임)
      - `naver_sync` cc1 의 affected_dates (단계 #4 에서 위임)

    내부 동작은 unassign_room 의 핵심 (query → delete → compact + 칩 cleanup) 과
    동일. 단 date range 가 아닌 임의 dates list 를 받음.
    """
    if not dates:
        return 0

    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        return 0

    diag(
        "unassign_dates.enter",
        level="verbose",
        res_id=reservation_id,
        dates_count=len(dates),
    )

    tid = get_session_tenant_id(db)
    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.tenant_id == tid,
        RoomAssignment.date.in_(dates),
    )
    old_assignments = query.all()
    affected_cells = {(ra.room_id, ra.date) for ra in old_assignments if ra.room_id}

    count = query.delete(synchronize_session="fetch")
    if affected_cells:
        db.flush()
        compacted = _compact_bed_orders_in_cells(db, affected_cells)
        if compacted:
            diag(
                "unassign_dates.compact",
                level="verbose",
                res_id=reservation_id,
                cells_count=len(affected_cells),
                changed=compacted,
            )

    # Surcharge / room_upgrade_promise / room_upgrade_review 칩 정리 — unassign_room 과 동일 패턴
    try:
        from app.services.surcharge import _delete_all_surcharge_chips
        from app.services.room_upgrade_review import _delete_all_room_upgrade_review_chips
        from app.services.room_upgrade_promise import _delete_all_room_upgrade_promise_chips
        for d in dates:
            _delete_all_surcharge_chips(db, reservation_id, d)
            _delete_all_room_upgrade_promise_chips(db, reservation_id, d)
            _delete_all_room_upgrade_review_chips(db, reservation_id, d)
    except Exception as e:
        logger.warning(f"Surcharge/room_upgrade cleanup failed for res={reservation_id}: {e}")

    diag(
        "unassign_dates.exit",
        level="verbose",
        res_id=reservation_id,
        deleted=count,
    )

    return count
```

**라인 단위 정당화 — 각 줄이 왜 필요한가**:

| 라인 | 책임 | unassign_room 대응 |
|---|---|---|
| `if not dates: return 0` | 빈 list 가드 — 의미상 no-op | unassign_room 은 range 가드, 본 함수는 list 가드 |
| `reservation = db.query(...).first()` | 존재 검증 | unassign_room L582 동일 |
| `if not reservation: return 0` | 없으면 no-op | unassign_room L583~L584 동일 |
| `diag("unassign_dates.enter")` | 진입 로깅 (verbose) | unassign_room L587~L592 동일 패턴 |
| `tid = get_session_tenant_id(db)` | 멀티테넌트 격리 — RoomAssignment 도 TenantMixin | unassign_room L622 동일 |
| `query = db.query(RoomAssignment).filter(...)` | 삭제 대상 정의 | unassign_room L624~L627 와 동등 — date 범위가 list `in_(dates)` 로 바뀜 |
| `old_assignments = query.all()` | bed_order 재정렬에 사용할 cells 캡처 | unassign_room L631 동일 |
| `affected_cells = {(ra.room_id, ra.date) ... }` | 도미토리 셀 집합 | unassign_room L631 동일 |
| `count = query.delete(synchronize_session="fetch")` | 실제 삭제 | unassign_room L632 동일 |
| `if affected_cells: db.flush(); _compact_bed_orders_in_cells` | bed_order 갭 재정렬 — 도미토리 방의 침대 순서 보정 | unassign_room L633~L642 동일 |
| `for d in dates: _delete_all_*` | surcharge / room_upgrade 칩 cleanup | unassign_room L654~L663 동일 패턴 (cleanup_dates 만 list 로 바뀜) |
| `diag("unassign_dates.exit")` | 종료 로깅 | unassign_room L666~L671 동일 |
| `return count` | 삭제 개수 반환 | unassign_room L673 동일 |

→ unassign_room 의 핵심 패턴을 dates list 기반으로 재구성. 차이점은:
- `_date_range(from_date, end_date)` 호출 X → `dates` 직접 사용
- `cleanup_dates = dates if from_date else _date_range(...)` → 항상 `dates`
- log_activity 호출 **제외** (단계 #3/#4 의 caller 가 이미 자체 diag/로깅 함, 중복 방지)

### 2-2. log_activity 호출을 제외한 이유

`unassign_room` 은 L585~L621 에서 `log_activity(type="room_move", title="...객실해제...")` 호출. 본 `unassign_dates` 는 이 호출을 **포함하지 않음**.

근거:
- 단계 #3 의 `_do_reduce_extension` 은 자체 diag `reduce_extension.invoked` 로깅 함
- 단계 #4 의 `naver_sync` cc1 은 자체 diag `naver_sync.same_day_cancel` 로깅 함
- 두 caller 가 이미 의미적 로깅 보유 — `unassign_dates` 가 추가로 `room_move` 로그 남기면 중복

→ 본 단계의 의도된 차이: caller 가 이미 로깅하니까 `unassign_dates` 는 verbose 진입/종료 diag 만.

---

## 3. 동작 동등성 근거

### 3-1. 호출 site 0건이라 동작 변화 0

본 단계 #1 머지 시점:
- `git diff main -- app/` 결과: `room_assignment.py` 의 신규 함수 추가만
- caller 0건 → SELECT/INSERT/DELETE 결과 동일

### 3-2. 함수 단독 테스트 — 단계 #3/#4 이전에 검증

caller 가 없는 상태에서도 단위 테스트 작성 가능 (Mutator 단계 #11 과 동일 패턴):

```python
# tests/unit/test_unassign_dates.py (선택, 권장)

def test_empty_dates_returns_zero():
    """빈 list 가드 — no-op"""
    count = unassign_dates(db, reservation_id=1, dates=[])
    assert count == 0

def test_missing_reservation_returns_zero():
    """존재하지 않는 예약 — no-op"""
    count = unassign_dates(db, reservation_id=999999, dates=["2026-05-15"])
    assert count == 0

def test_deletes_matching_dates_only():
    """dates list 의 날짜만 삭제, 다른 날짜는 보존"""
    # setup: 5/15, 5/16, 5/17 배정
    # call: unassign_dates(res_id, ["5/15", "5/17"])
    # expect: 5/16 만 남음, count=2

def test_compacts_bed_orders_after_delete():
    """도미토리 셀의 bed_order 갭 재정렬"""
    # setup: 같은 (room_id, date) 셀에 3명 (bed_order 1, 2, 3) 배정
    # call: unassign_dates 로 bed_order 2 삭제
    # expect: 남은 2명의 bed_order 가 1, 2 로 재정렬

def test_chip_cleanup_called_per_date():
    """surcharge / room_upgrade 칩 cleanup 호출 검증 (mock)"""
    with mock.patch("app.services.surcharge._delete_all_surcharge_chips") as m:
        unassign_dates(db, res_id, ["5/15", "5/16"])
        assert m.call_count == 2  # 날짜별 1회씩
```

본 단계는 caller 0건이라 단위 테스트만 검증. 통합 테스트는 단계 #3/#4 의 caller 가 호출하기 시작할 때.

### 3-3. 정적 분석

| 검증 항목 | 검증 방법 | 기대 결과 |
|---|---|---|
| 신규 함수 외부 호출 site | `grep -rn "unassign_dates" app/ tests/` (본 신규 정의 제외) | 0건 |
| 다른 caller 의 변화 | `git diff main -- app/` 가 room_assignment.py 외 0건 | 0건 |
| import 가능 | `python -c "from app.services.room_assignment import unassign_dates"` | OK |

### 3-4. unassign_room 과의 의미적 등가성

같은 dates list 를 unassign_room 의 range (`from_date`, `end_date`) 변환으로 처리하면 어떻게 될까?

| 케이스 | unassign_dates(dates=["5/15","5/17"]) | unassign_room(from_date="5/15", end_date="5/18") |
|---|---|---|
| 5/15 삭제 | ✅ | ✅ |
| 5/16 삭제 | ✅ 안 함 (list 에 없음) | 🔴 삭제됨 (range 안에 있음) |
| 5/17 삭제 | ✅ | ✅ |

→ **range 기반은 비연속 날짜 처리 못함**. `unassign_dates` 가 새로 필요한 이유.

---

## 4. 영향받지 않음을 확인할 코드 경로

본 단계에서 단 1 byte도 변경되지 않음:

```
app/services/room_assignment.py 의 기존 함수 모두:
  - assign_room (L213)
  - unassign_room (L569)        ← 본 단계와 무관, 그대로
  - clear_all_for_reservation (L668)
  - sync_denormalized_field (L709)  (DEPRECATED 표시)
  - shift_daily_records (L741)
  - reconcile_dates (L826)
  - sync_sms_tags (L198)
  - _compact_bed_orders_in_cells (L76)  ← 본 함수가 호출만, 정의 변경 0
  - _compute_bed_order (L135)
  - _resolve_prefixed_password (L23)

다른 caller 모두:
  - app/api/                                (모든 라우터)
  - app/services/naver_sync.py
  - app/services/room_auto_assign.py
  - app/services/chip_reconciler.py
  - app/services/reconcile.py
  - app/scheduler/

frontend 측: 변경 없음.
```

---

## 5. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/room_assignment.py` 에러 0
- [ ] **import 가능**: `python -c "from app.services.room_assignment import unassign_dates; print(unassign_dates.__doc__)"`
- [ ] **외부 호출 0건**: `grep -rn "unassign_dates" app/ tests/ | grep -v "room_assignment.py" | grep -v __pycache__` → 0건
- [ ] **기존 함수 변경 0**: `git diff app/services/room_assignment.py` 결과가 함수 추가만 (다른 라인 변화 0)
- [ ] **caller 변화 0**: `git diff main -- app/` 가 room_assignment.py 외 0 라인
- [ ] **기존 pytest 회귀**: pass/fail 개수 본 단계 전과 동일

---

## 6. 본 단계 이후의 후속 의존성

본 단계 머지 후 진행 가능:
- **#2** (lifecycle 스켈레톤) — 본 단계와 독립, 같은 인프라
- **#3** (`reservations_stay.py:378 db.delete(ra)` → `unassign_dates` 위임)
- **#4** (`naver_sync.py:795~807` 직접 RA delete → `unassign_dates` 위임)

본 단계 단독으로는 의도된 동작 변화 0. silent 버그 (bed_order 누락) 해결은 단계 #3/#4 시점.

---

## 7. 미결 검토 항목

- [ ] log_activity 호출을 본 함수에 포함시킬지 vs caller 책임으로 둘지 — §2-2 의 결정 (caller 책임 유지) 이 단계 #3/#4 사전조사에서 재검토 필요. 만약 caller 측 로깅이 부족하다고 판단되면 본 함수에 흡수.
- [ ] dates list 의 정렬 / 중복 처리 — 본 함수는 caller 가 정제한 list 를 받는다고 가정. 중복 dates 가 들어와도 `query.delete()` 가 idempotent 라 안전.

---

## 8. 머지 후 다음 액션

본 단계 PR 머지 → `lifecycle-step-02-lifecycle-skeleton.md` 작성.
