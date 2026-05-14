# 단계 #9 사전조사 — `on_reservation_deleted` 실제 구현

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §C
> 분류: ⚪ 동작 변화 없음 (caller 호출 0건)
> 변경 규모: `reservation_lifecycle.py` 의 `on_reservation_deleted` 본문 교체 (~15 라인)

---

## 1. 목적

예약 DELETE 시 연관 레코드 정리를 lifecycle 함수로 흡수:
1. `clear_all_for_reservation` — RoomAssignment 전체 + denormalized 필드 정리
2. `ReservationSmsAssignment` 전체 삭제 (sent/unsent 모두 — 예약 자체 사라지므로)
3. `ReservationDailyInfo` 전체 삭제
4. `PartyCheckin` 전체 삭제

caller (단계 #12, `reservations.py:459 delete_reservation`) 는 stay_group unlink (Q2 — caller 책임) + `db.delete(reservation)` + commit + diag 유지. lifecycle 호출 1줄.

---

## 2. 변경 대상 코드

### `app/services/reservation_lifecycle.py` 의 `on_reservation_deleted` 본문

**Before** (단계 #2):

```python
def on_reservation_deleted(
    db: "Session",
    reservation_id: int,
) -> None:
    """..."""
    raise NotImplementedError(...)
```

**After**:

```python
def on_reservation_deleted(
    db: "Session",
    reservation_id: int,
) -> None:
    """예약 삭제 (DELETE /reservations/{id}) 직후 호출.

    동작: 모든 연관 레코드 삭제 (FK 제약 + 깔끔 정리):
      1) clear_all_for_reservation — RoomAssignment 전체 + denormalized 필드
      2) ReservationSmsAssignment 전체 삭제 (sent/unsent 모두 — 예약 사라지므로)
      3) ReservationDailyInfo 전체 삭제
      4) PartyCheckin 전체 삭제

    caller (단계 #12): reservations.py delete_reservation.

    Note: stay_group unlink 와 db.delete(reservation) + commit + diag 는 caller 책임.
    """
    from app.db.models import ReservationSmsAssignment, ReservationDailyInfo, PartyCheckin
    from app.db.tenant_context import get_session_tenant_id
    from app.services.room_assignment import clear_all_for_reservation

    tid = get_session_tenant_id(db)

    clear_all_for_reservation(db, reservation_id)
    db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.tenant_id == tid,
    ).delete()
    db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.tenant_id == tid,
    ).delete()
    db.query(PartyCheckin).filter(
        PartyCheckin.reservation_id == reservation_id,
        PartyCheckin.tenant_id == tid,
    ).delete()
```

### 2-1. caller 코드와의 1:1 매핑

**Before (reservations.py L471~L480)** → on_reservation_deleted 내부:

| Before | After |
|---|---|
| `tid = get_session_tenant_id(db)` | 동일 (lifecycle 내부) |
| `clear_all_for_reservation(db, reservation_id)` | 동일 |
| `db.query(ReservationSmsAssignment).filter(...).delete()` | 동일 |
| `db.query(ReservationDailyInfo).filter(...).delete()` | 동일 |
| `db.query(PartyCheckin).filter(...).delete()` | 동일 |

caller 잔존:
- `if db_reservation.stay_group_id: unlink_from_group(...)` — stay_group 처리 (Q2)
- `db.delete(db_reservation)` — 예약 자체 삭제
- `db.commit()` — caller 책임 (Q3)
- `diag("reservation.deleted", critical, actor=current_user.username, ...)` — actor 정보 caller 가 보유

---

## 3. 동작 동등성

본 단계 #9 머지 시점: caller 0건 — 동작 변화 0.

단계 #12 머지 후: caller 코드 5 라인이 `on_reservation_deleted(db, reservation_id)` 1 라인으로 축소. SQL 결과 동등.

---

## 4. 영향받지 않음

다른 4 함수 (#5~#8 의 4 lifecycle 함수) 변경 0. `reservations.py delete_reservation` 변경 0 (단계 #12 에서).

---

## 5. 검증 체크리스트

- [ ] syntax OK
- [ ] NotImplementedError 사라짐 (5 함수 모두 실제 구현)
- [ ] caller 호출 0건
- [ ] import 가능

---

## 6. 머지 후 다음 액션

`lifecycle-step-10-reservations-put-dates-to-lifecycle.md` 작성 (#10 — caller 전환 시작).
