# 단계 #18 사전조사 — `reservations_room.py assign` 핸들러 → `on_room_assigned`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: ⚪ 의도된 효과 (push-out 칩 재계산 추가)
> 변경 규모: `app/api/reservations_room.py` ~10 라인 추가

---

## 1. 목적

`assign_room` 호출 직후 `on_room_assigned` 호출 → 본인 + push-out 예약의 5종 칩 재계산.

## 2. 변경 대상

본인 배정 + 그룹 멤버 배정 두 위치에 `on_room_assigned` 추가.

### Before (L97~L114, 본인 배정 + pushed_out 처리)

```python
        _result = room_assignment.assign_room(...)
        if isinstance(_result, tuple):
            _, pushed_out_raw = _result
            for p in pushed_out_raw:
                warnings.append(...)
                pushed_out_list.append({...})
```

### After

```python
        _result = room_assignment.assign_room(...)
        pushed_out_raw = None
        if isinstance(_result, tuple):
            _, pushed_out_raw = _result
            for p in pushed_out_raw:
                warnings.append(...)
                pushed_out_list.append({...})

        # lifecycle 단계 #18: on_room_assigned
        from app.services.reservation_lifecycle import on_room_assigned
        on_room_assigned(db, db_reservation, pushed_out=pushed_out_raw)
```

### 그룹 멤버 배정 (L126~L137)

```python
                try:
                    _gresult = room_assignment.assign_room(
                        db, member.id, room_id, member_from, member_end,
                        assigned_by="manual",
                        created_by=current_user.username,
                        skip_logging=True,
                    )
                    _gpush = _gresult[1] if isinstance(_gresult, tuple) else None
                    on_room_assigned(db, member, pushed_out=_gpush)
                except ValueError as e:
                    warnings.append(f"{member.customer_name}: {e}")
```

## 3. 검증 체크리스트

- [ ] syntax OK
- [ ] `on_room_assigned` 호출 site 2건 추가 (본인 + 그룹 멤버)

## 4. 머지 후 다음 액션

`lifecycle-step-19-room-auto-assign.md` 작성 (#19).
