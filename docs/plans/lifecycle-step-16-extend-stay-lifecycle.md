# 단계 #16 사전조사 — `extend_stay` → `on_dates_changed` + `on_room_assigned`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: 🔵 **누락 #1 (shift_daily) + #5 (칩 reconcile) 해결**
> 변경 규모: `app/api/reservations_stay.py` ~15 라인 치환

---

## 1. 목적

extend_stay 의 후처리를 lifecycle 로 통합:
- 구버전 `reconcile_chips_for_reservation` → `on_dates_changed` 의 `reconcile_all_chips` (5종 전부) — **누락 #5 해결**
- shift_daily_records / reconcile_dates 호출 신규 추가 — **누락 #1 해결**
- assign_room 후 `on_room_assigned` 호출 추가

## 2. 변경 대상

### `reservations_stay.py` L226~L249

**Before**:

```python
    # 4. Assign room for the new night (only if no conflict)
    if request.room_id and not conflict_guests:
        assign_room(
            db, reservation_id, request.room_id, new_night_str,
            end_date=new_end_str,
            assigned_by="manual",
            created_by=current_user.username,
        )
        conflict_resolved = True

    # 5. Reconcile chips for the full new date range
    schedules = (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.tenant_id == tid,
            TemplateSchedule.is_active == True,
        )
        .all()
    )
    reconcile_chips_for_reservation(db, reservation_id, schedules=schedules)
```

**After**:

```python
    # 4. Assign room for the new night (only if no conflict)
    if request.room_id and not conflict_guests:
        _result = assign_room(
            db, reservation_id, request.room_id, new_night_str,
            end_date=new_end_str,
            assigned_by="manual",
            created_by=current_user.username,
        )
        conflict_resolved = True
        # lifecycle 단계 #16: on_room_assigned
        from app.services.reservation_lifecycle import on_room_assigned
        _pushed_out = _result[1] if isinstance(_result, tuple) else None
        on_room_assigned(db, original, pushed_out=_pushed_out)

    # 5. on_dates_changed: check_out 변경 후 shift_daily + reconcile_dates + reconcile_all_chips
    from app.services.reservation_lifecycle import on_dates_changed
    on_dates_changed(db, original, original.check_in_date, current_end)
```

## 3. 의도된 동작 변화

| 후처리 | Before | After |
|---|---|---|
| reconcile_chips_for_reservation (구버전 — 기본 칩만) | 호출 | 제거 → `reconcile_all_chips` (5종 전부, lifecycle 내부) — **#5 해결** |
| shift_daily_records | ❌ 호출 0 | lifecycle 내부 호출 — **#1 해결** |
| reconcile_dates | ❌ 호출 0 | lifecycle 내부 호출 |
| push-out 칩 재계산 | ❌ 호출 0 | on_room_assigned 안에서 호출 |

## 4. 검증 체크리스트

- [ ] syntax OK
- [ ] `reconcile_chips_for_reservation` 호출 1건 감소 (extend_stay)
- [ ] `on_dates_changed` 호출 site 추가 (extend_stay)
- [ ] `on_room_assigned` 호출 site 1건 (extend_stay)

## 5. 머지 후 다음 액션

`lifecycle-step-17-reduce-extension-lifecycle.md` 작성 (#17).
