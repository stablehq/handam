# 단계 #4~#5 사전조사 — `delete_chips_for_reservation` + `delete_chips_for_schedule`

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #4~#5
> 분류: ⚪ 인프라 — caller 0 (호출처 없음). 동작 변화 0.
> 변경 규모: `app/services/chip_store.py` 스켈레톤 2 함수 → 실구현 (+ 단위 테스트)

---

## 1. 목적

PR1 의 단건 `remove_chip` 으로 못 다루는 **범위 삭제** 시나리오를 처리할 2 함수 구현. 후속 caller 이주 (PR4~PR10) 에서 13곳 DELETE 패턴 중 약 8곳을 흡수.

| 함수 | 용도 | 흡수할 패턴 |
|---|---|---|
| `delete_chips_for_reservation` | 예약 단위 범위 삭제 (옵션 dates/template_keys/schedule_ids) | surcharge:257, room_upgrade_common:275, reservation_lifecycle:184/247, reservations_stay:367 |
| `delete_chips_for_schedule` | 스케줄 ID 일괄 삭제 | template_schedules:518 |

---

## 2. 변경 대상 코드

### 2-1. `app/services/chip_store.py` — 스켈레톤 → 실구현

#### `delete_chips_for_reservation`

**Before** (PR1 직후 — line 194~213):

```python
def delete_chips_for_reservation(
    db, *, reservation_id, dates=None, template_keys=None,
    schedule_ids=None, force=False,
) -> int:
    """범위 삭제 — 예약 단위. PR2 (#4) 에서 구현. ..."""
    raise NotImplementedError("PR2 (#4) 에서 구현")
```

**After** (~30 lines):

```python
def delete_chips_for_reservation(
    db: 'Session', *,
    reservation_id: int,
    dates: Optional[list[str]] = None,
    template_keys: Optional[list[str]] = None,
    schedule_ids: Optional[list[int]] = None,
    force: bool = False,
) -> int:
    """범위 삭제 — 예약 단위 + 옵션 필터 AND 매칭.

    조합:
      - 옵션 전부 None: 해당 예약의 모든 칩 (cascade)
      - dates 만: 해당 날짜의 칩만
      - template_keys 만: 해당 템플릿의 칩만
      - schedule_ids 만: 해당 스케줄의 칩만
      - 다중 조합: AND 매칭
    """
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
    )
    if dates:
        q = q.filter(ReservationSmsAssignment.date.in_(dates))
    if template_keys:
        q = q.filter(ReservationSmsAssignment.template_key.in_(template_keys))
    if schedule_ids:
        q = q.filter(ReservationSmsAssignment.schedule_id.in_(schedule_ids))
    if not force:
        q = q.filter(
            ReservationSmsAssignment.sent_at.is_(None),
            ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
        )
    deleted = q.delete(synchronize_session='fetch')
    if deleted:
        diag(
            "chip_store.delete_reservation.deleted",
            level="verbose",
            res_id=reservation_id,
            dates_count=len(dates) if dates else None,
            template_keys_count=len(template_keys) if template_keys else None,
            schedule_ids_count=len(schedule_ids) if schedule_ids else None,
            force=force,
            count=deleted,
        )
    return deleted
```

#### `delete_chips_for_schedule`

**Before** (PR1 직후 — line 216~223):

```python
def delete_chips_for_schedule(db, *, schedule_id, force=False) -> int:
    """스케줄 단위 삭제. PR2 (#5) 에서 구현."""
    raise NotImplementedError("PR2 (#5) 에서 구현")
```

**After** (~20 lines):

```python
def delete_chips_for_schedule(
    db: 'Session', *,
    schedule_id: int,
    force: bool = False,
) -> int:
    """스케줄 단위 일괄 삭제 (template_schedule 비활성 / 삭제 시).

    tenant_id 는 ContextVar 가 자동 필터 (cross-tenant 우회는 caller 책임).
    """
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.schedule_id == schedule_id,
    )
    if not force:
        q = q.filter(
            ReservationSmsAssignment.sent_at.is_(None),
            ~ReservationSmsAssignment.assigned_by.in_(PROTECTED_ASSIGNED_BY),
        )
    deleted = q.delete(synchronize_session='fetch')
    if deleted:
        diag(
            "chip_store.delete_schedule.deleted",
            level="verbose",
            schedule_id=schedule_id,
            force=force,
            count=deleted,
        )
    return deleted
```

### 2-2. `backend/tests/integration/test_chip_store.py` — 신규 테스트 클래스 2개 추가

기존 16 케이스에 ~12 케이스 추가 (총 ~28).

---

## 3. 동작 동등성 근거

본 단계는 미호출 — 기존 코드 영향 0. 후속 PR 의 이주 시점에 1:1 매핑 검증할 패턴 매트릭스만 정리.

### 3-1. `delete_chips_for_reservation` 의 흡수 대상 매핑

| 현재 코드 | 라인 | After 변환 |
|---|---|---|
| `surcharge.py:252~257`<br/>`db.query(RSA).filter(res_id, date, schedule_id.in_(s_ids), sent_at NULL).delete()` | 5 | `delete_chips_for_reservation(res_id=R, dates=[D], schedule_ids=s_ids)` |
| `room_upgrade_common.py:270~275`<br/>`db.query(RSA).filter(res_id, date, schedule_id.in_(s_ids), sent_at NULL).delete()` | 5 | 동일 |
| `reservation_lifecycle.py:179~184` (cc1/cc2 — OQ-2-a)<br/>`db.query(RSA).filter(tid, res_id, sent_at NULL).delete()` | 6 | `delete_chips_for_reservation(res_id=R, force=True)` ← OQ-2-a 결정 (force=True 로 정책 변경) |
| `reservation_lifecycle.py:245~247` (on_reservation_deleted — OQ-2-b)<br/>`db.query(RSA).filter(tid, res_id).delete()` | 3 | `delete_chips_for_reservation(res_id=R, force=True)` |
| `reservations_stay.py:367` (reduce_extension dates 정리)<br/>`db.query(RSA).filter(res_id, date.in_(removed)).delete()` | 1 | `delete_chips_for_reservation(res_id=R, dates=removed_dates)` |

⚠️ 주의: `reservation_lifecycle:184` 의 현재 동작은 `sent_at NULL` 만 가드 → manual 칩 silent 삭제 위험. OQ-2-a 결정 (force=True) 으로 정책 변경. **본 단계는 미호출이므로 행위 변화 0, 후속 PR9 에서 정책 변경 발효**.

### 3-2. `delete_chips_for_schedule` 의 흡수 대상 매핑

| 현재 코드 | 라인 | After 변환 |
|---|---|---|
| `template_schedules.py:514~518`<br/>`db.query(RSA).filter(schedule_id == X, sent_at NULL, ~assigned_by.in_(['manual','excluded'])).delete()` | 5 | `delete_chips_for_schedule(schedule_id=X)` ✅ 정확히 매핑 |

📌 `templates.py:347~351` 는 `template_key` 기준이라 `delete_chips_for_schedule` 으로 못 흡수 — 추후 별도 함수 또는 inline 유지. PR2 범위 외.

### 3-3. PR1 (`ensure_chip`/`remove_chip`) 와 일관성

| 패턴 | PR1 | PR2 |
|---|---|---|
| 시그니처 | keyword-only, force 인자 | 동일 |
| 보호 가드 (force=False) | sent_at + assigned_by NOT IN PROTECTED_ASSIGNED_BY | 동일 |
| force=True 동작 | 가드 우회 전부 삭제 | 동일 |
| diag emit | `chip_store.<op>.deleted` (verbose, count) | 동일 (`delete_reservation` / `delete_schedule`) |
| tenant_id | ContextVar 자동 필터 | 동일 |

---

## 4. 시나리오별 결과 (단위 테스트)

`delete_chips_for_reservation`:

| 시나리오 | 인자 | 결과 |
|---|---|---|
| 옵션 전부 None — 예약 모든 칩 정리 | `(res_id=R)` | force=False 면 manual 보호, force=True 면 cascade |
| dates 만 | `(res_id=R, dates=[D1, D2])` | D1/D2 칩만 매칭 |
| schedule_ids 만 | `(res_id=R, schedule_ids=[s1])` | s1 칩만 매칭 |
| dates + schedule_ids AND | `(res_id=R, dates=[D], schedule_ids=[s1])` | 교집합 |
| 빈 dates 리스트 | `(res_id=R, dates=[])` | dates 필터 미적용 (옵션 None 과 동일) |
| force=False + manual 칩 | manual 보호 | ⭐ OQ-1 |
| force=True + manual 칩 | 삭제 | ⭐ OQ-2 |
| 존재하지 않는 res_id | `(res_id=99999)` | 0 |

`delete_chips_for_schedule`:

| 시나리오 | 인자 | 결과 |
|---|---|---|
| 스케줄에 칩 N 개 | `(schedule_id=s)` | N 칩 모두 force=False 적용 |
| force=False + manual 일부 | manual 보호 | |
| force=True | 모두 삭제 | |
| 존재하지 않는 schedule_id | `(schedule_id=99999)` | 0 |

---

## 5. 영향받지 않음을 확인할 코드 경로

- 모든 caller (17 파일) — 변경 0 (PR2 미호출)
- PR1 의 `ensure_chip` / `remove_chip` — 변경 0
- PR1 의 스켈레톤 `record_sent` / `record_failed` — 변경 0 (PR3 에서 구현)
- 기존 DB 스키마 — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `python -m py_compile app/services/chip_store.py` 통과
- [ ] **import**: 모든 함수 import 성공
- [ ] **단위 테스트**: PR1 16 케이스 + PR2 추가 케이스 모두 PASS
- [ ] **외부 참조**: `grep -rn "delete_chips_for_reservation\|delete_chips_for_schedule" app/` → 정의 1건씩 (caller 0)
- [ ] **diag-golden 영향**: 0 (신규 이벤트 `chip_store.delete_*.deleted` 아직 발화 0)
- [ ] **회귀 비교**: 기존 테스트 영향 0

---

## 7. 본 단계 이후의 후속 의존성

- **#6 (PR3)**: `record_sent` / `record_failed` 구현 (sms_tracking 패턴 일반화)
- **#7 (PR4)**: `sms_tracking.record_sms_sent/failed` 이주 — record_sent/failed 호출
- **#8 (PR5)**: `surcharge.py` 의 `_delete_all_surcharge_chips` 이주 — `delete_chips_for_reservation(dates=[date], schedule_ids=surcharge_s_ids)` 로
- **#9 (PR6)**: `party3_mms.py` + `room_upgrade_common.py` (자체 helpers) 이주
- **#13 (PR9)**: `reservation_lifecycle.py` — `on_status_cancelled` / `on_reservation_deleted` → `delete_chips_for_reservation(force=True)` ← OQ-2 결정 발효
- **#14 (PR10)**: `template_schedules.py:518` → `delete_chips_for_schedule`

---

## 8. 머지 후 다음 액션

`chip-store-step-06-record-sent-failed.md` 작성 (PR3) — `sms_tracking` 의 INSERT-or-update 패턴 일반화.

---

## 9. 회귀 위험 평가

| 위험 카테고리 | 평가 | 근거 |
|---|---|---|
| 기존 기능 회귀 | **없음** | caller 0 |
| 데이터 무결성 | **없음** | DB 스키마 변경 0 |
| 성능 영향 | **없음** | 호출 0 |
| 보안 영향 | **없음** | tenant_id 자동 필터 (PR1 와 동일 패턴) |
| diag-golden 회귀 | **없음** | 신규 verbose 이벤트, 아직 발화 0 |

**판정**: ⚪ 인프라 단계, 회귀 위험 0.
