# 단계 #9~#10 사전조사 — `party3_mms.py` + `room_upgrade_common.py` 이주

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #9~#10
> 분류: 🔵 의도된 변화 — OQ-1 fix 발효 (party3/upgrade reconcile 에서 manual/excluded/failed 보호)
> 변경 규모:
>   - party3_mms.py — 2 함수 내 INSERT/DELETE 4건 chip_store 위임
>   - room_upgrade_common.py — 3 helper (ensure_chip / remove_chip / delete_all_chips) chip_store 위임 + prefix diag 보존

---

## 1. 목적

PR4/PR5 와 동일 사상으로 party3/room_upgrade 패밀리의 직접 CRUD 를 chip_store 위임으로 교체.
**prefix diag 이벤트는 보존** — `{prefix}.chip_applied/chip_deleted/all_deleted` 가 정답지에 등장하므로 backward compat 위해 유지.

---

## 2. 변경 대상 코드

### 2-1. `party3_mms.py`

**4 변경 지점**:
| 라인 | 패턴 | After |
|------|------|-------|
| 110~124 (reconcile bulk INSERT) | for rid in (target_ids - existing_ids): SAVEPOINT INSERT | chip_store.ensure_chip per id |
| 128~136 (reconcile bulk DELETE) | for chip in existing_chips: 3-조건 → db.delete | chip_store.remove_chip per chip |
| 196~215 (single INSERT) | SAVEPOINT INSERT | chip_store.ensure_chip + 동일 diag |
| 220~225 (single DELETE) | db.delete | chip_store.remove_chip + 동일 diag |

prefix diag (`party3_mms.chip_insert_race`, `party3_mms.single.created`, `party3_mms.single.deleted`) 는 보존 (정답지 영향 회피).

### 2-2. `room_upgrade_common.py`

**3 helper 함수 내 INSERT/DELETE**:
| 함수 | 변경 |
|------|------|
| `ensure_chip` (165~219) | SAVEPOINT INSERT → chip_store.ensure_chip + 동일 `{prefix}.chip_applied` diag |
| `remove_chip` (221~248) | db.delete → chip_store.remove_chip + 동일 `{prefix}.chip_deleted` diag |
| `delete_all_chips` (251~287) | bulk delete → chip_store.delete_chips_for_reservation + 동일 `{prefix}.all_deleted` diag |

caller (room_upgrade_promise/review) 변경 0 — 시그니처 보존.

---

## 3. 동작 동등성 근거

### 3-1. INSERT 동등성

| 단계 | Before (직접 INSERT) | After (chip_store.ensure_chip) | 동등 |
|------|---------------------|-------------------------------|------|
| existing 칩 조회 매칭 키 | (res, date, template_key) | 동일 | ✅ |
| existing 있을 때 | return (party3 변형: chip_applied diag 안 emit) | return existing | ✅ |
| race 처리 | SAVEPOINT + IntegrityError catch | 동일 | ✅ |
| race 후 동작 | warn diag + 함수 종료 | warn diag + 재조회 후 반환 | ✅ |
| tenant_id | `get_session_tenant_id(db)` | 동일 (chip_store 내부) | ✅ |

### 3-2. DELETE 동등성 + 🔵 OQ-1 fix

| 단계 | Before | After |
|------|--------|-------|
| 매칭 키 | schedule_id == X | 동일 (chip_store schedule_id 분기) |
| sent_at 가드 | IS NULL | 동일 |
| **manual/excluded/failed 가드** | **없음** | **PROTECTED_ASSIGNED_BY 추가** (OQ-1) |
| DELETE 방식 | db.delete(chip) | query.delete(synchronize_session='fetch') |

→ OQ-1 fix 발효: party3/upgrade reconcile 사이클에서 운영자 manual 칩 보호.

### 3-3. diag 이벤트 보존

prefix diag 가 정답지에 등장하는지 grep 확인:

```
grep -rn "party3_mms.chip_insert_race\|party3_mms.single\|room_upgrade.*chip_applied\|room_upgrade.*chip_deleted\|room_upgrade.*all_deleted" docs/diag-golden/
```

결과 (사전 확인): `_draft/chip-reconcile-party3-mms.yaml` 등에 등장. **보존 필수**.

→ 이주 후에도 동일 키 emit. chip_store 의 verbose 이벤트는 부가로 발화 (정답지 영향 없음).

---

## 4. 시나리오별 결과

| 시나리오 | Before | After | 판정 |
|---------|--------|-------|------|
| party3 reconcile — 신규 대상 | INSERT + chip_applied (party3 변형: 없음) | 동일 (chip_store.ensure.created 추가 emit) | ✅ |
| party3 reconcile — 대상 제외 | DELETE + (없음) | 동일 + chip_store.remove emit | ✅ |
| party3 reconcile — manual 칩 + 제외 대상 | manual 칩 silent 삭제 | manual 보호 (OQ-1) | 🔵 fix |
| room_upgrade reconcile — 신규 적용 | chip_applied | 동일 | ✅ |
| room_upgrade reconcile — 만족 종료 | chip_deleted | 동일 | ✅ |
| room_upgrade — 배정 해제 (delete_all) | all_deleted | 동일 + OQ-1 보호 | 🔵 fix |

---

## 5. 영향받지 않음을 확인할 코드 경로

- party3_mms.py 의 reconcile 로직 (필터링, daily_party_map 계산 등) — 변경 0
- room_upgrade_common.py 의 `decide_upgrade_eligible`, `find_single_schedule` 등 — 변경 0
- room_upgrade_promise.py / room_upgrade_review.py — 변경 0 (caller 시그니처 보존)
- 외부 caller (`custom_schedule_registry`, `reconcile.py`) — 변경 0

---

## 6. 검증 체크리스트

- [ ] py_compile (party3_mms, room_upgrade_common) PASS
- [ ] 직접 CRUD 0건 (db.add(RSA) / db.query(RSA).delete) — 두 파일
- [ ] prefix diag 이벤트 유지 — `party3_mms.single.created`, `room_upgrade_promise.chip_applied` 등
- [ ] chip_store 단위테스트 42/42 PASS
- [ ] caller (room_upgrade_promise/review) 시그니처 변경 0

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 정상 reconcile 회귀 | **없음** (행위 동등) |
| manual/excluded/failed 칩 보호 | **🟢 강화** (OQ-1 fix) |
| prefix diag 정답지 | **보존** (이벤트 키 그대로) |
| race 처리 | **동등** (SAVEPOINT 패턴) |
| chip_store verbose 이벤트 중복 | 정답지 영향 없음 (verbose) |
| Supabase 호환 | 영향 없음 |

**판정**: 🔵 OQ-1 fix + ⚪ 리팩토링. 정답지 호환 — backward compat 보장.
