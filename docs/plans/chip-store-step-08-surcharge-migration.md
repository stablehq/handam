# 단계 #8 사전조사 — `surcharge.py` 이주

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #8
> 분류: 🔵 의도된 변화 — OQ-1 fix 발효 (surcharge reconcile 에서 manual/excluded/failed 보호)
> 변경 규모: 3 helper 함수 (`_ensure_chip`, `_remove_chip`, `_delete_all_surcharge_chips`) 의 직접 CRUD 제거 → chip_store 위임

---

## 1. 목적

surcharge.py 의 칩 직접 조작 (INSERT × 1, DELETE × 2) 을 chip_store 위임으로 교체.
**helper 함수명/시그니처 유지** — 외부 caller (surcharge 내부 7건 + room_assignment 3건) 코드 변경 0.

OQ-1 silent fix 발효:
- 기존: `_delete_all_surcharge_chips` 가 `sent_at NULL` 만 가드 → manual/excluded 칩 silent 삭제
- 신규: chip_store.delete_chips_for_reservation(force=False) → PROTECTED 가드 → manual 보호

---

## 2. 변경 대상 코드

### 2-1. `_ensure_chip` (line 189~224)

**Before** — 직접 INSERT + SAVEPOINT race 처리:
```python
def _ensure_chip(db, reservation_id, date, custom_type):
    schedule = _find_schedule(db, custom_type)
    if not schedule or not schedule.template or not schedule.template.is_active:
        return
    template_key = schedule.template.template_key
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.template_key == template_key,
    ).first()
    if existing:
        return
    tenant_id = get_session_tenant_id(db)
    try:
        with db.begin_nested():
            db.add(ReservationSmsAssignment(
                reservation_id=reservation_id,
                template_key=template_key,
                date=date,
                assigned_by='auto',
                schedule_id=schedule.id,
                sent_at=None,
                tenant_id=tenant_id,
            ))
    except IntegrityError:
        diag("surcharge.chip_insert_race", level="warn", ...)
```

**After** — chip_store 위임:
```python
def _ensure_chip(db, reservation_id, date, custom_type):
    schedule = _find_schedule(db, custom_type)
    if not schedule or not schedule.template or not schedule.template.is_active:
        return
    from app.services.chip_store import ensure_chip
    ensure_chip(
        db,
        reservation_id=reservation_id,
        template_key=schedule.template.template_key,
        date=date,
        assigned_by='auto',
        schedule_id=schedule.id,
    )
```

**행위 비교**:
| 단계 | Before | After |
|------|--------|-------|
| schedule 조회 + active 가드 | 동일 | 동일 |
| existing 칩 조회 | (res, date, template_key) | 동일 (chip_store 내부에서 매칭) |
| existing 있음 → 종료 | return | return existing (caller 무시) |
| INSERT race | SAVEPOINT + IntegrityError catch | 동일 패턴 |
| race diag 키 | `surcharge.chip_insert_race` (warn) | `chip_store.ensure.race` (warn) |
| race 후 동작 | warn diag, 함수 종료 | warn diag + 재조회 후 반환 |

→ **silent 차이**: race 시 diag 키 변경. 정답지 영향 없음 (warn 레벨 + 빈도 낮음).

### 2-2. `_remove_chip` (line 227~239)

**Before** — 단건 DELETE (`db.delete(existing)`):
```python
def _remove_chip(db, reservation_id, date, custom_type):
    schedule = _find_schedule(db, custom_type)
    if not schedule:
        return
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id == schedule.id,
        ReservationSmsAssignment.sent_at.is_(None),
    ).first()
    if existing:
        db.delete(existing)
```

**After** — chip_store.remove_chip 위임:
```python
def _remove_chip(db, reservation_id, date, custom_type):
    schedule = _find_schedule(db, custom_type)
    if not schedule:
        return
    from app.services.chip_store import remove_chip
    remove_chip(
        db,
        reservation_id=reservation_id,
        template_key=schedule.template.template_key if schedule.template else "",
        date=date,
        schedule_id=schedule.id,
    )
```

**행위 비교**:
| 단계 | Before | After |
|------|--------|-------|
| schedule 조회 | 동일 | 동일 |
| 매칭 키 | (res, date, schedule_id) | 동일 (chip_store schedule_id 분기) |
| 가드 | sent_at NULL 만 | **+ PROTECTED_ASSIGNED_BY** (OQ-1 fix) |
| 삭제 방식 | `db.delete(existing)` | `query.delete(synchronize_session='fetch')` |
| 반환값 | None | int (삭제 카운트) — caller 무시 |

→ **🔵 OQ-1 silent fix**: surcharge reconcile 사이클에서 manual 가드 강화. 5/12 res=5254/5255 같은 manual 토글 케이스 영향 가능.

### 2-3. `_delete_all_surcharge_chips` (line 242~261)

**Before** — bulk DELETE (sent_at NULL 만 가드):
```python
def _delete_all_surcharge_chips(db, reservation_id, date):
    surcharge_schedule_ids = [
        s.id for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == 'custom_schedule',
            TemplateSchedule.custom_type.in_(_ALL_SURCHARGE_TYPES),
        ).all()
    ]
    if not surcharge_schedule_ids:
        return
    deleted = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.date == date,
        ReservationSmsAssignment.schedule_id.in_(surcharge_schedule_ids),
        ReservationSmsAssignment.sent_at.is_(None),
    ).delete(synchronize_session='fetch')
    if deleted:
        db.flush()
        diag("surcharge.all_deleted", level="verbose", ...)
```

**After** — chip_store.delete_chips_for_reservation 위임:
```python
def _delete_all_surcharge_chips(db, reservation_id, date):
    surcharge_schedule_ids = [
        s.id for s in db.query(TemplateSchedule.id).filter(
            TemplateSchedule.schedule_category == 'custom_schedule',
            TemplateSchedule.custom_type.in_(_ALL_SURCHARGE_TYPES),
        ).all()
    ]
    if not surcharge_schedule_ids:
        return
    from app.services.chip_store import delete_chips_for_reservation
    deleted = delete_chips_for_reservation(
        db,
        reservation_id=reservation_id,
        dates=[date],
        schedule_ids=surcharge_schedule_ids,
    )
    if deleted:
        diag("surcharge.all_deleted", level="verbose",
             res_id=reservation_id, date=date, count=deleted)
```

**행위 비교**:
| 단계 | Before | After |
|------|--------|-------|
| schedule_ids fetch | 동일 | 동일 |
| 매칭 키 | (res, date, schedule_id IN) | 동일 |
| 가드 | sent_at NULL 만 | **+ PROTECTED_ASSIGNED_BY** (OQ-1 fix) |
| diag emit (수동) | `surcharge.all_deleted` | 동일 + chip_store.delete_reservation.deleted (chip_store 내부) |
| `db.flush()` | 있음 | 없음 (chip_store 가 synchronize_session='fetch') |

→ **🔵 OQ-1 silent fix** + diag 중복 (`surcharge.all_deleted` + `chip_store.delete_reservation.deleted` 둘 다). chip_store 측 verbose 라 정답지 영향 미미.

---

## 3. 동작 동등성 근거

### 3-1. 외부 API 보존

surcharge.py 의 3 helper 함수 시그니처 변경 0:
- `_ensure_chip(db, reservation_id, date, custom_type)`
- `_remove_chip(db, reservation_id, date, custom_type)`
- `_delete_all_surcharge_chips(db, reservation_id, date)`

→ 외부 caller (room_assignment.py × 3, surcharge.py 내부 × 7) 변경 0.

### 3-2. 정상 흐름 동작 동등 (auto 칩만 있는 일반 케이스)

| 시나리오 | Before | After | 판정 |
|---------|--------|-------|------|
| reconcile_surcharge → 신규 칩 INSERT | auto 칩 INSERT | 동일 | ✅ |
| reconcile_surcharge → 기존 칩 유지 | existing return | 동일 | ✅ |
| reconcile_surcharge → 다른 type 으로 전환 (_remove + _ensure) | 'A' 칩 삭제 + 'B' 칩 INSERT | 동일 (auto 칩만 가드 통과) | ✅ |
| unassign_room → _delete_all_surcharge_chips | sent_at NULL 칩 모두 삭제 | 동일 | ✅ |

### 3-3. 🔵 OQ-1 fix 발효 — manual 칩 시나리오

| 시나리오 | Before | After | 판정 |
|---------|--------|-------|------|
| 운영자 manual surcharge 칩 + auto reconcile 트리거 | manual 칩 silent 삭제 | manual 칩 보존 | 🔵 fix |
| excluded 칩 + reconcile | silent 삭제 | 보존 | 🔵 fix |
| failed 칩 + reconcile (PR4 후) | (PR4 전엔 auto 였음) | 보존 | 🔵 fix |

### 3-4. diag 키 변화

| 위치 | Before | After |
|------|--------|-------|
| INSERT 성공 | (없음) | `chip_store.ensure.created` (verbose) — 신규 |
| INSERT race | `surcharge.chip_insert_race` (warn) | `chip_store.ensure.race` (warn) |
| DELETE 성공 | `surcharge.all_deleted` (verbose) | 동일 + `chip_store.delete_reservation.deleted` (verbose) — 중복 |

정답지 영향:
- `surcharge.chip_insert_race` — 정답지 검색 0건
- `surcharge.all_deleted` — 정답지 검색 (다음 단계에서)
- 신규 `chip_store.*` 키 — PR4 와 동일하게 첫 발화 후 정답지 작성 예정

---

## 4. 시나리오별 결과

(§3-2, §3-3, §3-4 참조)

---

## 5. 영향받지 않음을 확인할 코드 경로

- `surcharge.py:1~131` (constants + helpers + reconcile_surcharge entry) — 변경 0
- `surcharge.py:264~end` (reconcile_surcharge_batch) — 변경 0
- `room_assignment.py:443~720` (외부 caller 3건) — 변경 0
- 모든 다른 파일 — 변경 0

---

## 6. 검증 체크리스트

- [ ] py_compile (surcharge.py) PASS
- [ ] 외부 caller 시그니처 변경 0 확인 — `grep -rn "_ensure_chip\|_remove_chip\|_delete_all_surcharge_chips" app/`
- [ ] chip_store 단위테스트 42/42 PASS 유지
- [ ] 통합 테스트 (있다면) PASS
- [ ] 직접 CRUD 0건 확인: surcharge.py 에서 `db.add(ReservationSmsAssignment\|db.query(ReservationSmsAssignment).delete` grep → 0

---

## 7. 본 단계 이후의 후속 의존성

- #9 (PR6): party3_mms + room_upgrade_common 이주
- #11 (PR8): chip_reconciler 이주
- #15 (PR11): CI lint — chip_store 외부의 직접 CRUD 차단

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 정상 reconcile 회귀 | **없음** (행위 동등) |
| manual 칩 silent 삭제 | **🟢 해결** (OQ-1 fix) |
| 외부 caller | **없음** (시그니처 보존) |
| race 처리 | **동등** (SAVEPOINT 패턴 보존) |
| diag-golden | **🟡 신규 키 발화** (state.json pending 에 이미 등록됨) |
| 테넌트 격리 | **없음** (chip_store 가 명시 tenant_id) |
| Supabase 호환 | **없음** |

**판정**: 🔵 OQ-1 fix 발효 + ⚪ 리팩토링. 외부 caller 영향 0.
