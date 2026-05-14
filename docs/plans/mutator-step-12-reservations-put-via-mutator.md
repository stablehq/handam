# 단계 #12 사전조사 — `reservations.py PUT` 을 Mutator.apply 호출로 전환

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §E
> 분류: ⚫ 리팩토링 — 동작 동등성 보장
> 변경 규모: `app/api/reservations.py` setattr 루프 + pin 세팅 → Mutator.apply 1줄로 치환

---

## 1. 목적

단계 #6~#7 에서 caller (`reservations.py PUT`) 가 직접 처리하던 `setattr` 루프 + `check_in_pinned`/`check_out_pinned` 자동 세팅 로직을 `ReservationMutator.apply_changes()` 호출로 교체. 단계 #11 의 Mutator 가 흡수.

**동작 동등성**: Mutator 의 권한 평가 + pin 세팅이 단계 #6~#7 + setattr 루프와 1:1 매핑되도록 단계 #11 §4-2 표에서 검증 완료.

---

## 2. 변경 대상 코드

### `app/api/reservations.py` L336~L343 (setattr 루프 + pin 세팅)

**Before** (단계 #6~#7 + #10 머지 결과):

```python
    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    # Mutator pin: 수동 PUT 으로 날짜 변경되면 naver_sync 덮어쓰기 방지 (단계 #6, #7)
    if "check_in_date" in update_data:
        db_reservation.check_in_pinned = True
    if "check_out_date" in update_data:
        db_reservation.check_out_pinned = True

    # status 가 CANCELLED 로 바뀌면 stay_group 자동 해제 (naver_sync 와 동일 정책)
```

**After**:

```python
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, db_reservation, ChangeSource.MANUAL, update_data)

    # status 가 CANCELLED 로 바뀌면 stay_group 자동 해제 (naver_sync 와 동일 정책)
```

**변경 내용**:
- setattr 루프 (2 라인) + pin 세팅 (5 라인) → Mutator import + apply_changes 호출 (2 라인) 으로 축소
- 함수 안 lazy import — circular import 회피 (다른 services import 와 동일 패턴)
- 반환된 `applied` dict 는 본 단계에서 사용 안 함 (caller 가 후속 처리에서 `old_dates != new_dates` 비교로 분기 — Mutator 가 db_reservation 을 in-place 갱신하므로 동일하게 작동)

---

## 3. 동작 동등성 근거

### 3-1. 필드별 처리 매핑 (단계 #11 §4-2 의 MANUAL 매트릭스)

| update_data 키 | 단계 #11 머지 결과 (setattr + pin 직접) | 단계 #12 (Mutator.apply) | 동등 |
|---|---|---|---|
| `customer_name`, `phone`, `visitor_name`, `gender`, `status`, `special_requests` (always) | setattr | Mutator: always → setattr | ✅ |
| `check_in_date` | setattr + `check_in_pinned=True` | Mutator: guarded → pin_attr=False → setattr → applied 에 포함 → MANUAL 분기에서 check_in_pinned=True | ✅ |
| `check_out_date` | setattr + `check_out_pinned=True` | Mutator: guarded → setattr + check_out_pinned=True | ✅ |
| `section` | setattr | Mutator: MANUAL "always" → setattr | ✅ |
| `male_count` / `female_count` / `party_size` | setattr (caller 가 미리 gender_manual auto-set) | Mutator: MANUAL "always" → setattr (gender_manual 처리는 caller L309~L311 에서 이미 처리됨, 영향 0) | ✅ |
| `total_price` | setattr | Mutator: MANUAL "always" → setattr | ✅ |
| `gender_manual` | setattr | Mutator: 미등록 → "always" (allow-all) → setattr | ✅ |
| `notes`, `visitor_phone`, `highlight_color` 등 미등록 필드 | setattr | Mutator: 미등록 → allow-all → setattr | ✅ |
| `naver_room_type`, `booking_options` (MANUAL=never) | (frontend 가 보내지 않음 — 운영 정책) | Mutator: never → skip. 만약 보내면 silent drop ⚠️ | ⚠️ 가시화 강화 |

**`MANUAL=never` 필드 (`naver_room_type`, `booking_options`)**:
- 단계 #11 머지 전에는 setattr 가 무조건 실행 — frontend 가 의도치 않게 보내도 적용됨
- 단계 #12 머지 후에는 Mutator 가 silent skip
- **실제 frontend 코드 확인**: `useGuestMove.ts`, `Reservations.tsx` 의 PUT 호출에 위 두 필드 없음 — 영향 0
- 운영 정책 강화: 권한 매트릭스 위반 시 차단 (silent regression 아니라 silent **fix** — 보안성↑)

### 3-2. setattr 후 흐름 비교

| 단계 | 동작 |
|---|---|
| Before (#11) | 1) setattr 루프 → 2) pin 자동 세팅 → 3) status=CANCELLED 분기 (manually_extended_until=None, check_out_pinned=False) → 4) new_dates 계산 → 5) shift_daily_records / reconcile_dates / reconcile_all_chips |
| After (#12) | 1) Mutator.apply_changes (setattr + pin 자동 흡수) → 3) status=CANCELLED 분기 → 4) new_dates 계산 → 5) 후속 처리 |

`db_reservation` 은 in-place 갱신 — `new_dates = (db_reservation.check_in_date, db_reservation.check_out_date)` 가 Mutator 호출 후 정확한 새 값 반환. 후속 분기 흐름 동일.

### 3-3. `manually_extended_until` 처리는 영향 없음

L353~L355 의 status=CANCELLED 시 `manually_extended_until=None` + `check_out_pinned=False` 클리어 (단계 #8):
- Mutator 가 `manually_extended_until` 안 만짐 (FIELD_PERMISSIONS 미등록 — but allow-all 정책이라 update_data 에 포함되면 setattr 됨)
- 다만 update_data 에 `manually_extended_until` 키가 들어오는 경우는 없음 (`reservation.dict(exclude_unset=True)` 가 빌더, Pydantic schema 에 manually_extended_until 없음 — `ReservationUpdate` 확인 필요)
- caller 가 별도로 None 클리어 → 그대로 유지

### 3-4. invariant check 분기 (L378~)

`constraint_changed` 가 True 인 경우 invariant check + unassign — 본 단계 #12 영향 없음. 동일 위치에서 동일 호출.

### 3-5. reconcile_all_chips 분기 (L443~)

`chip_affecting` 평가 → `reconcile_all_chips` 호출 — 본 단계 영향 없음.

---

## 4. 시나리오별 결과

| 시나리오 | Before (#11) | After (#12) | 판정 |
|---|---|---|---|
| 직원이 customer_name 만 변경 | setattr | Mutator setattr | ✅ |
| 직원이 check_in_date 변경 | setattr + pin=True | Mutator setattr + pin=True | ✅ |
| 드래그 (`dateCrossMutation`) → check_in/out 둘 다 | setattr + pin × 2 | Mutator setattr × 2 + pin × 2 | ✅ |
| 인원 변경 + `gender_manual=True` 자동 (L309~L311) | gender_manual auto-set 후 setattr | 동일 (auto-set 은 Mutator 호출 전 발생) | ✅ |
| status=CANCELLED | setattr + (캘러) manually_extended_until=None | Mutator setattr + 동일 caller 처리 | ✅ |
| frontend 가 의도치 않게 `naver_room_type` 보냄 | setattr (적용됨) | Mutator: never → skip | 🔵 보안 강화 (실제 발생 0) |

---

## 5. 영향받지 않음을 확인할 코드 경로

- L271 `update_data = reservation.dict(exclude_unset=True)` — 변경 0
- L309~L311 `gender_manual` auto-set — 변경 0
- L314 `old_dates = ...` — 변경 0
- L339~L350 status=CANCELLED stay_group unlink — 변경 0
- L353~L355 manually_extended_until 클리어 — 변경 0
- L383~L405 shift_daily_records / reconcile_dates / unassign — 변경 0
- L443~ reconcile_all_chips — 변경 0
- L455 `_to_response` — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/api/reservations.py` 에러 0
- [ ] **diff**: setattr 루프 + pin 세팅 7 라인 → Mutator import + apply 2 라인 (즉 -7/+2 = -5 라인)
- [ ] **외부 참조 (Mutator 호출 site)**: `grep -rn "ReservationMutator" app/` → 단계 #1 의 정의 1건 + 단계 #12 의 호출 1건 (reservations.py)
- [ ] **단위 시뮬레이션** (선택, 권장):
  ```python
  # update_data 가 check_in_date 포함 → pin 자동
  client.put(f"/reservations/{rid}", json={"check_in_date": "2026-05-20"})
  res = db.refresh(reservation)
  assert res.check_in_date == "2026-05-20"
  assert res.check_in_pinned is True
  # 미등록 필드 (notes) → allow-all
  client.put(f"/reservations/{rid}", json={"notes": "test"})
  assert res.notes == "test"
  ```
- [ ] **기존 pytest 회귀**: pass/fail 개수 #11 시점과 동일

---

## 7. 본 단계 이후의 후속 의존성

- **#13** `naver_sync._update_reservation` → Mutator.apply 호출
- **#14** `reservations_stay.py` extend/reduce → Mutator.apply 호출

---

## 8. 머지 후 다음 액션

`mutator-step-13-naver-sync-via-mutator.md` 작성.
