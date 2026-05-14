# 단계 #2 사전조사 — `reservation_lifecycle.py` 스켈레톤 생성

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §A
> 분류: ⚪ 동작 변화 없음 (인프라)
> 변경 규모: 신규 파일 1개 (~70 lines), 기존 파일 0 수정
> caller 호출 0건 (단계 #10~#19 에서 사용)

---

## 1. 목적

`backend/app/services/reservation_lifecycle.py` 를 신규 생성. 5개 lifecycle 함수의 시그니처만 노출하고 본문은 `NotImplementedError`. 본 단계 시점에서는 caller 0건.

후속 단계 (#5~#9) 에서 실제 구현, (#10~#19) 에서 caller 가 호출 시작.

### Mutator 단계 #1 과의 패턴 동등성

Mutator 마이그레이션 단계 #1 (`reservation_mutator.py` 스켈레톤) 과 동일 패턴:
- `NotImplementedError` raise — caller 가 실수로 호출 시 즉시 실패 (silent skip 차단)
- TYPE_CHECKING 기반 type hints — 순환 import 회피
- 시그니처는 후속 PR 의 이름 충돌 / drift 사전 방지

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| 함수 본문 실제 구현 | #5~#9 |
| caller 가 호출하도록 전환 | #10~#19 |
| `_run_post_processing` 또는 통합 후처리 | (없음 — 함수별로 직접 처리) |

---

## 2. 변경 대상 코드

**기존 파일 변경**: 없음.
**신규 파일**: `backend/app/services/reservation_lifecycle.py`

### 2-1. 파일 헤더 + import

```python
"""ReservationLifecycle — 예약 라이프사이클 이벤트별 후처리 게이트웨이 (스켈레톤).

본 모듈은 단계 #2 시점에서는 어디서도 호출되지 않는다. 5개 lifecycle 이벤트
함수의 시그니처만 노출하여 후속 PR (#5~#9 구현, #10~#19 caller 전환) 의
이름 충돌 / signature drift 를 사전 방지한다.

각 함수는 "Reservation 의 라이프사이클 이벤트가 발생했을 때 따라와야 할 후처리
(shift_daily_records, reconcile_dates, reconcile_all_chips, invariant check 등)
를 일관된 순서로 호출" 한다는 책임을 가진다.

참고: docs/plans/room-assignment-pipeline-design.md
      docs/plans/lifecycle-migration-plan.md
      docs/plans/lifecycle-step-02-lifecycle-skeleton.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.db.models import Reservation
```

**각 라인 향후 사용처**:
- docstring: 참조 문서로 유지
- `from __future__ import annotations`: 타입 힌트를 문자열로 평가 → 순환 import 방지
- `TYPE_CHECKING` 분기: Session / Reservation 타입 힌트만 런타임 import 회피

### 2-2. 5개 lifecycle 함수 스켈레톤

각 함수의 시그니처 + 책임 docstring + `NotImplementedError`.

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


def on_status_cancelled(
    db: "Session",
    reservation: "Reservation",
    *,
    same_day: bool,
) -> None:
    """status=CANCELLED 변경 직후 호출. cc1 (당일) / cc2 (사전) 분기 흡수.

    실제 구현 (단계 #7):
      - same_day=True: unassign_dates(future_dates) + 칩 정리
      - same_day=False: clear_all_for_reservation + 칩 정리

    caller (단계 #15): naver_sync cc1/cc2 분기.
    """
    raise NotImplementedError(
        "on_status_cancelled not implemented yet "
        "(see docs/plans/lifecycle-migration-plan.md step #7)."
    )


def on_room_assigned(
    db: "Session",
    reservation: "Reservation",
    pushed_out: Optional[list[dict]] = None,
) -> None:
    """assign_room 직후 호출. push-out 된 예약의 칩까지 재계산.

    실제 구현 (단계 #8):
      1) reconcile_all_chips(db, reservation.id)
      2) for p in pushed_out: reconcile_all_chips(db, p["reservation_id"])

    caller (단계 #16/#18/#19): extend_stay, reservations_room.py assign PUT,
    room_auto_assign.
    """
    raise NotImplementedError(
        "on_room_assigned not implemented yet "
        "(see docs/plans/lifecycle-migration-plan.md step #8)."
    )


def on_reservation_deleted(
    db: "Session",
    reservation_id: int,
) -> None:
    """예약 삭제 (DELETE /reservations/{id}) 직후 호출.

    실제 구현 (단계 #9):
      1) clear_all_for_reservation(db, reservation_id)
      2) ReservationSmsAssignment 등 부속 레코드 정리

    caller (단계 #12): reservations.py:459 delete_reservation.
    """
    raise NotImplementedError(
        "on_reservation_deleted not implemented yet "
        "(see docs/plans/lifecycle-migration-plan.md step #9)."
    )
```

**각 함수의 시그니처 정당화**:

| 함수 | 첫 인자 | 핵심 인자 | 정당화 |
|---|---|---|---|
| `on_dates_changed` | `db, reservation` | `old_check_in, old_check_out` | `shift_daily_records` 가 old 값 필요 (`reservation` 은 이미 new 값) |
| `on_constraints_changed` | `db, reservation` | `changed_fields` | invariant check 가 어떤 필드가 바뀌었나 알아야 함 (로깅 detail 에 사용) |
| `on_status_cancelled` | `db, reservation, *, same_day` | `same_day` (keyword-only) | cc1/cc2 분기. keyword-only 로 명확화 |
| `on_room_assigned` | `db, reservation, pushed_out=None` | `pushed_out` (optional) | assign_room 의 반환값 그대로 받음. push-out 없는 케이스 (자동 배정 직후) 대응 |
| `on_reservation_deleted` | `db, reservation_id` | — | 이미 DB 에서 객체 삭제 직전이라 reservation 객체 대신 id |

---

## 3. 동작 동등성 근거

### 3-1. 정적 분석 기반 동등성

본 단계의 변경: **신규 파일 1개 추가, 어디서도 import/호출 안 함**.

| 검증 항목 | 검증 방법 | 기대 결과 |
|---|---|---|
| 다른 파일이 import 하는지 | `grep -rn "from app.services.reservation_lifecycle\|import reservation_lifecycle" app/ tests/` | 0건 |
| 5개 함수 식별자 참조 | `grep -rn "on_dates_changed\|on_constraints_changed\|on_status_cancelled\|on_room_assigned\|on_reservation_deleted" app/ tests/` (신규 파일 제외) | 0건 |
| 기존 caller 동작 변화 | `git diff main -- app/` 가 lifecycle.py 외 0 라인 | 0 |

### 3-2. 런타임 동등성

- 신규 파일이 lazy-import 될 가능성: SQLAlchemy `Base.registry` 자동 등록 — 본 파일은 `Base` 상속 클래스 정의 없음 → 자동 등록 대상 아님 ✅
- FastAPI router include: 본 파일은 router 정의 0개 ✅
- 본 파일이 import 안 되면 5개 함수가 메모리에 적재되지 않음 → 모든 SQL 쿼리 동일

### 3-3. 케이스별 비교

| 입력 / 시나리오 | 단계 #1 (이전) 결과 | 단계 #2 (본 단계) 결과 | 판정 |
|---|---|---|---|
| `pytest backend/tests/*` | 통과 | 통과 (신규 파일 import 안 됨) | ✅ |
| 네이버 동기화 _update_reservation | 동일 동작 | 동일 (lifecycle 호출 0건) | ✅ |
| 수동 PUT update_reservation | 동일 동작 | 동일 | ✅ |
| extend_stay / reduce | 동일 동작 | 동일 | ✅ |
| 자동 배정 | 동일 동작 | 동일 | ✅ |
| `python -c "from app.services.reservation_lifecycle import on_dates_changed"` | ImportError | OK | 신규 능력 (영향 없음) |
| 임의로 `on_dates_changed(...)` 호출 시도 | (불가) | `NotImplementedError` | silent skip 차단 |

---

## 4. 영향받지 않음을 확인할 코드 경로

본 단계에서 단 1 byte도 변경되지 않음:

```
app/api/                                (모든 라우터)
app/services/reservation_mutator.py     (Mutator 마이그레이션 결과물 — 본 단계 무관)
app/services/room_assignment.py         (단계 #1 의 unassign_dates 추가됨 — 본 단계 무관)
app/services/naver_sync.py
app/services/room_auto_assign.py
app/services/chip_reconciler.py
app/services/reconcile.py
app/scheduler/                          (모든 스케줄러)
app/db/                                 (모델 + 마이그레이션)
```

frontend 측: 변경 없음.

---

## 5. 검증 체크리스트

- [ ] **파일 syntax**: `venv/bin/python -m py_compile app/services/reservation_lifecycle.py` 에러 0
- [ ] **import 가능**: 5개 함수 모두 import 성공
  ```python
  from app.services.reservation_lifecycle import (
      on_dates_changed,
      on_constraints_changed,
      on_status_cancelled,
      on_room_assigned,
      on_reservation_deleted,
  )
  ```
- [ ] **외부 참조 0건** (#5~#19 미머지 시점):
  - `grep -rn "reservation_lifecycle" app/ tests/ | grep -v reservation_lifecycle.py | grep -v __pycache__` → 0건
  - 5개 함수명 grep 결과도 신규 파일 외 0건
- [ ] **NotImplementedError 가시화**: 5개 함수 각각 호출 시 즉시 raise
  ```python
  for fn_name in ("on_dates_changed", "on_constraints_changed", "on_status_cancelled", "on_room_assigned", "on_reservation_deleted"):
      try:
          getattr(module, fn_name)(...)  # 적당한 인자
          assert False, f"{fn_name} should have raised"
      except NotImplementedError:
          pass  # 기대됨
  ```
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #1 시점과 동일
- [ ] **caller 파일 변화 0**: `git diff main -- app/` 가 본 신규 파일 외 0 라인

---

## 6. 본 단계 이후의 후속 의존성

본 단계 머지 후 진행 가능:
- **#3** (`reduce_extension` 의 `db.delete(ra)` → `unassign_dates` 위임) — 본 단계와 독립
- **#4** (`naver_sync` cc1 → `unassign_dates`) — 본 단계와 독립
- **#5~#9** (5 함수 실제 구현) — 본 단계의 스켈레톤 시그니처에 의존
- **#10~#19** (caller 전환) — #5~#9 의 구현에 의존

본 단계 단독으로는 의도된 동작 변화 0.

---

## 7. 미결 검토 항목 (단계 #5~#9 사전조사로 위임)

- [ ] `on_room_assigned` 의 `pushed_out` 인자 — `room_auto_assign` 의 자동 배정 시에도 push-out 발생 가능. signature 변경 필요 시 단계 #8 에서 결정.
- [ ] `on_reservation_deleted` 가 `ReservationSmsAssignment`, `PartyCheckin`, `ReservationDailyInfo` 까지 정리할지 — 현재 `reservations.py:DELETE` 본문에서 직접 정리 중. 흡수 vs 외부 유지 결정.
- [ ] lifecycle 함수가 `db.flush()` 호출할지 — 부모 계획 §미결검토 Q3 에서 "caller 책임 유지" 결정. 변경 시 단계 #5~#9 사전조사에서 재논의.

---

## 8. 머지 후 다음 액션

본 단계 PR 머지 → `lifecycle-step-03-reduce-extension-unassign-dates.md` 작성 (단계 #3 사전조사: `db.delete(ra)` → `unassign_dates` 위임).
