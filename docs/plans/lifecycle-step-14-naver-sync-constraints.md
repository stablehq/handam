# 단계 #14 사전조사 — `naver_sync` invariant 분기 → `on_constraints_changed`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: 🔵 **의도된 누락 해결 + diag 이벤트 이름 변화**
> 변경 규모: `app/services/naver_sync.py` ~40 라인 → ~10 라인

---

## 1. 변경 대상

`_CONSTRAINT_CHANGED` 분기 (L866~L903) 를 `on_constraints_changed` 호출로 치환.

## 2. Before / After

**Before** (요약):
```python
if _CONSTRAINT_CHANGED:
    try:
        invalid_dates = check_assignment_validity(db, existing)
    except: invalid_dates = []
    if invalid_dates:
        future_invalid = sorted([d for d in invalid_dates if d > today_str])
        if future_invalid:
            end_d = ...
            room_assignment.unassign_room(...)
            try:
                db.flush()
                room_assignment.sync_sms_tags(db, existing.id)
            except: ...
            log_activity(title="네이버 동기화 제약 위반 — 배정 해제", created_by="naver_sync")
            diag("naver_sync.constraint_violation", critical, ...)
```

**After**:
```python
if _CONSTRAINT_CHANGED:
    # lifecycle 단계 #14
    from app.services.reservation_lifecycle import on_constraints_changed
    _changed_set = set()
    if old_male != existing.male_count: _changed_set.add("male_count")
    if old_female != existing.female_count: _changed_set.add("female_count")
    if old_party_size != existing.party_size: _changed_set.add("party_size")
    if old_gender != existing.gender: _changed_set.add("gender")
    on_constraints_changed(db, existing, _changed_set, actor="naver_sync")
```

## 3. 의도된 동작 변화

| 항목 | Before | After |
|---|---|---|
| invariant 위반 시 unassign_room | 호출 | 동일 (lifecycle 내부) |
| invariant 위반 후 칩 재계산 | sync_sms_tags 만 (기본 칩) | reconcile_all_chips (5종 전부) — **누락 #5 해결** |
| log_activity title | "네이버 동기화 제약 위반 — 배정 해제" | "제약 위반 배정 해제 (N일)" — title 통일 |
| log_activity detail.trigger | "naver_sync_constraint_violation" | "constraint_field_change" — 통일 |
| diag 이벤트 이름 | "naver_sync.constraint_violation" | "invariant.violation_detected" — 통일 |
| log_activity created_by | "naver_sync" | "naver_sync" (actor 인자로 전달) |
| invariant 위반 없을 때 reconcile_all_chips | 호출 0 | reconcile_all_chips 호출 (lifecycle 항상) — 추가 효과 |

→ diag/log 이름 변경은 의도된 통일. 운영 모니터링 도구가 두 이름 모두 인식하려면 alias 추가 필요 (별도 작업).

## 4. 검증 체크리스트

- [ ] syntax OK
- [ ] diff: ~30 라인 축소
- [ ] `on_constraints_changed` 호출 site 2건 (reservations.py + naver_sync.py)
- [ ] diag 이벤트 이름 변경 인지 — 운영 모니터링 별도 검토

## 5. 머지 후 다음 액션

`lifecycle-step-15-naver-sync-cancel.md` 작성 (#15).
