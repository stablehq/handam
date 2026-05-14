# 단계 #5 사전조사 — `on_dates_changed` 실제 구현

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §C
> 분류: ⚪ 동작 변화 없음 (caller 호출 0건, 호출 시점에 발동)
> 변경 규모: `app/services/reservation_lifecycle.py` 의 `on_dates_changed` 함수 본문 교체 (~10 라인)

---

## 1. 목적

단계 #2 의 `NotImplementedError` 스켈레톤을 실제 구현으로 교체. 본 함수가 호출되면:
1. `shift_daily_records(db, reservation, old_check_in, old_check_out)` — PartyCheckin / DailyInfo 평행이동
2. `reconcile_dates(db, reservation)` — 범위 밖 RA 삭제 + 누락 날짜 자동 INSERT
3. `reconcile_all_chips(db, reservation.id)` — 5종 칩 전부 재계산

본 단계 #5 시점에 caller 0건 — 동작 변화 0.

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| caller (`reservations.py`, `naver_sync`, `extend_stay`, `_do_reduce_extension`) 가 호출하도록 전환 | #10/#13/#16/#17 |
| 다른 lifecycle 함수 (`on_constraints_changed` 등) | #6~#9 |
| `db.flush()` — caller 책임 유지 (Q3 결정) | — |

---

## 2. 변경 대상 코드

### `app/services/reservation_lifecycle.py` 의 `on_dates_changed` 함수 본문

**Before** (단계 #2 결과):

```python
def on_dates_changed(
    db: "Session",
    reservation: "Reservation",
    old_check_in: str,
    old_check_out: str,
) -> None:
    """체크인/체크아웃 변경 직후 호출.

    실제 구현 (단계 #5):
      1) shift_daily_records(db, reservation, old_check_in, old_check_out)
      2) reconcile_dates(db, reservation)
      3) reconcile_all_chips(db, reservation.id)

    caller (단계 #10/#13/#16/#17): reservations.py PUT, naver_sync._update,
    extend_stay, _do_reduce_extension.
    """
    raise NotImplementedError(
        "on_dates_changed not implemented yet "
        "(see docs/plans/lifecycle-migration-plan.md step #5)."
    )
```

**After**:

```python
def on_dates_changed(
    db: "Session",
    reservation: "Reservation",
    old_check_in: str,
    old_check_out: str,
) -> None:
    """체크인/체크아웃 변경 직후 호출.

    호출 순서 (caller 책임이었던 후처리를 단일 함수로 통합):
      1) shift_daily_records — PartyCheckin / ReservationDailyInfo 평행이동
      2) reconcile_dates       — 범위 밖 RA 삭제 + 누락 날짜 INSERT + push-out
      3) reconcile_all_chips   — 5종 칩 전부 재계산 (sync_sms_tags + surcharge +
                                  party3 + room_upgrade_promise + _review)

    caller 가 reservation 의 새 check_in/out 값을 이미 적용한 상태에서 호출.
    old_check_in / old_check_out 은 shift_daily_records 가 평행이동 계산에 사용.

    caller (단계 #10/#13/#16/#17): reservations.py PUT, naver_sync._update,
    extend_stay, _do_reduce_extension.
    """
    from app.services.room_assignment import shift_daily_records, reconcile_dates
    from app.services.reconcile import reconcile_all_chips

    shift_daily_records(db, reservation, old_check_in, old_check_out)
    reconcile_dates(db, reservation)
    reconcile_all_chips(db, reservation.id)
```

**변경 내용**:
- `NotImplementedError` 본문 6 라인 제거
- docstring 갱신 — 호출 순서 명시
- 3 함수 lazy import 1 라인
- 3 함수 호출 3 라인
- 총 변경: -6 / +4 = **-2 라인** (함수 자체는 그대로)

### 2-1. lazy import 정당화

| import 대상 | 위치 | 사유 |
|---|---|---|
| `shift_daily_records` | `app/services/room_assignment.py:741` | 함수 내 import — 모듈 로딩 시점 순환 import 회피 (Mutator 와 동일 패턴) |
| `reconcile_dates` | `app/services/room_assignment.py:826` | 동일 |
| `reconcile_all_chips` | `app/services/reconcile.py:23` | 동일 |

→ 단계 #20 에서 `shift_daily_records` / `reconcile_dates` 가 private 화 될 때, 본 lifecycle 함수가 모듈 내부에서 직접 호출 → 외부 노출 면적 ↓.

### 2-2. 호출 순서 정당화

```
shift_daily_records  → reconcile_dates  → reconcile_all_chips
```

| 순서 | 이유 |
|---|---|
| 1. shift_daily_records 먼저 | PartyCheckin/DailyInfo 의 date 가 reservation 의 새 범위 안에 들어와야 reconcile_dates 가 RA 범위 결정 시 동일 데이터셋 기준 |
| 2. reconcile_dates 다음 | 범위 밖 RA 삭제 + 누락 날짜 INSERT — 칩 재계산이 정확한 RA 상태 위에서 작동하려면 먼저 RA 정리 필요 |
| 3. reconcile_all_chips 마지막 | 최종 RA 상태 + invariant 가 모두 정리된 후 5종 칩 일괄 재계산 |

이 순서는 `reservations.py PUT update_reservation` 의 기존 패턴 (L383~L405 의 shift → reconcile_dates 분기 + L443~L450 의 reconcile_all_chips 호출) 과 동일.

### 2-3. `db.flush()` 호출 여부

단계 #2 사전조사 §3 의 Q3 결정 — caller 책임 유지. 본 함수는 flush 안 함.

- caller (`reservations.py PUT`) 는 이미 setattr 후 db.flush() 또는 commit 으로 마무리
- `reconcile_dates` 내부의 `_compact_bed_orders_in_cells` 가 자체 flush 호출 — ORM 변경이 DB 에 반영됨
- 본 함수가 명시적 flush 호출하면 중복 — 안 함

---

## 3. 동작 동등성 근거

### 3-1. 호출 site 0건 — 동작 변화 0

본 단계 #5 머지 시점:
- `git diff main -- app/` 결과: `reservation_lifecycle.py` 의 `on_dates_changed` 본문 교체만
- caller 0건 — SQL 쿼리 결과 동일
- caller 미머지 상태이므로 운영 동작 동등성 완전 보장

### 3-2. 단위 테스트 가능 (선택, 권장)

```python
# tests/unit/test_lifecycle_on_dates_changed.py (선택)

def test_calls_three_functions_in_order(monkeypatch):
    """3 함수가 정해진 순서로 호출됨"""
    calls = []
    monkeypatch.setattr(
        "app.services.room_assignment.shift_daily_records",
        lambda db, r, oi, oo: calls.append(("shift", oi, oo)),
    )
    monkeypatch.setattr(
        "app.services.room_assignment.reconcile_dates",
        lambda db, r: calls.append(("reconcile_dates", r.id)),
    )
    monkeypatch.setattr(
        "app.services.reconcile.reconcile_all_chips",
        lambda db, rid: calls.append(("reconcile_all_chips", rid)),
    )

    res = make_fake_reservation(id=1, check_in_date="2026-05-15")
    on_dates_changed(None, res, "2026-05-10", "2026-05-11")

    assert calls == [
        ("shift", "2026-05-10", "2026-05-11"),
        ("reconcile_dates", 1),
        ("reconcile_all_chips", 1),
    ]

def test_imports_resolved():
    """lazy import 가 모듈 로딩 시점에 실패하지 않음"""
    from app.services.reservation_lifecycle import on_dates_changed
    # NotImplementedError 가 아니라 실제 실행 가능한 함수
    import inspect
    src = inspect.getsource(on_dates_changed)
    assert "NotImplementedError" not in src
```

### 3-3. 정적 분석

| 검증 항목 | 검증 방법 | 기대 결과 |
|---|---|---|
| 신규 함수 호출 site | `grep -rn "on_dates_changed(" app/ tests/` (신규 정의 + docstring 제외) | 0건 (caller 미머지) |
| import 가능 | `python -c "from app.services.reservation_lifecycle import on_dates_changed; on_dates_changed.__doc__"` | OK |
| NotImplementedError 사라짐 | `inspect.getsource` 에 `NotImplementedError` 미포함 | OK |

---

## 4. 영향받지 않음을 확인할 코드 경로

본 단계에서 단 1 byte도 변경되지 않음:

```
app/services/reservation_lifecycle.py 의 다른 4개 함수:
  - on_constraints_changed (단계 #6)      ← 스켈레톤 유지
  - on_status_cancelled (단계 #7)         ← 스켈레톤 유지
  - on_room_assigned (단계 #8)            ← 스켈레톤 유지
  - on_reservation_deleted (단계 #9)      ← 스켈레톤 유지

app/services/room_assignment.py 의 shift_daily_records, reconcile_dates  ← 변경 0 (호출만)
app/services/reconcile.py 의 reconcile_all_chips                          ← 변경 0 (호출만)

모든 caller (reservations.py, naver_sync.py, reservations_stay.py 등) — 변경 0
```

frontend: 변경 없음.

---

## 5. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/reservation_lifecycle.py` 에러 0
- [ ] **import 가능**: `from app.services.reservation_lifecycle import on_dates_changed`
- [ ] **`NotImplementedError` 사라짐**:
  ```python
  import inspect
  from app.services.reservation_lifecycle import on_dates_changed
  src = inspect.getsource(on_dates_changed)
  assert "NotImplementedError" not in src, "still skeleton"
  ```
- [ ] **다른 4 함수 스켈레톤 유지**: 4 함수 모두 `NotImplementedError` raise 확인 (단계 #2 검증 재실행)
- [ ] **외부 호출 0건**: `grep -rn "on_dates_changed(" app/ tests/ | grep -v reservation_lifecycle.py | grep -v __pycache__` → 0건
- [ ] **단위 테스트** (선택): 3 함수 호출 순서 mock 검증
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #4 시점과 동일

---

## 6. 본 단계 이후의 후속 의존성

본 단계 머지 후 진행 가능:
- **#6** (`on_constraints_changed` 구현) — 본 단계와 독립
- **#7~#9** (다른 lifecycle 함수 구현) — 본 단계와 독립
- **#10** (`reservations.py PUT` 날짜 분기 → `on_dates_changed` 호출) — 본 단계 의존

본 단계 단독으로는 의도된 동작 변화 0.

---

## 7. 미결 검토 항목

- [ ] 단위 테스트 추가 vs 단계 #10 이후 통합 테스트만 의존 — 선택. lifecycle 함수가 단순 위임 (3 함수 순차 호출) 이라 단위 테스트 가치 미약.
- [ ] `reservation.check_in_date` / `check_out_date` 가 None 인 케이스 — caller 측 가드. 본 함수는 그대로 위임 (shift_daily_records 와 reconcile_dates 가 자체 가드 보유).

---

## 8. 머지 후 다음 액션

`lifecycle-step-06-on-constraints-changed-impl.md` 작성 (단계 #6 사전조사).
