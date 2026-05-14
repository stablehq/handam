# 단계 #15 사전조사 — `naver_sync` cc1/cc2 + cancel cleanup → `on_status_cancelled`

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: ⚫ 리팩토링 + 🟡 의미 정정 (CANCELLED 가드 추가)
> 변경 규모: `app/services/naver_sync.py` ~50 라인 → ~6 라인

---

## 1. 목적

cc1 (당일 취소) / cc2 (사전 취소) 분기 + 공통 미발송 칩 cleanup 을 `on_status_cancelled` 단일 호출로 통합.

## 2. 의미 정정 — CANCELLED 가드 추가

**Before**: `if _prev_status != existing.status:` 안에서 status 종류 무관하게 cc1/cc2 + cleanup 실행 (CONFIRMED→CANCELLED 뿐 아니라 CANCELLED→CONFIRMED 재활성에도 발동). 단 재활성 시 idempotent 라 무해 (affected_dates 빈 / clear_all no-op).

**After**: `if existing.status == ReservationStatus.CANCELLED:` 가드 추가. CANCELLED 일 때만 lifecycle 호출. 재활성 시 호출 안 함 — 기존 idempotent 결과와 동등.

## 3. 변경 대상 코드

### Before (L786~L831):

```python
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        check_in_str = str(existing.check_in_date) if existing.check_in_date else ""
        is_same_day_cancel = (check_in_str == today_str)
        if is_same_day_cancel:
            from app.db.models import RoomAssignment as RA
            tid = get_session_tenant_id(db)
            affected_dates = [
                ra.date for ra in db.query(RA).filter(
                    RA.reservation_id == existing.id,
                    RA.tenant_id == tid,
                    RA.date >= today_str,
                ).all()
            ]
            if affected_dates:
                room_assignment.unassign_dates(db, existing.id, affected_dates)
                existing.room_number = None
                existing.room_password = None
                diag("naver_sync.same_day_cancel", level="critical", reservation_id=existing.id, dates=affected_dates)
        else:
            room_assignment.clear_all_for_reservation(db, existing.id)
        _cancel_deleted = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.tenant_id == existing.tenant_id,
            ReservationSmsAssignment.reservation_id == existing.id,
            ReservationSmsAssignment.sent_at.is_(None),
        ).delete(synchronize_session='fetch')
        diag(
            "naver_sync.cancel_chip_cleanup",
            level="verbose",
            res_id=existing.id,
            tenant_id=existing.tenant_id,
            deleted=_cancel_deleted,
        )
```

### After:

```python
        # lifecycle 단계 #15: status 변화 처리 (CANCELLED 만)
        if existing.status == ReservationStatus.CANCELLED:
            today_str = datetime.now(KST).strftime("%Y-%m-%d")
            check_in_str = str(existing.check_in_date) if existing.check_in_date else ""
            is_same_day_cancel = (check_in_str == today_str)
            from app.services.reservation_lifecycle import on_status_cancelled
            on_status_cancelled(db, existing, same_day=is_same_day_cancel)
```

총 ~45 라인 → 6 라인 = **-39 라인**.

## 4. 동작 동등성

| 시나리오 | Before | After | 동등 |
|---|---|---|---|
| CONFIRMED → CANCELLED, 당일 (cc1) | unassign_dates + room_number=None + diag + cleanup | 동일 (lifecycle 내부) | ✅ |
| CONFIRMED → CANCELLED, 사전 (cc2) | clear_all + cleanup | 동일 | ✅ |
| CANCELLED → CONFIRMED (재활성) | cc1/cc2 + cleanup 무조건 실행 (idempotent — no-op) | CANCELLED 가드로 skip | ✅ DB 결과 동등 |
| 다른 status 변화 (PENDING→CONFIRMED 등) | cc1/cc2 + cleanup 실행 (idempotent no-op) | skip | ✅ DB 결과 동등 |

## 5. 검증 체크리스트

- [ ] syntax OK
- [ ] diff: ~39 라인 축소
- [ ] `on_status_cancelled` 호출 site 1건 (naver_sync.py)
- [ ] 기존 pytest 회귀

## 6. 머지 후 다음 액션

`lifecycle-step-16-extend-stay-lifecycle.md` 작성 (#16).
