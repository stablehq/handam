# PR1 사전조사 — `reservations_stay.py` link/unlink_stay_group 이주

> 부모 계획: [sync-sms-tags-consolidation-plan.md](./sync-sms-tags-consolidation-plan.md) §6 PR1
> 분류: 🔵 의도된 변화 — 4종 칩 누락 해결 (surcharge/party3/upgrade_promise/_review)
> 변경 규모: 2 호출처 + schedules pre-query 제거

---

## 1. 목적

`link_stay_group` 과 `unlink_stay_group` 후처리에서 1종 칩만 reconcile 하던
패턴을 5종 통합 reconcile 로 교체. 연박 그룹 변경으로 인한 surcharge/party3/
upgrade 칩 stale 회귀 위험 해결.

---

## 2. 변경 대상 코드

### 2-1. `link_stay_group` (line 99~101)

**Before**:
```python
from app.services.room_assignment import sync_sms_tags
schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
for res_id in linked_ids:
    sync_sms_tags(db, res_id, schedules=schedules)
```

**After**:
```python
from app.services.reconcile import reconcile_all_chips
for res_id in linked_ids:
    reconcile_all_chips(db, res_id)
```

**변경 내용**:
- `sync_sms_tags` (1종) → `reconcile_all_chips` (5종)
- `schedules` pre-query 제거 — reconcile_all_chips 가 내부 처리
- dates 인자 미지정 → 각 res 의 stay 전체 (check_in~check_out)

### 2-2. `unlink_stay_group` (line 139~141)

동일 패턴:
**Before**:
```python
schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
for res_id in affected_ids:
    sync_sms_tags(db, res_id, schedules=schedules)
```

**After**:
```python
from app.services.reconcile import reconcile_all_chips
for res_id in affected_ids:
    reconcile_all_chips(db, res_id)
```

---

## 3. 동작 동등성 근거

### 3-1. 기본 칩 (sync_sms_tags) 동작은 변화 0

`reconcile_all_chips` 의 1번째 단계가 `sync_sms_tags` 호출 (reconcile.py:62).
→ 기존 호출과 동일 효과.

| 단계 | Before | After |
|------|--------|-------|
| 기본 SMS 칩 reconcile | sync_sms_tags 직접 호출 | reconcile_all_chips 내부 호출 |
| 처리 res | linked_ids/affected_ids 순회 | 동일 |
| schedules 인자 | pre-query 후 전달 | reconcile_all_chips 내부에서 자체 query (sync_sms_tags 가 None 받음 → 자체 가져옴) |

### 3-2. 🔵 4종 칩 추가 reconcile (의도된 변화)

reconcile_all_chips 가 각 stay 날짜에 대해 추가 실행:
| 추가 처리 | 호출 함수 | 영향 |
|---------|---------|------|
| 추가요금 | `reconcile_surcharge(db, res_id, date, room_id=None)` | 연박 그룹 변경으로 정원/요금 변동 가능 → 정대 |
| 파티3 MMS | `reconcile_party3_mms_for_reservation(db, res_id, date)` | party_type 영향 없으나 보호적 reconcile |
| 객실업그레이드 약속 | `reconcile_room_upgrade_promise(db, res_id, date)` | 객실 등급 영향 없음, 보호적 |
| 객실업그레이드 후기 | `reconcile_room_upgrade_review(db, res_id, date)` | 동일 |

surcharge 가 가장 영향 큼 — 연박 그룹 묶이면 booking_count 합산 변동으로 추가요금 칩 생성/삭제 가능성.

### 3-3. 성능 영향

링크 사례 (예: 2박 + 2박 → 4박 묶음):
- 기존: 2 res × 1종 = 2 호출
- 신규: 2 res × 5종 칩 × 2~4 stay 날짜 = ~16~40 reconcile 호출

호출 빈도: 운영자 수동 (하루 0~수회). 절대 부담 작음.

### 3-4. diag 이벤트 변화

| 이벤트 | Before | After |
|--------|--------|-------|
| `reconcile_chips_for_reservation.enter/exit` | ✓ (per res) | ✓ (per res, sync_sms_tags 가 호출) |
| `reconcile_all_chips.enter/exit` | ✗ | ✓ (per res) — 신규 emit |
| `surcharge.reconcile.enter/exit` | ✗ | ✓ (per res × date) — 신규 emit |
| `party3_mms.single.created/deleted` | ✗ | 가능 (party3 변동 시) |
| `room_upgrade_*` | ✗ | 가능 |

### 3-5. 정답지 영향 (1건)

**`docs/diag-golden/actions/_draft/ctx-menu-stay-group-unlink.yaml`**:
- 현재 MANDATORY: `reconcile_chips_for_reservation.enter/exit` (per res) — **여전히 emit 됨** (sync_sms_tags 가 reconcile_all_chips 내부 호출)
- 신규 MANDATORY 후보: `reconcile_all_chips.enter/exit` (per res)
- 신규 VARIABLE_COUNT 후보: `surcharge.*`, `party3_mms.*`, `room_upgrade_*` (발화 빈도 가변)

→ **정답지 갱신 필요**. 단 기존 MANDATORY 가 사라지지 않으므로 강한 회귀는 아님.

조치:
- 본 PR 머지 후 정답지 보강 (별도 작업 또는 본 PR 에 포함)
- state.json pending 등록 또는 yaml 직접 수정

---

## 4. 시나리오별 결과

| 시나리오 | Before | After |
|---------|--------|-------|
| 운영자가 2박 res + 2박 res 묶기 (link) | 1종 칩만 reconcile → surcharge 합산 미반영 | 5종 모두 reconcile → 추가요금 칩 정대 |
| 운영자가 묶음 해제 (unlink) | 동일 회귀 | 동일 해결 |
| 묶음 후 surcharge 0건 (정원초과 없음) | 기존 surcharge 칩 stale (정원초과 사라졌는데 칩 유지) | 정대로 chip_store.remove_chip → 정리 |
| 묶음 해제 후 surcharge 발생 | 칩 생성 안 됨 | 정대로 ensure_chip → 생성 |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `consecutive_stay.link_reservations` / `unlink_from_group` — 변경 0
- `link_stay_group` / `unlink_stay_group` 의 그 외 로직 (validation, exception, log) — 변경 0
- `room_assignment.sync_sms_tags` 함수 자체 — 변경 0 (다른 caller 가 계속 사용)
- 다른 reconcile 진입점 — 변경 0

---

## 6. 검증 체크리스트

- [ ] syntax: py_compile (reservations_stay.py)
- [ ] sync_sms_tags 호출 0건: `grep "sync_sms_tags" backend/app/api/reservations_stay.py` → 0
- [ ] schedules pre-query 제거 — 미사용 import 가 남는지 확인
- [ ] chip_store 단위테스트 46/46 PASS (회귀 0)
- [ ] 정답지 갱신: `_draft/ctx-menu-stay-group-unlink.yaml` — `reconcile_all_chips.*` 추가

---

## 7. 본 단계 이후의 후속 의존성

- PR2 (`reservations.py:370` peer unlink)
- PR3 (`reservations_room.py:69` 수동 unassign)
- PR4 (`naver_sync.py` 2건)

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 기본 SMS 칩 reconcile 회귀 | **없음** (sync_sms_tags 가 reconcile_all_chips 내부 호출) |
| 4종 칩 회귀 | **🟢 해결** (의도된 정대) |
| 성능 부담 | **작음** (운영자 수동 빈도) |
| diag-golden | **🟡 정답지 1건 갱신** (이벤트 추가 — MANDATORY 사라지지 않음) |
| 트랜잭션 무결성 | **없음** (동일 db 세션) |
| 테넌트 격리 | **없음** (chip_store 보존 패턴) |

**판정**: 🔵 의도된 fix + ⚪ 정답지 갱신. 회귀 위험 작음.
