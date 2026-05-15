# 단계 #11 사전조사 — `chip_reconciler.py` 이주

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #11
> 분류: ⚪ 리팩토링 — 행위 동등 (사전 chip_store 가드 강화로 호환성 확보)
> 변경 규모: chip_reconciler.py 의 3 변경 지점 + chip_store.py 가드 강화

---

## 1. 목적

`reconcile_chips_for_reservation` + `_sync_chips` + `_sync_chips_for_schedule` 의
직접 CRUD 를 chip_store 위임으로 교체. 행위 동등 보장을 위해 chip_store 가드에
`send_status != 'failed'` 추가 (옛 데이터 호환).

---

## 2. 변경 대상 코드

### 2-1. ⭐ chip_store 가드 강화 (선행 변경)

`chip_store.py` 의 force=False 가드에 추가:

**Before**:
```python
if not force:
    q = q.filter(
        ReservationSmsAssignment.sent_at.is_(None),
        ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
    )
```

**After**:
```python
if not force:
    q = q.filter(
        ReservationSmsAssignment.sent_at.is_(None),
        ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
        # 옛 데이터 호환 — assigned_by='auto' + send_status='failed' 케이스
        (ReservationSmsAssignment.send_status.is_(None))
        | (ReservationSmsAssignment.send_status != 'failed'),
    )
```

**근거**: chip_reconciler 가 기존에 사용하던 가드 (`a.send_status != 'failed'`)
와 정합. PR4 OQ-5 fix 이전 데이터 (assigned_by='auto' + send_status='failed')
보호. PR5/PR6 의 동작도 자동 강화 — 회귀 0 (더 엄격해질 뿐).

신규 단위 테스트 1건 추가:
- `test_protects_legacy_failed_send_status` — 옛 데이터 보호 검증

### 2-2. chip_reconciler.py 변경 지점 (3건)

#### A. line 76~88 (cancelled 예약 cleanup)
**Before**: `db.query(...).filter(... ~assigned_by.in_(_PROTECTED_ASSIGNED_BY)).all()` + 반복 `db.delete`
**After**: `chip_store.delete_chips_for_reservation(reservation_id, force=False)`

#### B. line 295~325 (_sync_chips INSERT + DELETE)
**Before**: SAVEPOINT INSERT loop + race diag + 반복 db.delete
**After**: `chip_store.ensure_chip` per (key, d) + `chip_store.remove_chip` per stale
- `chip.race_save_point_triggered` diag → `chip_store.ensure.race` (chip_store 내부)

#### C. line 365~388 (_sync_chips_for_schedule INSERT + DELETE)
**Before**: pre-check + db.add + 반복 db.delete
**After**: `chip_store.ensure_chip` per (res_id, d) + `chip_store.remove_chip` per stale
- pre-check 는 chip_store.ensure_chip 내부 idempotent 가 흡수

---

## 3. 동작 동등성 근거

### 3-1. 가드 비교 (chip_reconciler vs chip_store 강화 후)

| 가드 항목 | chip_reconciler (기존) | chip_store (PR7 강화 후) | 동등 |
|----------|----------------------|------------------------|------|
| sent_at IS NULL | ✓ | ✓ | ✅ |
| manual / excluded 보호 | ✓ | ✓ + failed 추가 | 🟢 더 엄격 |
| send_status != 'failed' | ✓ | ✓ (강화 추가) | ✅ |

→ chip_store 가드가 chip_reconciler 가드를 **포함**. 회귀 0.

### 3-2. SAVEPOINT race 처리

| 위치 | 기존 | chip_store |
|------|------|----------|
| _sync_chips INSERT | `db.begin_nested()` + IntegrityError catch + `chip.race_save_point_triggered` critical | `db.begin_nested()` + `chip_store.ensure.race` warn + 재조회 |
| _sync_chips_for_schedule INSERT | pre-check + db.add (race 시 transaction abort) | `db.begin_nested()` + idempotent | 🟢 더 안전 |

`chip.race_save_point_triggered` critical diag 는 정답지에 있을 수 있음 — 별도 확인 필요.

---

## 4. 시나리오별 결과

| 시나리오 | Before | After |
|---------|--------|-------|
| reconcile cancelled — 미발송 칩 cleanup | manual/excluded 보호 | 동일 + failed 보호 (OQ-5 정합) |
| _sync_chips — 새 칩 INSERT (정상) | SAVEPOINT + race diag | idempotent (chip_store 흡수) |
| _sync_chips — stale 삭제 | manual + excluded + failed_status 보호 | 동일 (chip_store 강화 가드) |
| _sync_chips_for_schedule — 새 칩 | pre-check + add | idempotent |
| 옛 데이터 (assigned_by='auto', send_status='failed') 만남 | 보호 (기존 가드) | 보호 (강화 가드) |

---

## 5. 영향받지 않음을 확인할 코드 경로

- chip_reconciler.py 의 `reconcile_chips_for_schedule` 의 schedule 매칭 로직 — 변경 0
- `_reservation_matches_schedule` / `_get_candidate_reservations` — 변경 0
- caller (`reconcile.py`, `room_assignment.py`, 외) — 변경 0

---

## 6. 검증 체크리스트

- [ ] py_compile (chip_reconciler.py, chip_store.py) PASS
- [ ] 직접 CRUD 0건 (chip_reconciler.py)
- [ ] chip_store 단위테스트 PASS (42 → 43 with 신규 legacy 보호 케이스)
- [ ] _PROTECTED_ASSIGNED_BY 상수 미사용 시 제거
- [ ] caller 시그니처 변경 0

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 정상 reconcile 동작 | **없음** (행위 동등) |
| 옛 failed 칩 silent 삭제 | **🟢 해결** (chip_store 가드 강화) |
| race 처리 동등 | **있음** (chip_store SAVEPOINT) |
| chip.race_save_point_triggered diag | **🟡 키 변경** (정답지 확인 필요) |
| PR5/PR6 호환 | **🟢 자동 강화** (회귀 0) |

**판정**: ⚪ 리팩토링 — chip_store 가드 강화로 정확한 행위 동등 보장.
