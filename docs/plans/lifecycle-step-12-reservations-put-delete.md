# 단계 #12 사전조사 — `reservations.py delete_reservation` → `on_reservation_deleted`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: ⚫ 리팩토링
> 변경 규모: `app/api/reservations.py` ~5 라인 축소

---

## 1. 변경 대상 코드

**Before**:

```python
    # 연관 레코드 먼저 삭제 (FK 제약, 현재 테넌트만)
    from app.db.models import PartyCheckin, ReservationDailyInfo
    from app.db.tenant_context import get_session_tenant_id
    tid = get_session_tenant_id(db)
    from app.services.room_assignment import clear_all_for_reservation
    clear_all_for_reservation(db, reservation_id)
    db.query(ReservationSmsAssignment).filter(ReservationSmsAssignment.reservation_id == reservation_id, ReservationSmsAssignment.tenant_id == tid).delete()
    db.query(ReservationDailyInfo).filter(ReservationDailyInfo.reservation_id == reservation_id, ReservationDailyInfo.tenant_id == tid).delete()
    db.query(PartyCheckin).filter(PartyCheckin.reservation_id == reservation_id, PartyCheckin.tenant_id == tid).delete()
```

**After**:

```python
    # 연관 레코드 정리 (lifecycle 단계 #12)
    from app.services.reservation_lifecycle import on_reservation_deleted
    on_reservation_deleted(db, reservation_id)
```

## 2. 동작 동등성

1:1 매핑 — lifecycle 내부 동일 SQL DELETE (단계 #9 §2).

## 3. 검증 체크리스트

- [ ] syntax OK
- [ ] `on_reservation_deleted` 호출 site 1건
- [ ] caller 의 ReservationSmsAssignment / DailyInfo / PartyCheckin / clear_all import 모두 제거됨

## 4. 머지 후 다음 액션

`lifecycle-step-13-naver-sync-dates.md` 작성 (#13).
