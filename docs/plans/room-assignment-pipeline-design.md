# RoomAssignment Pipeline 정리 설계안

> 작성일: 2026-05-14
> 상태: 검토 대기
> 관련 설계: [reservation-mutator-design.md](./reservation-mutator-design.md) (전 단계 — Reservation 필드 변경 게이트)
> 본 설계 범위: Mutator 통과 **이후** 단계 — RoomAssignment / DailyInfo / PartyCheckin / SmsAssignment 후처리

---

## 1. 배경 — 왜 이 설계가 필요한가

### 1-1. 문제 정의

`Reservation`이 변경된 직후 따라와야 할 후처리(방 배정 정리, 일자별 정보 평행이동, SMS 칩 재계산, invariant 검증)가 **caller 책임**으로 분산되어 있다. 각 진입점이 어떤 후처리를 어떤 순서로 부를지 직접 결정하기 때문에, 빠뜨리거나 잘못된 버전을 부르는 누락이 조용히 발생한다.

```
현재:
  [extend_stay]    → assign_room + reconcile_chips_for_reservation (구버전)
  [reduce_extend]  → db.delete(ra) 직접 + reconcile_chips_for_reservation (구버전)
  [update PUT]     → shift + reconcile_dates + unassign + reconcile_all_chips + invariant
  [naver_sync]     → shift + reconcile_dates + unassign + sync_sms_tags
  [delete]         → clear_all + 칩 직접 SQL DELETE
  [naver cc1]      → db.query(RA).filter().delete() 직접
  [naver cc2]      → clear_all_for_reservation
  [room_room PUT]  → assign_room (+ unassign 분기 시 sync_sms_tags)
```

같은 "예약 변경 후 정리" 사건인데 7가지 처리가 섞여 있고, 칩 reconcile 함수만 3종이 혼재한다.

### 1-2. Mutator 설계안과의 관계

| | Mutator (이전 단계) | 본 설계 (이후 단계) |
|---|---|---|
| **대상 테이블** | `Reservation` 1줄 | `RoomAssignment` + `ReservationDailyInfo` + `PartyCheckin` + `ReservationSmsAssignment` |
| **결정하는 것** | "이 source가 이 필드를 바꿀 수 있나?" | "필드가 바뀌었으니 어떤 후처리를 따라야 하나?" |
| **실패 시 영향** | 필드가 안 바뀜 | 필드는 바뀌었는데 부속 데이터가 어긋남 (silent drift) |

caller 흐름:
```
caller → Mutator.apply(...)              # 권한 통과 + Reservation 필드 변경
       → on_<event>(...)                 # 본 설계의 lifecycle 함수
       → db.commit()
```

두 게이트웨이는 독립적이고, 각자 단독 도입해도 효과가 있다.

---

## 2. 현재 구조 사전점검

### 2-1. 진입점별 후처리 호출 매트릭스 (코드 실측)

| 진입점 (파일:라인) | RA 변경 방식 | shift_daily | reconcile_dates | reconcile_all_chips | sync_sms_tags | invariant check |
|---|---|:---:|:---:|:---:|:---:|:---:|
| `reservations_room.py:45` assign PUT | `assign_room` / `unassign_room` 서비스 | × | × | × | ✅ (unassign 시만) | × |
| `reservations_stay.py:157` extend_stay | `assign_room` 서비스만 | × | × | × *구버전 호출* | × | × |
| `reservations_stay.py:304` _do_reduce_extension | **`db.delete(ra)` 직접** | × | × | × *구버전 호출* | × | × |
| `reservations.py:261` update PUT | `unassign_room` 서비스 | ✅ | ✅ | ✅ | × | ✅ |
| `reservations.py:458` delete_reservation | `clear_all_for_reservation` | × | × | × | × | × |
| `naver_sync.py:646` _update_reservation | `unassign_room` 서비스 | ✅ | ✅ | × | ✅ (조건부) | ✅ |
| `naver_sync.py:763~` 당일취소 cc1 | **`db.query(RA).filter().delete()` 직접** | × | × | × | × | × |
| `naver_sync.py:815` 사전취소 cc2 | `clear_all_for_reservation` | × | × | × | × | × |
| `room_auto_assign.py:425/446` 자동배정 | `assign_room` 서비스 | × | × | × | ✅ (사전) | × |

*구버전 = `chip_reconciler.py:41 reconcile_chips_for_reservation` (5종 중 기본 칩만, surcharge/party3/room_upgrade_promise/room_upgrade_review 누락)*

### 2-2. RoomAssignment 테이블 직접 조작 (서비스 우회)

| 위치 | 라인 | 코드 | 누락되는 처리 |
|---|---|---|---|
| `reservations_stay.py` | 376 | `db.delete(ra)` (reduce_extension) | bed_order 재정렬, push-out 가드, surcharge cleanup |
| `naver_sync.py` | 763~771 | `db.query(RA).filter(...).delete()` (cc1) | 동일 (bed_order, surcharge cleanup) |

`services/room_assignment.py` 외부에서 RoomAssignment를 INSERT/DELETE하는 곳은 위 두 곳뿐. 나머지는 서비스 함수 경유.

### 2-3. 칩 reconcile 함수 3종 혼재

| 함수 | 처리 범위 | 사용처 |
|---|---|---|
| `reconcile_all_chips` (reconcile.py:23) | 5종 전부 (기본+추가요금+파티3MMS+업그레이드 약속/후기) | `reservations.py` PUT만 |
| `sync_sms_tags` (room_assignment.py:198) | 기본 칩만 | `naver_sync._update`, `room_auto_assign`, peer cleanup |
| `reconcile_chips_for_reservation` (chip_reconciler.py:41) | 구버전 — 기본 칩만 | `extend_stay`, `_do_reduce_extension` |

→ 진입점에 따라 추가요금/파티/업그레이드 칩이 갱신되거나 stale 상태로 남는다.

### 2-4. push-out 후처리 누락

`assign_room` 내부 push-out 분기 (`room_assignment.py:266~548`)에서:
- ✅ push-out된 예약의 `section='unassigned'` 세팅
- ✅ surcharge / room_upgrade 칩 정리 (L437-456)
- ❌ push-out된 예약에 대한 `reconcile_all_chips` 미호출 → 5종 중 일부 stale

caller가 별도로 처리하지 않으면 누락.

### 2-5. 후처리 함수 시그니처 (services/room_assignment.py)

| 함수 | 라인 | 책임 |
|---|---|---|
| `sync_sms_tags(db, reservation_id, schedules=None)` | 198 | 기본 SMS 칩 동기화 (column_match/structural filter 재평가) |
| `assign_room(db, reservation_id, room_id, from_date, end_date, ...) -> (assignments, pushed_out)` | 213 | RA INSERT + 충돌 push-out + bed_order/비밀번호 계산 |
| `unassign_room(db, reservation_id, from_date=None, end_date=None) -> int` | 569 | RA range DELETE (None → 전체) |
| `clear_all_for_reservation(db, reservation_id) -> int` | 668 | RA 전체 DELETE + Reservation.room_number/password NULL |
| `shift_daily_records(db, reservation, old_check_in, old_check_out) -> dict` | 741 | ReservationDailyInfo / PartyCheckin 상대 인덱스 평행이동 |
| `reconcile_dates(db, reservation)` | 826 | check_in/out 범위 밖 RA DELETE + 누락 날짜 자동 INSERT + push-out |
| `sync_denormalized_field(db, reservation)` | 709 | **DEPRECATED** (주석 명시) |

---

## 3. 제안 구조 — Lifecycle 함수

### 3-1. 핵심 아이디어

후처리 호출 책임을 caller에서 분리. 변경 종류별로 묶은 **5개 lifecycle 함수**만 외부에 노출하고, caller는 자기 변경이 어떤 종류인지만 알면 됨.

```
변경 종류                  → 호출할 lifecycle 함수
──────────────────────────────────────────────────
체크인/체크아웃 변경       → on_dates_changed
성별/인원/section 변경     → on_constraints_changed
status=CANCELLED           → on_status_cancelled
방 배정 (assign_room 직후) → on_room_assigned
예약 삭제                  → on_reservation_deleted
```

### 3-2. 함수 시그니처 안

```python
# services/reservation_lifecycle.py (신규)

def on_dates_changed(
    db: Session,
    reservation: Reservation,
    old_check_in: str,
    old_check_out: str,
) -> None:
    """체크인/체크아웃이 바뀐 직후 호출."""
    shift_daily_records(db, reservation, old_check_in, old_check_out)
    reconcile_dates(db, reservation)
    reconcile_all_chips(db, reservation.id)


def on_constraints_changed(
    db: Session,
    reservation: Reservation,
    changed_fields: set[str],
) -> None:
    """성별/인원/section 등 invariant 영향 필드가 바뀐 직후."""
    invalid_dates = check_assignment_validity(db, reservation)
    if invalid_dates:
        future_invalid = _filter_future(invalid_dates)
        if future_invalid:
            unassign_room(
                db, reservation.id,
                from_date=future_invalid[0],
                end_date=_next_day(future_invalid[-1]),
            )
            _log_invariant_violation(...)
    reconcile_all_chips(db, reservation.id)


def on_status_cancelled(
    db: Session,
    reservation: Reservation,
    *,
    same_day: bool,
) -> None:
    """status=CANCELLED 로 바뀐 직후. cc1/cc2 분기 흡수."""
    if same_day:
        future_dates = _future_dates(reservation)
        unassign_dates(db, reservation.id, future_dates)
    else:
        clear_all_for_reservation(db, reservation.id)
    _delete_unsent_chips(db, reservation.id)


def on_room_assigned(
    db: Session,
    reservation: Reservation,
    pushed_out: list[dict],
) -> None:
    """assign_room 직후 호출. push-out된 예약의 칩까지 재계산."""
    reconcile_all_chips(db, reservation.id)
    for p in pushed_out:
        reconcile_all_chips(db, p["reservation_id"])


def on_reservation_deleted(
    db: Session,
    reservation_id: int,
) -> None:
    """DELETE /reservations/{id} 처리 시."""
    clear_all_for_reservation(db, reservation_id)
    _delete_all_chips(db, reservation_id)
```

### 3-3. RoomAssignment 직접 조작 제거 — 신규 함수 1개

```python
# services/room_assignment.py 추가

def unassign_dates(db: Session, reservation_id: int, dates: list[str]) -> int:
    """특정 날짜 목록의 RA 삭제 + bed_order 재정렬.
    기존 unassign_room 은 range 기반이라 비연속 날짜 케이스를 못 다룸.
    """
```

`reduce_extension`의 `db.delete(ra)`와 `naver_sync` cc1의 `db.query(RA).filter().delete()`를 모두 이 함수로 위임.

### 3-4. 호출자 매핑 — 7개 진입점 일괄 전환

| 진입점 | Before | After |
|---|---|---|
| `reservations.py:261` update PUT (날짜 변경) | shift + reconcile_dates + reconcile_all_chips | `on_dates_changed(...)` |
| `reservations.py:261` update PUT (인원 변경) | invariant + unassign + reconcile_all_chips | `on_constraints_changed(...)` |
| `reservations.py:458` delete | clear_all + 칩 직접 DELETE | `on_reservation_deleted(...)` |
| `reservations_stay.py:157` extend_stay | check_out 변경 + assign_room + 구버전 칩 | check_out 변경 + assign_room + `on_dates_changed(...)` + `on_room_assigned(...)` |
| `reservations_stay.py:304` _do_reduce_extension | check_out 변경 + `db.delete(ra)` + 구버전 칩 | check_out 변경 + `on_dates_changed(...)` |
| `reservations_room.py:45` assign PUT | assign_room (+조건부 sync_sms_tags) | assign_room + `on_room_assigned(...)` |
| `naver_sync.py:646` _update (날짜 변경) | shift + reconcile_dates + sync_sms_tags | `on_dates_changed(...)` |
| `naver_sync.py:646` _update (인원 변경) | invariant + unassign + sync_sms_tags | `on_constraints_changed(...)` |
| `naver_sync.py:763` cc1 (당일취소) | 직접 RA DELETE | `on_status_cancelled(same_day=True)` |
| `naver_sync.py:815` cc2 (사전취소) | clear_all | `on_status_cancelled(same_day=False)` |
| `room_auto_assign.py:425` 자동배정 | assign_room (+ sync_sms_tags 사전) | assign_room + `on_room_assigned(...)` |

### 3-5. 후처리 함수 가시성 정리

| 함수 | 가시성 변경 | 사유 |
|---|---|---|
| `shift_daily_records` | private 화 (`_shift_daily_records`) | lifecycle 내부에서만 호출 |
| `reconcile_dates` | private 화 | 동일 |
| `reconcile_chips_for_reservation` | **삭제** (또는 `_legacy_` 접두) | `reconcile_all_chips` 로 일원화 |
| `sync_sms_tags` | 유지 (peer cleanup 등 단발 호출 필요) | 단 새 caller 추가 시 lifecycle 검토 |
| `assign_room` / `unassign_room` / `clear_all_for_reservation` / `unassign_dates` | 유지 (lifecycle이 호출) | low-level primitive |

---

## 4. 현재 vs 제안 비교

| 항목 | 현재 (As-Is) | 제안 (To-Be) |
|---|---|---|
| 후처리 결정 책임 | caller 7곳에 분산 | lifecycle 함수 5개로 통일 |
| RoomAssignment 직접 조작 | 2곳 (services 우회) | 0곳 (`unassign_dates` 경유) |
| 칩 reconcile 함수 종류 | 3종 혼재 (full/기본/구버전) | 1종 (`reconcile_all_chips`) |
| push-out 칩 후처리 | caller 책임 (대부분 누락) | `on_room_assigned` 내부에서 보장 |
| extend_stay의 shift_daily 누락 | 🔴 발생 | ✅ on_dates_changed가 보장 |
| reduce_extension의 bed_order 미정렬 | 🔴 발생 | ✅ unassign_dates가 보장 |
| naver_sync의 surcharge 칩 stale | 🔴 발생 | ✅ on_dates_changed → reconcile_all_chips |
| 새 진입점 추가 시 | 후처리 7개 함수 조합 직접 결정 | 변경 종류만 알면 됨 |

---

## 5. 마이그레이션 단계

각 단계는 독립 실행 가능하며 단계마다 기존 integration test로 회귀 검증.

| 단계 | 작업 | 위험도 | 크기 |
|---|---|---|---|
| **1** | `services/room_assignment.py` 에 `unassign_dates(reservation_id, dates)` 추가 | 낮음 | 작음 |
| **2** | `reservations_stay.py:376` `db.delete(ra)` → `unassign_dates` 호출로 교체 | 낮음 | 작음 |
| **3** | `naver_sync.py:763~` 직접 `db.query(RA).delete()` → `unassign_dates` 호출로 교체 | 중간 | 작음 |
| **4** | `services/reservation_lifecycle.py` 신규 — 5개 lifecycle 함수 구현 | 낮음 | 중간 |
| **5** | `reservations.py` PUT/DELETE → lifecycle 호출로 교체 | 중간 | 중간 |
| **6** | `naver_sync.py` _update / cc1 / cc2 → lifecycle 호출로 교체 | 중간 | 중간 |
| **7** | `reservations_stay.py` extend/reduce → lifecycle 호출로 교체 + 구버전 `reconcile_chips_for_reservation` 호출 제거 | 낮음 | 작음 |
| **8** | `reservations_room.py` assign PUT → `on_room_assigned` 호출 추가 | 낮음 | 작음 |
| **9** | `room_auto_assign.py` 자동배정 → `on_room_assigned` 호출 추가 | 낮음 | 작음 |
| **10** | `shift_daily_records` / `reconcile_dates` private 화 | 낮음 | 작음 |
| **11** | `chip_reconciler.py:41 reconcile_chips_for_reservation` 삭제 (호출처 모두 제거됨 확인 후) | 낮음 | 작음 |
| **12** | CI lint 규칙 추가 — RA 직접 조작 / 구버전 함수 호출 차단 | 낮음 | 작음 |

각 단계 후 검증 포인트:
- 단계 2~3 후: 침대 순서가 정확히 재정렬되는지 (단순 통합 테스트)
- 단계 5~9 후: 진입점별 후처리 매트릭스가 모두 동일하게 호출되는지 (mock 기반 호출 시퀀스 테스트)
- 단계 12 후: 새 PR에서 RA를 직접 만지는 코드가 추가되면 CI fail

---

## 6. 미결 검토 항목

검토 전 확인이 필요한 것들:

- [ ] `sync_sms_tags`를 lifecycle 외부 호출 허용 범위 — peer cleanup (`naver_sync.py:846`, `reservations.py:369`)은 lifecycle이 아니라 단발 호출이 자연스러움. 별도 함수로 분리할지, 그대로 두고 가시성만 유지할지.
- [ ] `extend_stay` 의 `manually_extended_until` 세팅 — 이 플래그는 Reservation 필드 변경이므로 Mutator 책임. lifecycle 도입 시점에는 그대로 두고, Mutator 도입 시 함께 제거.
- [ ] `on_status_cancelled` 내부에서 stay_group unlink 처리할지 — 현재 unlink + peer sync_sms_tags 는 caller가 직접 호출(`naver_sync.py:838`, `reservations.py:333`). lifecycle 안으로 흡수 시 의존성이 늘어남.
- [ ] `room_auto_assign` 의 `_assign_all_rooms` 루프 안에서 `on_room_assigned`를 호출하면 N회 reconcile_all_chips 실행 → 성능. 배치 끝에 한 번에 처리하는 변형(`on_batch_assigned`) 도입 검토.
- [ ] DB 트랜잭션 경계 — 현재 caller가 `db.commit()` 시점을 가짐. lifecycle 도입 후에도 동일 유지 (lifecycle은 flush까지만).
- [ ] 자동 객실 배정(`daily_room_assign_job`)에서 push-out 발생 시 `on_room_assigned` 호출이 N+M번 reconcile 트리거 → 성능 검토 (N: 배정자, M: 밀려난 자).

---

## 7. 관련 파일 위치

```
변경 대상 (lifecycle 호출로 교체):
  backend/app/api/reservations.py              — update_reservation (L261), delete_reservation (L458)
  backend/app/api/reservations_room.py         — assign_room handler (L45)
  backend/app/api/reservations_stay.py         — extend_stay (L157), _do_reduce_extension (L304)
  backend/app/services/naver_sync.py           — _update_reservation (L646), 취소 분기 (L761~L815)
  backend/app/services/room_auto_assign.py     — _assign_all_rooms (L272), push-out (L425/L446)

신규 생성:
  backend/app/services/reservation_lifecycle.py — 5개 lifecycle 함수

함수 추가:
  backend/app/services/room_assignment.py      — unassign_dates(reservation_id, dates)

가시성 변경 / 삭제:
  backend/app/services/room_assignment.py      — shift_daily_records, reconcile_dates → private
  backend/app/services/chip_reconciler.py      — reconcile_chips_for_reservation (L41) 삭제

CI / 도구:
  .github/workflows/ci.yml                      — RA 직접 조작 / 구버전 함수 호출 lint 규칙

테스트:
  backend/tests/unit/test_reservation_lifecycle.py — 5개 lifecycle 함수 단위 테스트
  backend/tests/integration/                       — 기존 진입점 테스트로 회귀 검증
```

---

## 8. 효과 — 현재 발견된 누락/버그 대비

| 누락/버그 | 단계 | 해결 메커니즘 |
|---|---|---|
| `reduce_extension`의 bed_order 미정렬 | 1, 2 | `unassign_dates`가 `_compact_bed_orders_in_cells` 호출 |
| `naver_sync` cc1의 bed_order 미정렬 | 1, 3 | 동일 |
| `extend_stay`의 PartyCheckin/DailyInfo 평행이동 누락 | 4, 7 | `on_dates_changed` 안에 `shift_daily_records` 포함 |
| `extend_stay` / `reduce_extension`의 칩 5종 중 1종만 갱신 | 4, 7 | `on_dates_changed` 안에 `reconcile_all_chips` 포함 |
| `naver_sync._update_reservation`의 surcharge/party3/upgrade 칩 stale | 4, 6 | `on_dates_changed` / `on_constraints_changed` 안에 `reconcile_all_chips` 포함 |
| `assign_room` push-out 시 밀려난 예약의 칩 stale | 4, 8, 9 | `on_room_assigned` 안에서 pushed_out 예약별로 reconcile |
| 새 caller 추가 시 후처리 또 빠뜨림 | 12 | CI lint가 직접 조작 차단 |
