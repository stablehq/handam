# 단계 #7 사전조사 — `on_status_cancelled` 실제 구현

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §C
> 분류: ⚪ 동작 변화 없음 (caller 호출 0건)
> 변경 규모: `reservation_lifecycle.py` 의 `on_status_cancelled` 본문 교체 (~40 라인)

---

## 1. 목적

`naver_sync._update_reservation` 의 cc1 (당일 취소) / cc2 (사전 취소) 분기 + 공통 ReservationSmsAssignment 정리 를 lifecycle 함수로 흡수.

caller (단계 #15) 는 `on_status_cancelled(db, reservation, same_day=True/False)` 만 호출. 내부에서 분기.

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| stay_group unlink + peer sync_sms_tags (caller L860~L880) | caller 책임 유지 (부모 계획 Q2 결정) |
| `naver_sync` cc1/cc2 분기를 본 함수 호출로 전환 | 단계 #15 |

---

## 2. 변경 대상 코드

### `app/services/reservation_lifecycle.py` 의 `on_status_cancelled` 함수 본문

**Before** (단계 #2):

```python
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
```

**After**:

```python
def on_status_cancelled(
    db: "Session",
    reservation: "Reservation",
    *,
    same_day: bool,
) -> None:
    """status=CANCELLED 변경 직후 호출. cc1 (당일) / cc2 (사전) 분기 흡수.

    동작:
      - same_day=True (cc1, 당일 취소):
          1) 오늘 이후 affected_dates 수집 (idempotent guard)
          2) unassign_dates 로 RA 삭제 + bed_order 재정렬 + 칩 cleanup
          3) reservation.room_number/room_password = None
          4) critical diag
      - same_day=False (cc2, 사전 취소):
          1) clear_all_for_reservation — 전체 RA 삭제 + denormalized 필드 정리
      - 공통: ReservationSmsAssignment 의 미발송 칩 (sent_at IS NULL) 삭제 + verbose diag

    caller (단계 #15): naver_sync cc1/cc2 분기.

    Note: stay_group unlink + peer sync_sms_tags 는 caller 책임 (부모 계획 Q2).
    """
    from datetime import datetime
    from app.config import KST
    from app.db.models import RoomAssignment, ReservationSmsAssignment
    from app.db.tenant_context import get_session_tenant_id
    from app.services import room_assignment
    from app.diag_logger import diag

    tid = get_session_tenant_id(db)

    if same_day:
        # cc1: 당일 취소 — 오늘 이후 affected_dates 수집
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        affected_dates = [
            ra.date for ra in db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id == reservation.id,
                RoomAssignment.tenant_id == tid,
                RoomAssignment.date >= today_str,
            ).all()
        ]
        # Idempotent guard: 이미 정리된 cancelled 예약이면 매 sync 무용한 delete 회피
        if affected_dates:
            room_assignment.unassign_dates(db, reservation.id, affected_dates)
            reservation.room_number = None
            reservation.room_password = None
            diag(
                "naver_sync.same_day_cancel",
                level="critical",
                reservation_id=reservation.id,
                dates=affected_dates,
            )
    else:
        # cc2: 사전 취소 — 전체 배정 해제
        room_assignment.clear_all_for_reservation(db, reservation.id)

    # 공통: 미발송 SMS 칩 삭제 (sent 보호)
    _cancel_deleted = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.tenant_id == reservation.tenant_id,
        ReservationSmsAssignment.reservation_id == reservation.id,
        ReservationSmsAssignment.sent_at.is_(None),
    ).delete(synchronize_session='fetch')
    diag(
        "naver_sync.cancel_chip_cleanup",
        level="verbose",
        res_id=reservation.id,
        tenant_id=reservation.tenant_id,
        deleted=_cancel_deleted,
    )
```

### 2-1. caller 코드와의 1:1 매핑

**naver_sync.py L789~L857 (단계 #4 후 상태)** → on_status_cancelled 내부:

| Before (naver_sync) | After (on_status_cancelled) |
|---|---|
| `if is_same_day_cancel:` | `if same_day:` |
| `from RA import RoomAssignment; tid = get_session_tenant_id(db)` | 동일 (lifecycle 내부) |
| `affected_dates = [ra.date for ra in db.query(RA).filter(...).all()]` | 동일 — `db.query(RoomAssignment).filter(reservation_id=reservation.id, ...)` |
| `if affected_dates:` | 동일 |
| `room_assignment.unassign_dates(db, existing.id, affected_dates)` | `room_assignment.unassign_dates(db, reservation.id, affected_dates)` |
| `existing.room_number = None; existing.room_password = None` | `reservation.room_number = None; reservation.room_password = None` |
| `diag("naver_sync.same_day_cancel", critical, dates=affected_dates)` | 동일 (이벤트 이름 유지) |
| `else: room_assignment.clear_all_for_reservation(db, existing.id)` | 동일 |
| `_cancel_deleted = db.query(ReservationSmsAssignment).filter(tenant_id, res_id, sent_at None).delete()` | 동일 |
| `diag("naver_sync.cancel_chip_cleanup", verbose, deleted=_cancel_deleted)` | 동일 |

→ 책임 1:1 매핑. caller 의 후속 stay_group unlink + peer sync_sms_tags 는 lifecycle 밖에서 caller 가 처리 (Q2 결정).

### 2-2. diag 이벤트 이름 유지

`naver_sync.same_day_cancel` 와 `naver_sync.cancel_chip_cleanup` 두 critical/verbose 이벤트의 이름을 그대로 유지 — 운영 모니터링 도구 호환성 보장.

본 함수가 naver_sync 외 다른 caller 에서도 호출될 가능성 있지만, 현재 마이그레이션 범위에서는 cc1/cc2 가 유일. 이벤트 이름 변경 시 별도 마일스톤.

### 2-3. ReservationSmsAssignment 정리는 항상 발동

기존 naver_sync 의 cancel 분기 후 공통 처리. lifecycle 안에서도 `if same_day / else` 분기 후 항상 발동. caller 마다 sent 보호 정책 (`sent_at IS NULL` 필터) 유지.

---

## 3. 동작 동등성 근거

### 3-1. 호출 site 0건 — 동작 변화 0

본 단계 #7 머지 시점:
- caller 0건 — SQL 결과 동일
- `git diff` 가 `reservation_lifecycle.py` 외 0 라인

### 3-2. 케이스별 매트릭스

| 시나리오 | Before (naver_sync 직접) | After (on_status_cancelled) | 동등 |
|---|---|---|---|
| same_day=True, affected_dates 있음 | unassign_dates + room_number/password=None + critical diag | 동일 | ✅ |
| same_day=True, affected_dates 빈 (idempotent) | guard 로 skip | 동일 | ✅ |
| same_day=False (cc2) | clear_all_for_reservation | 동일 | ✅ |
| 미발송 SMS 칩 있는 cancel | delete + verbose diag (cancel_chip_cleanup) | 동일 | ✅ |
| sent SMS 칩 있는 cancel | sent 보존 (`sent_at IS NULL` 필터) | 동일 | ✅ |

### 3-3. 단위 테스트 (선택)

```python
def test_same_day_true_calls_unassign_dates(monkeypatch):
    """same_day=True 경로: affected_dates 수집 후 unassign_dates"""
    monkeypatch.setattr("...db.query", make_query_with_dates(["2026-05-15"]))
    calls = []
    monkeypatch.setattr("...room_assignment.unassign_dates", lambda db, rid, dates: calls.append(("unassign", rid, dates)))

    res = make_fake_reservation(id=1, tenant_id=1)
    on_status_cancelled(db, res, same_day=True)
    assert ("unassign", 1, ["2026-05-15"]) in calls
    assert res.room_number is None

def test_same_day_false_calls_clear_all(monkeypatch):
    """same_day=False 경로: clear_all_for_reservation"""
    calls = []
    monkeypatch.setattr("...room_assignment.clear_all_for_reservation", lambda db, rid: calls.append(("clear_all", rid)))

    res = make_fake_reservation(id=1, tenant_id=1)
    on_status_cancelled(db, res, same_day=False)
    assert ("clear_all", 1) in calls
```

---

## 4. 영향받지 않음을 확인할 코드 경로

```
app/services/reservation_lifecycle.py 의 다른 4개 함수:
  - on_dates_changed (#5)             ← 실제 구현 유지
  - on_constraints_changed (#6)       ← 실제 구현 유지
  - on_room_assigned (#8)             ← 스켈레톤 유지
  - on_reservation_deleted (#9)       ← 스켈레톤 유지

naver_sync.py cc1/cc2 caller 분기 — 변경 0 (단계 #15 에서 본 함수 호출로 전환)
모든 caller 모두 변경 0
```

frontend: 변경 없음.

---

## 5. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/reservation_lifecycle.py` 에러 0
- [ ] **import 가능**: `from app.services.reservation_lifecycle import on_status_cancelled`
- [ ] **signature**: `(db, reservation, *, same_day)` — keyword-only same_day 유지
- [ ] **NotImplementedError 사라짐**: `on_status_cancelled` 의 src 에 `NotImplementedError` 미포함
- [ ] **다른 2 함수 스켈레톤 유지** (#8, #9): NotImplementedError raise 검증
- [ ] **caller 호출 0건**: `grep -rn "on_status_cancelled(" app/ tests/ | grep -v reservation_lifecycle.py` → 0건
- [ ] **same_day 누락 TypeError**: positional 호출 시 즉시 실패
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #6 시점과 동일

---

## 6. 본 단계 이후의 후속 의존성

- **#8, #9** (다른 lifecycle 함수 구현) — 본 단계와 독립
- **#15** (`naver_sync` cc1/cc2 → 본 함수 호출) — 본 단계 의존

본 단계 단독으로는 의도된 동작 변화 0.

---

## 7. 미결 검토 항목

- [ ] `reservation.tenant_id` 직접 접근 — caller (naver_sync) 와 동일 패턴이지만 multi-tenant 컨텍스트 검증. tenant_context.py 의 자동 필터는 SELECT 시 발동, DELETE 는 명시 필요. 본 함수는 명시 `ReservationSmsAssignment.tenant_id == reservation.tenant_id` — 안전.
- [ ] `diag` 이벤트 이름이 `naver_sync.` prefix 유지 — 다른 caller 에서 호출 시 이름 부정확. 단계 #15 머지 후 운영 모니터링 도구 점검.

---

## 8. 머지 후 다음 액션

`lifecycle-step-08-on-room-assigned-impl.md` 작성 (단계 #8).
