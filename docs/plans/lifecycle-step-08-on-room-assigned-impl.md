# 단계 #8 사전조사 — `on_room_assigned` 실제 구현

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §C
> 분류: ⚪ 동작 변화 없음 (caller 호출 0건)
> 변경 규모: `reservation_lifecycle.py` 의 `on_room_assigned` 본문 교체 (~15 라인)

---

## 1. 목적

`assign_room` 직후 호출되어:
1. reservation 본인의 5종 칩 재계산
2. push-out 된 예약 각각의 5종 칩 재계산

→ 단계 #18 (`reservations_room.py` assign 핸들러) / #19 (`room_auto_assign`) 머지 후 발동.

---

## 2. 변경 대상 코드

### `app/services/reservation_lifecycle.py` 의 `on_room_assigned` 본문

**Before** (단계 #2):

```python
def on_room_assigned(
    db: "Session",
    reservation: "Reservation",
    pushed_out: Optional[list[dict]] = None,
) -> None:
    """..."""
    raise NotImplementedError(...)
```

**After**:

```python
def on_room_assigned(
    db: "Session",
    reservation: "Reservation",
    pushed_out: Optional[list[dict]] = None,
) -> None:
    """assign_room 직후 호출. push-out 된 예약의 칩까지 재계산.

    동작:
      1) reconcile_all_chips(db, reservation.id) — 본인 칩 재계산
      2) for p in pushed_out: reconcile_all_chips(db, p["reservation_id"]) — push-out 예약별 재계산

    pushed_out 의 각 dict 구조: {"reservation_id": int, "customer_name": str, "date": str, "cause": str}
    (assign_room 반환값의 두 번째 tuple element).

    caller (단계 #16/#18/#19): extend_stay, reservations_room.py assign PUT, room_auto_assign.
    """
    from app.services.reconcile import reconcile_all_chips

    reconcile_all_chips(db, reservation.id)

    if pushed_out:
        seen_ids = set()
        for p in pushed_out:
            res_id = p.get("reservation_id")
            if res_id is not None and res_id not in seen_ids:
                seen_ids.add(res_id)
                reconcile_all_chips(db, res_id)
```

**라인 단위 정당화**:
- `reconcile_all_chips(db, reservation.id)` — 기본 재계산. 항상 호출.
- `if pushed_out:` 가드 — None 또는 빈 list 인 경우 skip.
- `seen_ids` 중복 방지 — 같은 reservation_id 가 여러 날짜에 push-out 될 수 있음 (`assign_room` push-out 분기에서 같은 res 가 여러 셀에서 push-out 가능). 중복 reconcile 회피.
- `p.get("reservation_id")` — assign_room 반환 dict 구조에 의존. None 케이스 가드.

---

## 3. 동작 동등성

본 단계 #8 머지 시점: caller 호출 0건 — 동작 변화 0.

단계 #16/#18/#19 머지 후:
- 시나리오: extend_stay 가 `assign_room` 호출 후 `on_room_assigned(...)` 호출 → 본인 칩 재계산 (Before 는 `reconcile_chips_for_reservation` 구버전만 호출 — 부분 칩만)
- 효과: 칩 5종 전부 재계산 — **누락 패턴 #5 해결**

---

## 4. 영향받지 않음

`reconcile_all_chips` 자체 변경 0. `assign_room` 변경 0. caller 모두 변경 0.

---

## 5. 검증 체크리스트

- [ ] syntax OK
- [ ] NotImplementedError 사라짐
- [ ] 나머지 1개 (`on_reservation_deleted`) 스켈레톤 유지
- [ ] caller 호출 0건
- [ ] pushed_out=None 케이스 안전 (TypeError 없음)
- [ ] pushed_out 의 중복 reservation_id 처리 안전

---

## 6. 머지 후 다음 액션

`lifecycle-step-09-on-reservation-deleted-impl.md` 작성 (#9).
