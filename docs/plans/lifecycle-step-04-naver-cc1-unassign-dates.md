# 단계 #4 사전조사 — `naver_sync` cc1 의 직접 RA delete → `unassign_dates` 위임

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §B
> 분류: 🔵 **silent 버그 해결** — 누락 패턴 #4 (bed_order 재정렬은 기존에도 있었음, 코드 중복 제거 + 정합성 강화)
> 변경 규모: `app/services/naver_sync.py` cc1 블록 ~38 라인 축소 → ~15 라인
> **분기점**: 본 단계 머지 = bed_order 정렬 누락 해결 분기점 도달

---

## 1. 목적

`naver_sync._update_reservation` 의 당일취소 (cc1) 분기 에서 RoomAssignment 직접 조작 (`db.query(RA).filter().delete()` + `_compact_bed_orders_in_cells` 호출 + surcharge/upgrade cleanup) 을 단계 #1 의 `unassign_dates` 호출로 통합. caller 는 affected_dates 수집 + reservation 무효화 + diag 로깅만 책임.

### 본 단계의 핵심 — 기존 cc1 이 *이미* bed_order 재정렬 + cleanup 을 하고 있음

cc1 블록 (L789~L839) 은 이미 `_compact_bed_orders_in_cells` + surcharge/upgrade cleanup 을 직접 호출 — bed_order 누락 패턴 #4 는 **이미 부분적으로 해결되어 있음**. 본 단계의 핵심 가치는:
1. **코드 중복 제거** — `unassign_dates` 가 이 모든 후처리를 흡수 (단일 구현)
2. **정합성 강화** — 신규 caller 가 같은 패턴을 또 작성하지 않도록 단일 게이트웨이
3. **회귀 차단 분기점** — 본 단계 머지 후 모든 RA 직접 조작은 `services/room_assignment.py` 내부로 제한

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| cc1/cc2 분기 전체를 `on_status_cancelled` 호출로 치환 | 단계 #15 |
| `_cancel_deleted` 의 ReservationSmsAssignment 삭제 (L843~L857) | 단계 #15 (lifecycle 흡수) |
| `existing.room_number=None`, `room_password=None` | caller 유지 |
| stay_group unlink + peer sync_sms_tags (L860~L880) | caller 유지 |

---

## 2. 변경 대상 코드

### `app/services/naver_sync.py` L791~L839 (cc1 블록 본문)

**Before** (실측):

```python
        if is_same_day_cancel:
            # 당일 취소: 오늘 이후 배정만 해제, 미배정 풀에 빨간 행으로 표시
            from app.db.models import RoomAssignment as RA
            tid = get_session_tenant_id(db)

            # S5 반영: 영향 날짜 먼저 수집 (+ bed_order 재정렬을 위한 room_id도 함께)
            affected_rows = db.query(RA).filter(
                RA.reservation_id == existing.id,
                RA.tenant_id == tid,
                RA.date >= today_str,
            ).all()
            affected_dates = [ra.date for ra in affected_rows]
            affected_cells = {(ra.room_id, ra.date) for ra in affected_rows if ra.room_id}

            # Idempotent guard: 이미 정리된 cancelled 예약이면 매 sync 마다 무용한 delete +
            # critical diag noise 방지. affected_dates 가 비었다는 건 이전 sync 가 이미 정리했거나
            # 애초에 미배정 상태였다는 뜻 — 더 이상 할 일 없음.
            if affected_dates:
                db.query(RA).filter(
                    RA.reservation_id == existing.id,
                    RA.tenant_id == tid,
                    RA.date >= today_str,
                ).delete(synchronize_session="fetch")
                existing.room_number = None
                existing.room_password = None

                if affected_cells:
                    db.flush()
                    compacted = room_assignment._compact_bed_orders_in_cells(db, affected_cells)
                    if compacted:
                        diag(
                            "naver_sync.same_day_cancel.compact",
                            level="verbose",
                            res_id=existing.id,
                            cells_count=len(affected_cells),
                            changed=compacted,
                        )

                # S5 반영: surcharge / room_upgrade_promise / _review 칩 정리
                try:
                    from app.services.surcharge import _delete_all_surcharge_chips
                    from app.services.room_upgrade_promise import _delete_all_room_upgrade_promise_chips
                    from app.services.room_upgrade_review import _delete_all_room_upgrade_review_chips
                    for d in affected_dates:
                        _delete_all_surcharge_chips(db, existing.id, d)
                        _delete_all_room_upgrade_promise_chips(db, existing.id, d)
                        _delete_all_room_upgrade_review_chips(db, existing.id, d)
                except Exception as e:
                    logger.warning(f"Naver same-day cancel chip cleanup failed: {e}")

                diag("naver_sync.same_day_cancel", level="critical", reservation_id=existing.id, dates=affected_dates)
```

**After**:

```python
        if is_same_day_cancel:
            # 당일 취소: 오늘 이후 배정만 해제, 미배정 풀에 빨간 행으로 표시
            from app.db.models import RoomAssignment as RA
            tid = get_session_tenant_id(db)

            # 영향 날짜 수집 (idempotent guard + diag 로깅용)
            affected_dates = [
                ra.date for ra in db.query(RA).filter(
                    RA.reservation_id == existing.id,
                    RA.tenant_id == tid,
                    RA.date >= today_str,
                ).all()
            ]

            # Idempotent guard: 이미 정리된 cancelled 예약이면 매 sync 마다 무용한 delete +
            # critical diag noise 방지. affected_dates 가 비었다는 건 이전 sync 가 이미 정리했거나
            # 애초에 미배정 상태였다는 뜻 — 더 이상 할 일 없음.
            if affected_dates:
                # lifecycle 단계 #4: unassign_dates 로 위임
                # — RA delete + bed_order 재정렬 + surcharge/upgrade 칩 cleanup 자동
                room_assignment.unassign_dates(db, existing.id, affected_dates)
                existing.room_number = None
                existing.room_password = None

                diag("naver_sync.same_day_cancel", level="critical", reservation_id=existing.id, dates=affected_dates)
```

총 라인: Before ~50 라인 → After ~22 라인 = **-28 라인**.

### 2-1. 라인 단위 정당화 — "지워지는 코드가 어디서 대신 수행되나"

| 지워지는 라인 | 역할 | 대체 위치 |
|---|---|---|
| `affected_rows = db.query(RA).filter(...).all()` (전체 row 캡처) | bed_order 셀 + 날짜 동시 수집 | After 의 `affected_dates = [ra.date for ra in db.query(RA).filter(...).all()]` 가 날짜만 수집. `affected_cells` 는 `unassign_dates` 가 내부에서 자체 query (`old_assignments = query.all()` + `affected_cells = {(ra.room_id, ra.date) for ...}`) 로 재수집 |
| `affected_cells = {(ra.room_id, ra.date) ...}` | bed_order 재정렬 대상 | `unassign_dates` 내부 동등 로직 (단계 #1 §2-1) |
| `db.query(RA).filter(...).delete(sync="fetch")` | RA 삭제 | `unassign_dates` 내부 `count = query.delete(synchronize_session="fetch")` |
| `if affected_cells: db.flush() + _compact_bed_orders_in_cells(...) + diag` | bed_order 재정렬 + verbose 로깅 | `unassign_dates` 내부 동등 (단계 #1 §2-1, diag 이름 `unassign_dates.compact` 로 변경) |
| `for d in affected_dates: _delete_all_surcharge_chips / _delete_all_room_upgrade_*_chips` | 칩 cleanup | `unassign_dates` 내부 동등 (단계 #1 §2-1) |
| `try/except logger.warning("Naver same-day cancel chip cleanup failed")` | cleanup 실패 가드 | `unassign_dates` 내부 동등한 try/except + `logger.warning("Surcharge/room_upgrade cleanup failed")` |

→ 모든 책임이 `unassign_dates` 내부에서 동등하게 수행됨.

### 2-2. 잔존 라인 (caller 책임 유지)

| 잔존 라인 | 사유 |
|---|---|
| `from app.db.models import RoomAssignment as RA` + `tid = get_session_tenant_id(db)` | affected_dates 수집 query 에 필요 |
| `affected_dates = [...]` query | idempotent guard 조건 + diag 인자 |
| `if affected_dates:` | idempotent guard 유지 — Before/After 동일 정책 |
| `existing.room_number = None`, `existing.room_password = None` | `unassign_dates` 가 reservation 의 denormalized 필드 정리 안 함 — caller 책임 (clear_all_for_reservation 의 대응 로직과 일치) |
| `diag("naver_sync.same_day_cancel", level="critical", ...)` | 운영 critical 이벤트 — `unassign_dates` 의 verbose diag 로는 대체 불가, 호환성 유지 |

### 2-3. diag 이벤트 이름 변화

| Before diag | After diag |
|---|---|
| `naver_sync.same_day_cancel.compact` (verbose) | `unassign_dates.compact` (verbose, 단계 #1 의 함수 내) |
| `naver_sync.same_day_cancel` (critical) | 동일 — caller 가 유지 |

→ verbose 이벤트 이름이 변경됨. 운영 모니터링 도구가 `naver_sync.same_day_cancel.compact` 에 의존하면 영향. critical 이벤트는 그대로.

---

## 3. 동작 동등성

### 3-1. DB 변경 동등성

| 입력 / 시나리오 | Before 결과 | After 결과 | 동등 |
|---|---|---|---|
| affected_dates 가 비어있는 cancel | 가드로 skip (idempotent) | 동일 — `if affected_dates:` 가드 | ✅ |
| 1개 RA, 일반실 | 1 RA 삭제, room_number=None, room_password=None, diag | 동일 (unassign_dates 가 RA 삭제, caller 가 None 세팅, diag) | ✅ |
| 1개 RA, 도미토리, 같은 셀에 다른 점유자 | 1 RA 삭제 + bed_order 재정렬 (`_compact_bed_orders_in_cells`) | 동일 — unassign_dates 내부 동등 로직 | ✅ |
| 미발송 surcharge 칩 있는 cancel | 3 함수 호출 → 미발송만 삭제 | 동일 — unassign_dates 내부 동등 로직 (단계 #1) | ✅ |
| sent surcharge 칩 있는 cancel | sent 보존 (`sent_at.is_(None)` 필터) | 동일 — unassign_dates 가 호출하는 `_delete_all_*_chips` 모두 sent 보호 (단계 #3 §3-2 검증) | ✅ |
| cleanup 함수 1개 실패 | 다른 cleanup 도 try/except 로 logger.warning, 진행 계속 | 동일 — unassign_dates 의 `try/except logger.warning` | ✅ |

### 3-2. 호출 순서

| 순서 | Before | After |
|---|---|---|
| 1) | `affected_rows = query.all()` | `affected_dates = [ra.date for ra in query.all()]` (동등 쿼리) |
| 2) | `affected_cells = {...}` 계산 | (생략 — unassign_dates 가 재계산) |
| 3) | `if affected_dates:` 가드 | 동일 |
| 4) | `db.query(RA).filter(...).delete()` | `unassign_dates(...)` 진입 |
| 4-1) | `existing.room_number=None` | `unassign_dates` 가 자체 query 후 delete |
| 4-2) | `existing.room_password=None` | bed_order 재정렬 + 칩 cleanup |
| 5) | `if affected_cells: flush + compact + diag` | (unassign_dates 안에서 발생) |
| 6) | for d: 3 cleanup 함수 호출 | (unassign_dates 안에서 발생) |
| 7) | `diag("naver_sync.same_day_cancel", critical)` | After 의 4-1, 4-2 이후 → diag |

After 의 4 (unassign_dates) 와 4-1, 4-2 (caller 의 room_number/password None) 사이 순서:
- Before 는 `delete()` 가 먼저, `room_number=None` 그 다음
- After 는 `unassign_dates(...)` 가 먼저 (RA delete + cleanup), `room_number=None` 그 다음

→ caller 의 ORM 필드 세팅은 다음 commit/flush 까지 보류 — 두 케이스 모두 동일. 트랜잭션 종료 시점에 양쪽 다 반영.

### 3-3. 추가 query 1개 — affected_dates 만 수집하기 위해

Before 는 `affected_rows` 에서 `affected_dates` 와 `affected_cells` 를 함께 계산. After 는 `affected_dates` 만 수집하고 `affected_cells` 는 `unassign_dates` 내부에서 재계산.

→ 같은 RA 행을 2번 query (한 번은 caller, 한 번은 unassign_dates). 성능 영향:
- 같은 reservation_id + tenant_id + date >= today_str 필터 — indexed
- 행 개수: 일반적으로 < 30 (예약 1건의 미래 날짜 RA)
- 영향: 1 query 추가 × ~30 rows — ms 단위, 무시 가능

→ silent regression 아님. 미세한 비효율.

### 3-4. `unassign_dates` 내부 reservation 조회

`unassign_dates(db, reservation_id, dates)` 가 내부에서 `reservation = db.query(Reservation).first()` 함. caller (`_update_reservation`) 는 이미 `existing` 객체 보유.

- ORM identity map 으로 같은 객체 반환 (1 row indexed by PK)
- 영향: 미세한 추가 쿼리, 무시 가능

---

## 4. 시나리오별 결과

| 시나리오 | Before | After | 판정 |
|---|---|---|---|
| 일반 당일취소, 1개 RA, 일반실 | 1 RA 삭제, room_number=None | 동일 | ✅ |
| 도미토리 당일취소, bed_order 갭 발생 케이스 | bed_order 재정렬 + diag(compact) | 동일 — diag 이름만 변경 | ✅ DB 동등 |
| sent 칩 있는 당일취소 | sent 보존, 미발송 surcharge 삭제 | 동일 | ✅ |
| affected_dates 빈 cancel | skip (no-op) | 동일 | ✅ |
| cleanup 실패 (DB 에러 등) | logger.warning, 진행 계속 | 동일 (unassign_dates 의 try/except) | ✅ |
| diag 모니터링 도구가 `naver_sync.same_day_cancel.compact` 추적 중 | 이벤트 발생 | 발생 안 함 (`unassign_dates.compact` 가 대체) | 🟡 운영 영향 |

---

## 5. 영향받지 않음을 확인할 코드 경로

본 단계에서 변경 0:
- L786~L789 `today_str`, `check_in_str`, `is_same_day_cancel` 계산 — 변경 0
- L840~L842 cc2 (`else:`) 분기 — 변경 0 (단계 #15 에서 lifecycle 흡수)
- L843~L857 `_cancel_deleted` ReservationSmsAssignment 삭제 — 변경 0
- L860~L880 stay_group unlink + peer sync_sms_tags — 변경 0
- 다른 함수 / 다른 파일 — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff**: cc1 블록 ~28 라인 축소 (Before ~50 → After ~22)
- [ ] **`unassign_dates` 호출 site 2건**:
  - `grep -rn "unassign_dates(" app/ | grep -v room_assignment.py | grep -v __pycache__` → 2건 (reservations_stay.py + naver_sync.py)
- [ ] **잔존 라인 정확**: §2-2 의 5 항목 모두 잔존
- [ ] **diag 이벤트 이름**: critical `naver_sync.same_day_cancel` 그대로, verbose `same_day_cancel.compact` 사라짐
- [ ] **시나리오 단위 검증** (수동, 선택):
  - 도미토리 미래 1박 예약 → 당일 취소 → bed_order 재정렬 확인
  - 미래 surcharge 칩 있는 예약 → 당일 취소 → 미발송 칩 삭제 + sent 보존 확인
- [ ] **기존 pytest 회귀**: pass/fail 개수 단계 #3 시점과 동일
- [ ] **외부 영향**: `git diff main -- app/` 가 naver_sync.py 외 본 마이그레이션 무관 라인 0

---

## 7. 본 단계 이후의 후속 의존성

- **분기점 #4 머지 = bed_order 정렬 누락 해결 + RA 직접 조작 0건 (caller 측)**
- **#15** (cc1/cc2 → `on_status_cancelled` 호출) — 본 단계 후 cc1 블록 자체를 lifecycle 로 흡수
- **#22** (CI lint) — 본 단계 머지 후 RA 직접 조작 차단 lint 가 안전

---

## 8. 미결 검토 항목

- [ ] verbose diag `naver_sync.same_day_cancel.compact` 이벤트 이름 변경 — 운영 모니터링 도구가 이 이벤트에 의존하는지 확인. 의존 시 alias 추가 또는 운영 도구 갱신.
- [ ] `existing.room_number=None`, `room_password=None` 세팅은 caller 책임 유지 — 단계 #15 `on_status_cancelled` 에 흡수 시 고려.

---

## 9. 머지 후 다음 액션

본 단계 PR 머지 = **분기점 #4 도달**.

→ `lifecycle-step-05-on-dates-changed-impl.md` 작성 (단계 #5 사전조사: `on_dates_changed` 실제 구현).
