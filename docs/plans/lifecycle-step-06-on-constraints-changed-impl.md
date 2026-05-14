# 단계 #6 사전조사 — `on_constraints_changed` 실제 구현

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §C
> 분류: ⚪ 동작 변화 없음 (caller 호출 0건)
> 변경 규모: `reservation_lifecycle.py` 의 `on_constraints_changed` 함수 본문 교체 (~35 라인)
> **signature 변경**: 단계 #2 의 `(db, reservation, changed_fields)` → `(db, reservation, changed_fields, *, actor)` (keyword-only `actor` 추가)

---

## 1. 목적

성별/인원/section 등 invariant 영향 필드 변경 후의 후처리 통합:
1. `check_assignment_validity(db, reservation)` → invalid_dates
2. future_invalid 가 있으면 `unassign_room` 호출 + `log_activity` + `diag`
3. `reconcile_all_chips(db, reservation.id)`

기존 `reservations.py PUT update_reservation` (L399~L430) + `naver_sync._update_reservation` (L859~L897) 의 두 invariant check 분기가 거의 동일한 패턴 — 함수 1개로 통합.

---

## 2. Signature 변경 — 왜 `actor` 추가하나

단계 #2 의 스켈레톤: `on_constraints_changed(db, reservation, changed_fields)`.

본 단계의 발견: 두 caller 가 `log_activity` 호출 시 `created_by` 인자를 다르게 전달:
- `reservations.py`: `created_by=current_user.username`
- `naver_sync`: `created_by="naver_sync"`

lifecycle 함수가 운영 로그에 actor 표기를 유지하려면 caller 마다 다른 값을 받아야 함. keyword-only `actor: str` 인자 추가.

| 옵션 | 평가 |
|---|---|
| A. `actor` 인자 추가 | 운영 로그 정확성 유지, signature 변경 1회 (본 단계) | ✅ |
| B. 시그니처 유지, `created_by="system"` 고정 | 단순하지만 운영 추적 ↓ — `naver_sync` 와 `current_user` 구분 사라짐 |
| C. log_activity 는 caller 에 남김 (lifecycle 은 invariant + reconcile 만) | lifecycle 의 책임이 좁아짐, 두 caller 가 동일 log_activity 코드 중복 |

**A 선택**. caller 가 자기 actor 전달.

---

## 3. 변경 대상 코드

### `app/services/reservation_lifecycle.py` 의 `on_constraints_changed` 함수 본문

**Before** (단계 #2 결과):

```python
def on_constraints_changed(
    db: "Session",
    reservation: "Reservation",
    changed_fields: set[str],
) -> None:
    """성별/인원/section 등 invariant 영향 필드 변경 직후 호출.

    실제 구현 (단계 #6):
      1) check_assignment_validity(db, reservation) → invalid_dates
      2) future_invalid 이 있으면 unassign_room 호출 + 로깅
      3) reconcile_all_chips(db, reservation.id)

    caller (단계 #11/#14): reservations.py PUT, naver_sync._update.
    """
    raise NotImplementedError(
        "on_constraints_changed not implemented yet "
        "(see docs/plans/lifecycle-migration-plan.md step #6)."
    )
```

**After**:

```python
def on_constraints_changed(
    db: "Session",
    reservation: "Reservation",
    changed_fields: set[str],
    *,
    actor: str,
) -> None:
    """성별/인원/section 등 invariant 영향 필드 변경 직후 호출.

    호출 순서:
      1) check_assignment_validity — RA 가 새 인원/성별 invariant 만족하는지 검사
      2) (위반 시) unassign_room — 위반 future 날짜의 RA 해제 + log_activity + critical diag
      3) reconcile_all_chips — 5종 칩 전부 재계산

    caller (단계 #11/#14): reservations.py PUT, naver_sync._update.

    Args:
        actor: log_activity 의 created_by 값. caller 가 자기 식별자 전달
               (예: current_user.username 또는 "naver_sync").
    """
    import logging
    from datetime import datetime, timedelta
    from app.config import KST
    from app.services.room_assignment_invariants import check_assignment_validity
    from app.services.room_assignment import unassign_room
    from app.services.reconcile import reconcile_all_chips
    from app.services.activity_logger import log_activity
    from app.diag_logger import diag

    logger = logging.getLogger(__name__)

    try:
        invalid_dates = check_assignment_validity(db, reservation)
    except Exception as e:
        logger.warning(f"check_assignment_validity failed: {e}")
        invalid_dates = []

    if invalid_dates:
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        future_invalid = sorted([d for d in invalid_dates if d > today_str])
        if future_invalid:
            end_d = (
                datetime.strptime(future_invalid[-1], "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            unassign_room(
                db, reservation.id,
                from_date=future_invalid[0],
                end_date=end_d,
            )
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 제약 위반 배정 해제 ({len(future_invalid)}일)",
                detail={
                    "reservation_id": reservation.id,
                    "invalid_dates": future_invalid,
                    "trigger": "constraint_field_change",
                    "changed_fields": sorted(changed_fields),
                },
                created_by=actor,
            )
            diag(
                "invariant.violation_detected",
                level="critical",
                reservation_id=reservation.id,
                invalid_dates=future_invalid,
            )

    reconcile_all_chips(db, reservation.id)
```

**변경 내용**:
- `NotImplementedError` 본문 6 라인 제거
- 신규 본문 ~45 라인
- signature 변경: `*, actor: str` keyword-only 인자 추가

### 3-1. 기존 caller 코드와의 1:1 매핑

| Before (reservations.py L399~L432) | After (on_constraints_changed 내부) |
|---|---|
| `try: invalid_dates = check_assignment_validity(...)` | 동일 |
| `except Exception as e: logger.warning(...)` | 동일 |
| `if invalid_dates: today_str = datetime.now(KST).strftime(...)` | 동일 |
| `future_invalid = sorted([d for d in invalid_dates if d > today_str])` | 동일 |
| `if future_invalid: end_d = ...; unassign_room(...)` | 동일 |
| `log_activity(db, type="room_move", title=..., detail={..., "changed_fields": list(_CONSTRAINT_FIELDS & set(update_data.keys()))}, created_by=current_user.username)` | 동일 — `changed_fields` 가 caller 의 `_CONSTRAINT_FIELDS & set(update_data.keys())` 대신 lifecycle 인자 `changed_fields` (caller 가 미리 계산해 전달) |
| `diag("invariant.violation_detected", ...)` | 동일 |
| (`if chip_affecting: db.flush(); reconcile_all_chips`) — caller 의 별도 분기 | `reconcile_all_chips(db, reservation.id)` — lifecycle 안에서 항상 호출 |

### 3-2. `reconcile_all_chips` 의 항상 호출에 대한 정당화

기존 `reservations.py PUT` 의 흐름:
```python
if constraint_changed:
    # invariant check + unassign
if chip_affecting:  # sms_fields | constraint | surcharge_fields
    db.flush()
    reconcile_all_chips(...)
```

→ `chip_affecting` 가드는 sms_fields_changed OR constraint_changed OR surcharge_fields 변경. 즉 constraint_changed=True 면 어차피 `chip_affecting=True` → reconcile_all_chips 호출.

lifecycle `on_constraints_changed` 안에서 항상 `reconcile_all_chips` 호출은 동등.

단계 #11 (caller 전환) 시:
- caller 의 `if chip_affecting: db.flush(); reconcile_all_chips` 블록 분석:
  - constraint_changed 만 — `on_constraints_changed` 가 이미 호출
  - sms_fields_changed 만 — lifecycle 에 미흡수, caller 가 별도 호출 유지 (또는 다른 lifecycle 함수에 통합)
- → 단계 #11 사전조사에서 상세 분기 정리. 본 단계 #6 은 함수 정의만.

### 3-3. `db.flush()` 호출 — caller 책임 유지

부모 계획 Q3 결정 (caller 책임 유지) 에 따라 본 함수는 명시적 flush 안 함.
- `unassign_room` 내부는 `_compact_bed_orders_in_cells` 호출 시 자체 flush
- `reconcile_all_chips` 도 내부 flush 가능
- caller 는 commit/flush 자체 관리

---

## 4. 동작 동등성 근거

### 4-1. 호출 site 0건 — 동작 변화 0

본 단계 #6 머지 시점:
- caller 0건 — SQL 결과 동일
- `git diff main -- app/` 가 `reservation_lifecycle.py` 외 0 라인

### 4-2. 단계 #2 의 signature 와의 호환성

| 호환성 측면 | 분석 |
|---|---|
| 본 단계 머지 후 외부 호출 0건 | caller 미머지 — signature 변경 영향 0 |
| 단계 #11/#14 caller 전환 시 | 새 signature 따라 `actor=` 전달 (사전조사 단계에서 명시) |
| 향후 다른 caller 가 추가될 때 | `actor` keyword-only — 누락 시 TypeError 즉시 발생 (silent skip 차단) |

### 4-3. 단위 테스트 (선택)

```python
def test_invalid_dates_triggers_unassign_and_log(monkeypatch):
    """invariant 위반 시 unassign + log_activity + diag 호출"""
    calls = []
    monkeypatch.setattr("...check_assignment_validity", lambda db, r: ["2026-05-20"])
    monkeypatch.setattr("...unassign_room", lambda **kw: calls.append(("unassign", kw)))
    monkeypatch.setattr("...log_activity", lambda **kw: calls.append(("log", kw["created_by"])))
    monkeypatch.setattr("...reconcile_all_chips", lambda db, rid: calls.append(("chips", rid)))
    monkeypatch.setattr("...diag", lambda *a, **kw: calls.append(("diag", a[0])))

    res = make_fake_reservation(id=1, customer_name="X")
    on_constraints_changed(None, res, {"male_count"}, actor="user1")

    # unassign + log("user1") + diag + chips 호출
    assert ("unassign", ...) in calls
    assert ("log", "user1") in calls
    assert ("chips", 1) in calls
```

---

## 5. 영향받지 않음을 확인할 코드 경로

```
app/services/reservation_lifecycle.py 의 다른 4개 함수:
  - on_dates_changed (단계 #5)             ← 실제 구현 유지
  - on_status_cancelled (단계 #7)          ← 스켈레톤 유지
  - on_room_assigned (단계 #8)             ← 스켈레톤 유지
  - on_reservation_deleted (단계 #9)       ← 스켈레톤 유지

app/services/room_assignment_invariants.py 의 check_assignment_validity  ← 변경 0
app/services/room_assignment.py 의 unassign_room                          ← 변경 0
app/services/reconcile.py 의 reconcile_all_chips                          ← 변경 0
app/services/activity_logger.py 의 log_activity                           ← 변경 0
app/diag_logger.py 의 diag                                                ← 변경 0

모든 caller (reservations.py PUT, naver_sync._update) — 변경 0
```

frontend: 변경 없음.

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/reservation_lifecycle.py` 에러 0
- [ ] **import 가능**: signature 가 새 `actor` 인자 포함
  ```python
  import inspect
  from app.services.reservation_lifecycle import on_constraints_changed
  sig = inspect.signature(on_constraints_changed)
  assert "actor" in sig.parameters
  assert sig.parameters["actor"].kind == inspect.Parameter.KEYWORD_ONLY
  ```
- [ ] **NotImplementedError 사라짐**: `on_constraints_changed` 의 src 에 `NotImplementedError` 미포함
- [ ] **다른 3 함수 스켈레톤 유지** (#7~#9): NotImplementedError raise 검증
- [ ] **caller 호출 0건**: `grep -rn "on_constraints_changed(" app/ tests/` 에서 정의 파일 외 0건
- [ ] **`actor` 누락 시 TypeError**: positional 만 호출 시 즉시 실패
  ```python
  try:
      on_constraints_changed(None, None, {"male_count"})  # actor 누락
      assert False
  except TypeError:
      pass
  ```
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #5 시점과 동일

---

## 7. 본 단계 이후의 후속 의존성

- **#7~#9** (다른 lifecycle 함수 구현) — 본 단계와 독립
- **#11/#14** (caller 전환) — 본 단계의 새 signature `actor=` 사용

본 단계 단독으로는 의도된 동작 변화 0.

---

## 8. 미결 검토 항목

- [ ] `actor` 의 default 값 — 본 단계는 keyword-only required. silent skip 차단 우선. 향후 default 필요 시 별도 PR.
- [ ] `reconcile_all_chips` 의 항상 호출 — caller 의 `chip_affecting` 가드 의미가 사라짐 (constraint_changed=True 면 자동). 단계 #11 사전조사에서 caller 의 가드 코드 정리 검토.

---

## 9. 머지 후 다음 액션

`lifecycle-step-07-on-status-cancelled-impl.md` 작성 (단계 #7).
