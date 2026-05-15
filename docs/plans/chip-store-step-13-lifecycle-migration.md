# 단계 #13 사전조사 — `reservation_lifecycle.py` 이주 (OQ-2 발효)

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #13
> 분류: 🔵 의도된 변화 — OQ-2-a + OQ-2-b 정책 발효
> 변경 규모: 2 lifecycle 함수 의 chip DELETE → chip_store.delete_chips_for_reservation(force=True)

---

## 1. 목적

`on_status_cancelled` 와 `on_reservation_deleted` 의 직접 칩 DELETE 를
`chip_store.delete_chips_for_reservation(force=True)` 위임으로 교체.
OQ-2 결정 (취소·삭제 시 cascade) 발효.

---

## 2. 변경 대상 코드

### 2-1. `on_status_cancelled` 공통 cleanup (line 179~191)

**Before**: `sent_at IS NULL` 만 가드 (manual/excluded/failed silent 삭제)
```python
_cancel_deleted = db.query(ReservationSmsAssignment).filter(
    ReservationSmsAssignment.tenant_id == reservation.tenant_id,
    ReservationSmsAssignment.reservation_id == reservation.id,
    ReservationSmsAssignment.sent_at.is_(None),
).delete(synchronize_session='fetch')
```

**After**: OQ-2-a cascade (force=True)
```python
from app.services.chip_store import delete_chips_for_reservation
_cancel_deleted = delete_chips_for_reservation(
    db, reservation_id=reservation.id, force=True,
)
```

**행위 변화**:
- 기존: manual/excluded/failed 칩 + sent_at NULL 인 것만 cleanup (sent 보호)
- 신규: **모든 미발송 칩 + 발송된 칩까지** cleanup (force=True)
- 즉 sent_at IS NOT NULL 칩도 삭제됨!

⚠️ 잠깐 — sent 칩까지 삭제? 의도된 동작인가?

운영 의미: 취소된 예약의 sent 기록도 삭제. 이력 손실 가능성.

→ **재검토 필요** — OQ-2-a 결정은 "manual cascade" 였지 "sent 까지 삭제" 가 아님.

`force=True` 가 너무 광범위. 정확한 매핑:
- sent 기록은 보존 (이력 가치)
- manual/excluded/failed/auto unsent 만 cleanup

→ chip_store.delete_chips_for_reservation 에 `keep_sent` 옵션 필요? 아니면 force 분리?

대안: **manual/excluded/failed 가드만 우회, sent 보호는 유지**:
```python
.filter(
    ReservationSmsAssignment.sent_at.is_(None),  # sent 보호 유지
    # manual/excluded/failed 가드는 force=True 효과로 우회
)
```

이게 OQ-2-a 의도. 추가 함수 인자 필요.

### 2-2. `on_reservation_deleted` cascade (line 245~248)

**Before**: 가드 없이 전부 delete
```python
db.query(ReservationSmsAssignment).filter(
    ReservationSmsAssignment.reservation_id == reservation_id,
    ReservationSmsAssignment.tenant_id == tid,
).delete()
```

**After**: force=True (예약 row 자체 사라짐, sent 이력도 의미 없음)
```python
delete_chips_for_reservation(db, reservation_id=reservation_id, force=True)
```

→ OQ-2-b 결정 그대로. row 삭제 시 모든 데이터 cascade — 의도된 동작.

---

## 3. 발견된 이슈 — `on_status_cancelled` 의 force=True 가 sent 칩까지 삭제

### 현재 코드 동작 (Before)
- `sent_at IS NULL` 가드 — 발송 완료 칩은 보존
- 즉 sent 기록은 cancel 후에도 유지 (이력)

### chip_store.delete_chips_for_reservation(force=True) 동작
- 모든 가드 우회 — sent 칩도 삭제됨

### 영향 분석
- 운영 관점: 취소된 예약의 "이미 발송한 SMS" 이력이 사라짐. 사고 재현 / 운영자 확인 어려워짐.
- 사용자 OQ-2-a 결정 의도: "manual/excluded 도 cascade" (제재 강화). **sent 이력까지 삭제는 의도 외**.

### 해결 방안

A. chip_store API 보강 — `force_unsent_only` 또는 `protect_sent` 같은 새 플래그 추가
B. on_status_cancelled 에서 chip_store 우회 직접 처리 (force 의 정의에 맞지 않음)
C. 현재 force=True 유지 (sent 이력 손실 감수)

→ A 가 정합. PR9 에서 chip_store API 확장.
