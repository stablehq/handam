# 단계 #12 사전조사 — `reservations_sms.py` 이주

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #12
> 분류: ⚪ 리팩토링 — 행위 동등
> 변경 규모: 2 INSERT 지점 chip_store 위임 (운영자 UX 보존)

---

## 1. 목적

운영자가 화면에서 SMS 칩을 토글하는 API 의 직접 INSERT 2건을 chip_store.ensure_chip 으로 교체. SELECT/UPDATE 는 그대로 (UPDATE 는 chip_store 범위 외).

---

## 2. 변경 대상 코드

### 2-1. `assign_sms_template` (line 52~60)
**Before**: 직접 INSERT
**After**: `chip_store.ensure_chip` (duplicate detection 은 line 39~50 의 기존 SELECT + 409 분기로 유지)

### 2-2. `toggle_sms_sent` upsert path (line 116~124)
**Before**: 직접 INSERT with assigned_by='manual'
**After**: chip_store.ensure_chip(assigned_by='manual')

### 2-3. 변경 안 함
- `unassign_sms_template` (line 72~89): assigned_by → 'excluded' UPDATE — 삭제 아님, chip_store 범위 외
- `toggle_sms_sent` 의 sent_at toggle (직접 setattr): 칩 상태 변경, UPDATE 패턴 — chip_store 범위 외
- `send_sms_by_tag`: send_single_sms 위임 (이미 chip_store 사용)

---

## 3. 동작 동등성

| 시나리오 | Before | After |
|---------|--------|-------|
| assign — 새 칩 | INSERT 성공 | ensure_chip 신규 생성 |
| assign — 중복 | 409 raise | 기존 SELECT 가드로 동일 (ensure_chip 전에 409 raise) |
| toggle — 칩 없음 → 토글 | INSERT manual + sent_at update | ensure_chip(manual) + setattr |
| toggle — 칩 있음 → 토글 | setattr | 동일 (변경 없음) |

---

## 4. 영향받지 않음

- unassign_sms_template — UPDATE only
- sent_at toggle — UPDATE only
- send_sms_by_tag — sms_sender 위임

---

## 5. 검증

- [x] 직접 INSERT 0건
- [x] py_compile PASS
- [x] chip_store 단위테스트 43/43 PASS

---

## 6. 회귀 위험

| 위험 | 평가 |
|---|---|
| 운영자 토글 UX | **없음** (행위 동등) |
| 409 duplicate detection | **보존** |
| excluded UPDATE | **그대로** |
| chip_store 가드 | force 사용 안 함 — UX 그대로 |
