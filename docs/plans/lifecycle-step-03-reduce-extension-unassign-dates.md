# 단계 #3 사전조사 — `_do_reduce_extension` 의 `db.delete(ra)` → `unassign_dates` 위임

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §B
> 분류: 🔵 **silent 버그 해결** — 누락 패턴 #3 (bed_order 재정렬) + 부수 정리 (surcharge/room_upgrade 칩 cleanup)
> 변경 규모: `app/api/reservations_stay.py` ~4 라인 치환

---

## 1. 목적

`_do_reduce_extension` 의 RoomAssignment 직접 삭제 (`db.delete(ra)`) 를 단계 #1 의 `unassign_dates` 호출로 위임. 이로써:
1. bed_order 재정렬 (`_compact_bed_orders_in_cells`) 자동 발동 — **누락 패턴 #3 해결**
2. surcharge / room_upgrade 칩 cleanup 자동 발동 — **부수 정리** (의도된 추가 효과)
3. diag 로깅 보강 (`unassign_dates.enter/compact/exit`)

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| `chips_to_check` 블록 (L380~L398, SMS 칩 직접 삭제) | 단계 #17 (lifecycle `on_dates_changed` 흡수) |
| `shift_daily_records` / `reconcile_dates` 호출 | 단계 #17 |
| `reconcile_chips_for_reservation` (구버전) 호출 | 단계 #17 |
| `manually_extended_until` set/clear | Mutator 단계 #8 결과 그대로 |

---

## 2. 변경 대상 코드

### `app/api/reservations_stay.py` L366~L378 (RA 삭제 블록)

**Before** (실측):

```python
    # 1. Delete room assignments for removed dates
    ra_deleted = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date.in_(dates_to_remove),
            RoomAssignment.tenant_id == tid,
        )
        .all()
    )
    room_assignments_deleted = len(ra_deleted)
    for ra in ra_deleted:
        db.delete(ra)
```

**After**:

```python
    # 1. Delete room assignments for removed dates (lifecycle 단계 #3)
    from app.services.room_assignment import unassign_dates
    room_assignments_deleted = unassign_dates(db, reservation_id, dates_to_remove)
```

**변경 내용**:
- L367~L375 `ra_deleted = (db.query(...).all())` 블록 (9 라인) 제거
- L376 `room_assignments_deleted = len(ra_deleted)` 제거
- L377~L378 `for ra in ra_deleted: db.delete(ra)` 제거
- 대체: lazy import + `unassign_dates` 호출 1 라인 (값 반환 = 삭제 개수)
- 주석 갱신: "lifecycle 단계 #3"

총 11 라인 제거 + 2 라인 추가 = **-9 라인**.

### 2-1. 라인 단위 정당화 — "지워지는 코드가 어디서 대신 수행되나"

| 지워지는 라인 | 역할 | 대체 위치 |
|---|---|---|
| `ra_deleted = (db.query(RA).filter(...).all())` | 삭제 대상 캡처 | `unassign_dates` 내부 `old_assignments = query.all()` (단계 #1 §2-1) |
| `room_assignments_deleted = len(ra_deleted)` | 삭제 개수 통계 | `unassign_dates` 의 반환값 `count` (단계 #1 §2-1) |
| `for ra in ra_deleted: db.delete(ra)` | 실제 삭제 | `unassign_dates` 내부 `count = query.delete(synchronize_session="fetch")` (단계 #1 §2-1) |

→ 모든 책임이 `unassign_dates` 내부에서 동등하게 수행됨.

### 2-2. 추가로 발동되는 동작 (의도된 누락 해결)

| 신규 동작 | 위치 | 효과 |
|---|---|---|
| `_compact_bed_orders_in_cells(db, affected_cells)` | `unassign_dates` 내부 (단계 #1 §2-1) | 도미토리 셀의 bed_order 갭 재정렬 — **누락 패턴 #3 해결** |
| `_delete_all_surcharge_chips(db, reservation_id, d)` 매 날짜 | 동일 | reduce 된 날짜의 미발송 surcharge 칩 정리 |
| `_delete_all_room_upgrade_promise/_review_chips` | 동일 | 동일 |

---

## 3. 동작 동등성 / 의도된 변화

### 3-1. RA 삭제 결과

| 입력 | Before | After | 동등 |
|---|---|---|---|
| `dates_to_remove = ["2026-05-15"]` 인 reservation | 1개 RA 삭제, 삭제 개수 1 반환 | 1개 RA 삭제, 삭제 개수 1 반환 | ✅ |
| `dates_to_remove = ["2026-05-15", "2026-05-16"]` | 2개 삭제, count=2 | 2개 삭제, count=2 | ✅ |
| 빈 `dates_to_remove` | 0 삭제 (for 루프 진입 안 함), count=0 | 0 삭제 (`unassign_dates` 의 `if not dates: return 0`), count=0 | ✅ |
| dates_to_remove 의 RA 가 도미토리 같은 셀에 다른 점유자와 있는 경우 | bed_order 재정렬 ❌ — 갭 남음 | bed_order 재정렬 ✅ — 갭 메움 | 🔵 누락 해결 |

### 3-2. 칩 정리 효과 — sent 보호 검증

`unassign_dates` 가 호출하는 3개 cleanup 함수 모두 **`sent_at IS NULL` 만 삭제** (검증됨):
- `surcharge.py:_delete_all_surcharge_chips` L256: `ReservationSmsAssignment.sent_at.is_(None)`
- `room_upgrade_promise.py` / `room_upgrade_review.py` 의 `delete_all_chips` 헬퍼도 동일 docstring 명시

→ sent 칩은 영구 보호. Before 의 chips_to_check 블록 (L380~L398) 의 sent 보호 정책과 일관.

### 3-3. 통계 변수 영향

| 변수 | Before 값 | After 값 |
|---|---|---|
| `room_assignments_deleted` | `len(ra_deleted)` | `unassign_dates` 반환값 (= 동일) |
| `chips_deleted_unsent` | chips_to_check 블록에서 sent_at None 인 모든 ReservationSmsAssignment 삭제 카운트 | 동일 — 단 unassign_dates 가 먼저 surcharge/upgrade 미발송 칩을 삭제한 *이후* chips_to_check 가 나머지 (standard SMS) 칩만 카운트 |
| `sent_chips_preserved` | sent_at not None 인 모든 ReservationSmsAssignment 카운트 | 동일 (sent 보호 정책 보존) |

**`chips_deleted_unsent` 통계 변화 분석**:
- Before: 전체 미발송 칩 (surcharge + upgrade + standard) 모두 카운트
- After: surcharge + upgrade 미발송 칩은 unassign_dates 가 먼저 삭제 → chips_to_check 가 못 봄 → standard SMS 칩만 카운트

→ **통계 숫자는 감소할 수 있음**. 단 데이터베이스 실제 상태는 동일 (어차피 같은 칩들이 삭제됨, 단지 카운트의 책임이 분리됨).

이 변화는:
- 의도된 부수 효과 (lifecycle 정책에 따른 통계 위치 변경)
- diag 로깅의 `chips_deleted_unsent` 값 변화 — 모니터링 도구가 이 숫자에 의존하면 영향. 단 본 마이그레이션의 단계 #17 이후 chips_to_check 블록 자체가 사라질 예정이라 일시적.

### 3-4. 트랜잭션 / 호출 순서

| 순서 | Before | After |
|---|---|---|
| 1) | `ra_deleted = query.all()` | `unassign_dates` 진입 → 자체 query.all() |
| 2) | `for ra: db.delete(ra)` (flush 없이 마킹만) | `query.delete(sync="fetch")` (즉시 delete + flush via `_compact_bed_orders_in_cells`) |
| 3) | (다음 블록의 chips_to_check `query.all()`) | `_compact_bed_orders_in_cells` 후 db.flush 발동 → surcharge/upgrade cleanup → chips_to_check 가 그 결과 본 후 standard 칩 처리 |

→ flush 시점이 미세하게 다름. `db.delete(ra)` 의 마킹 후 flush 는 후속 query 시점에 발동 (SQLAlchemy autoflush) — 결과는 동일. 다만 affected_cells 의 bed_order 재정렬이 chips_to_check 보다 먼저 일어남 → 정상.

### 3-5. reservation 객체 중복 조회

`unassign_dates` 가 내부에서 `db.query(Reservation).filter(...).first()` 함 — caller (`_do_reduce_extension`) 의 L322 에서 이미 조회한 동일 객체.
- 영향: 미세한 추가 쿼리 (1 row, indexed by PK) — 성능 영향 무시 가능
- ORM identity map 으로 중복 인스턴스 0건 (같은 객체 반환)

---

## 4. 시나리오별 결과

| 시나리오 | Before | After | 판정 |
|---|---|---|---|
| 5박 → 4박 (1박 reduce), 일반실 | 1 RA 삭제 (bed_order N/A) | 동일 | ✅ |
| 5박 → 4박, 도미토리 셀 다른 점유자 있음 | 1 RA 삭제, bed_order 갭 남음 | 1 RA 삭제 + bed_order 재정렬 | 🔵 누락 해결 |
| 5박 → 4박, 해당 날짜의 surcharge 칩 미발송 존재 | chips_to_check 가 삭제 (카운트 +1) | unassign_dates 가 먼저 삭제 (카운트 미포함), chips_to_check 못 봄 | ✅ DB 상태 동일, 카운트 위치만 이동 |
| 5박 → 4박, 해당 날짜의 surcharge 칩 sent 존재 | chips_to_check 가 sent 보존 | unassign_dates 가 sent 보존 (`sent_at IS NULL` 필터) | ✅ |
| 빈 dates_to_remove (이론적, 새 end 가 기존과 같음) | for 루프 무 동작, count=0 | unassign_dates 가드 발동, count=0 | ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

본 단계에서 변경 0:
- L322~L365 (reservation 조회 + validation + 새 end 계산) — 변경 0
- L380~L398 `chips_to_check` 블록 — 변경 0 (단계 #17 에서 lifecycle 흡수)
- L400~L420 `# 2. Delete unsent SMS chips` 의 나머지 로직 — 변경 0
- L421~L450 `original.check_out_date = new_end_str` 등 (단계 #14 의 Mutator 호출 포함) — 변경 0
- L450~L470 `reconcile_chips_for_reservation` 호출 — 변경 0 (단계 #17 에서 교체)
- L471~L485 `diag("reduce_extension.completed")` + return — 변경 0
- L487~L520 `reduce_extension` HTTP 핸들러 + `cancel_extend_stay` 핸들러 — 변경 0
- 다른 caller 모두 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/api/reservations_stay.py` 에러 0
- [ ] **diff**: 약 -9 라인 (Before 11 라인 → After 2 라인)
- [ ] **`unassign_dates` 호출 site 1건 추가**:
  - `grep -rn "unassign_dates" app/ | grep -v room_assignment.py | grep -v __pycache__` → 1건 (`reservations_stay.py` 의 호출)
- [ ] **시나리오 단위 검증** (수동, 선택):
  - 도미토리 5박 예약 → 1박 reduce → DB 의 bed_order 가 1, 2, 3 으로 재정렬 확인
  - surcharge 칩 미발송 있는 상태 → reduce 후 surcharge 칩 삭제 확인 (sent 는 보존)
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #2 시점과 동일
- [ ] **외부 영향**: `git diff main -- app/` 가 reservations_stay.py 외 0 라인 (단계 #1, #2 추가 분 제외)

---

## 7. 본 단계 이후의 후속 의존성

- **#4** (`naver_sync` cc1 → `unassign_dates`) — 같은 함수 호출 패턴, 본 단계와 독립
- **#17** (`_do_reduce_extension` → `on_dates_changed` 호출) — 본 단계 후 chips_to_check 블록 흡수
- 분기점 #4 머지 = bed_order 누락 해결 분기점 도달

---

## 8. 미결 검토 항목

- [ ] `chips_deleted_unsent` 통계의 의미 변화 — 운영 모니터링 도구가 이 값에 의존하는지 확인. 단계 #17 머지 후 chips_to_check 블록 자체가 사라지므로 일시적 영향.
- [ ] flush 시점 차이 (단계 #1 의 `unassign_dates` 가 명시적 flush) — autoflush 와 동등하지만 명시 호출이라 더 안전.

---

## 9. 머지 후 다음 액션

`lifecycle-step-04-naver-cc1-unassign-dates.md` 작성 (단계 #4 사전조사).
