# 단계 #11 사전조사 — `reservations.py PUT` invariant 분기 → `on_constraints_changed`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: ⚫ 리팩토링 (동작 동등)
> 변경 규모: `app/api/reservations.py` L397~L430 → ~7 라인

---

## 1. 목적

invariant check 분기를 `on_constraints_changed` 단일 호출로 치환. 단계 #6 구현의 caller 전환 첫 번째.

---

## 2. 변경 대상 코드

### `app/api/reservations.py` L397~L430

**Before**:

```python
    # Phase 2-5a: 성별/인원 변경 시 invariant 재검증
    if constraint_changed:
        try:
            from app.services.room_assignment_invariants import check_assignment_validity
            invalid_dates = check_assignment_validity(db, db_reservation)
        except Exception as e:
            logger.warning(f"check_assignment_validity failed: {e}")
            invalid_dates = []

        if invalid_dates:
            from datetime import timedelta
            from app.config import KST
            today_str = datetime.now(KST).strftime("%Y-%m-%d")
            future_invalid = sorted([d for d in invalid_dates if d > today_str])
            if future_invalid:
                end_d = (datetime.strptime(future_invalid[-1], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                room_assignment.unassign_room(
                    db, reservation_id,
                    from_date=future_invalid[0],
                    end_date=end_d,
                )
                # ※ unassign 후 칩 재동기화는 함수 끝 reconcile_all_chips 에서 일괄 처리
                log_activity(
                    db, type="room_move",
                    title=f"[{db_reservation.customer_name}] 제약 위반 배정 해제 ({len(future_invalid)}일)",
                    detail={
                        "reservation_id": reservation_id,
                        "invalid_dates": future_invalid,
                        "trigger": "constraint_field_change",
                        "changed_fields": list(_CONSTRAINT_FIELDS & set(update_data.keys())),
                    },
                    created_by=current_user.username,
                )
                diag("invariant.violation_detected", level="critical", reservation_id=reservation_id, invalid_dates=future_invalid)
```

**After**:

```python
    # Phase 2-5a: 성별/인원 변경 시 invariant 재검증 (lifecycle 단계 #11)
    if constraint_changed:
        from app.services.reservation_lifecycle import on_constraints_changed
        on_constraints_changed(
            db, db_reservation,
            _CONSTRAINT_FIELDS & set(update_data.keys()),
            actor=current_user.username if current_user else "system",
        )
```

총 33 라인 → 7 라인 = **-26 라인**.

### 2-1. 1:1 매핑

- `check_assignment_validity` + `try/except` → lifecycle 내부
- `if invalid_dates: future_invalid + unassign_room + log_activity + diag` → lifecycle 내부 동일
- `reconcile_all_chips` → lifecycle 내부 (caller 의 chip_affecting 분기와 중복, idempotent 안전)
- `current_user.username` → `actor` 인자로 전달

### 2-2. 의도된 변화 — reconcile_all_chips 중복

단계 #6 의 `on_constraints_changed` 가 `reconcile_all_chips` 항상 호출. caller 의 L443~ `if chip_affecting:` 분기도 호출 → 중복 2회. idempotent 안전. 단계 외 정리 가능.

---

## 3. 동작 동등성

| 시나리오 | Before | After | 동등 |
|---|---|---|---|
| constraint_changed=False | invariant 분기 skip | 동일 (`if constraint_changed:` False) | ✅ |
| 인원 변경, invariant 위반 없음 | check_validity → invalid_dates=[] → no-op | 동일 (lifecycle 내부 invalid_dates=[]) | ✅ |
| 인원 변경, invariant 위반 (future_invalid) | unassign + log + diag | 동일 (lifecycle 내부) | ✅ |
| 인원 변경, 위반 + reconcile_all_chips 호출 | chip_affecting 분기에서 1회 | lifecycle + chip_affecting 분기 = 2회 (idempotent) | ✅ |

---

## 4. 검증 체크리스트

- [ ] syntax OK
- [ ] diff: -26 라인
- [ ] `on_constraints_changed` 호출 site 1건 추가
- [ ] caller 의 invariant check 분기 코드 전부 사라짐
- [ ] 기존 pytest 회귀

---

## 5. 머지 후 다음 액션

`lifecycle-step-12-reservations-put-delete.md` 작성 (#12).
