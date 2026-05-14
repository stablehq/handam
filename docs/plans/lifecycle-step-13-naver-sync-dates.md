# 단계 #13 사전조사 — `naver_sync._update_reservation` 날짜 분기 → `on_dates_changed`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: 🔵 **의도된 누락 해결** (#5 — 칩 reconcile 비대칭)
> 변경 규모: `app/services/naver_sync.py` ~3 라인 치환

---

## 1. 목적

naver_sync 의 날짜 변경 분기 (`shift_daily_records + reconcile_dates`) 를 `on_dates_changed` 단일 호출로 치환. lifecycle 안에 `reconcile_all_chips` 가 추가로 호출됨 — **누락 패턴 #5 (surcharge/party3/upgrade 칩 stale) 해결**.

## 2. 변경 대상 코드

### `naver_sync.py` L850~L853

**Before**:

```python
    # Reconcile room assignments if dates changed
    if existing.check_in_date != old_date or existing.check_out_date != old_end_date:
        room_assignment.shift_daily_records(db, existing, old_date, old_end_date)
        room_assignment.reconcile_dates(db, existing)
```

**After**:

```python
    # Reconcile room assignments if dates changed (lifecycle 단계 #13)
    if existing.check_in_date != old_date or existing.check_out_date != old_end_date:
        from app.services.reservation_lifecycle import on_dates_changed
        on_dates_changed(db, existing, old_date, old_end_date)
```

## 3. 의도된 동작 변화 — 누락 #5 해결

| 칩 종류 | Before (naver_sync 날짜 변경 시) | After |
|---|---|---|
| sync_sms_tags (기본) | 1회 (L924 sms 필드 변경 시 또는 #15 invariant 후) | reconcile_all_chips 안에서 1회 |
| reconcile_surcharge | ❌ 호출 0건 | reconcile_all_chips 안에서 호출 |
| reconcile_party3_mms | ❌ 호출 0건 | reconcile_all_chips 안에서 호출 |
| reconcile_room_upgrade_promise | ❌ 호출 0건 | reconcile_all_chips 안에서 호출 |
| reconcile_room_upgrade_review | ❌ 호출 0건 | reconcile_all_chips 안에서 호출 |

→ 누락 패턴 #5 해결. naver_sync 가 날짜 변경 후 surcharge 등 5종 칩 모두 갱신.

## 4. 검증 체크리스트

- [ ] syntax OK
- [ ] diff: -1 라인 (reconcile_dates 1 줄 사라지고 import + on_dates_changed 으로 대체)
- [ ] `on_dates_changed` 호출 site 2건 (reservations.py + naver_sync.py)

## 5. 머지 후 다음 액션

`lifecycle-step-14-naver-sync-constraints.md` 작성 (#14).
