# 단계 #11 사전조사 — `ReservationMutator.apply_changes()` 실제 구현

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §E
> 분류: ⚪ 동작 변화 없음 (caller 호출 시점에 발동, 본 단계 단독으로는 호출 0건)
> 변경 규모: `app/services/reservation_mutator.py` ~80 라인 실제 구현 (NotImplementedError 교체)

---

## 1. 목적

단계 #1 에서 `NotImplementedError` 만 raise 하던 `apply_changes()` 를 실제 구현으로 교체. 단계 #12~#14 의 caller 들이 호출하면 다음을 수행:
1. FIELD_PERMISSIONS 평가 — source 별 권한 검사
2. 권한 통과 필드만 setattr
3. `check_in_date` / `check_out_date` 변경 + `source=MANUAL` 시 pin 자동 세팅 (기존 #6~#8 의 pin 세팅 로직을 Mutator 내부로 흡수)
4. 적용된 변경 dict 반환 ({필드명: (old, new)})

본 단계 #11 단독 머지 시점에는 caller 가 여전히 setattr 직접 사용 — Mutator.apply 호출 0건이므로 동작 변화 0.

---

## 2. 정책 결정

### 2-1. FIELD_PERMISSIONS 미등록 필드 처리 (단계 #1 §8 미결)

| 옵션 | 동작 | 평가 |
|---|---|---|
| A. 거부 (`continue`) | 미등록 필드는 변경 안 됨 | 호환성 ↓, 새 필드 추가 시 매트릭스 갱신 필수, 디버깅 까다로움 |
| B. 통과 (`setattr` 그대로) | 미등록 필드는 무조건 적용 | 호환성 ↑, 점진적 매트릭스 확장 가능 | ✅ **선택** |

근거: 단계 #12~#14 의 caller 들이 setattr 루프 전체를 Mutator.apply 호출로 교체할 수 있도록 호환성 보장. 매트릭스 확장은 별도 PR 로 점진적.

### 2-2. `guarded` 필드 중 pin 컬럼 없는 것 처리

설계안 §3-3 의 FIELD_PERMISSIONS 에서 `guarded` 필드:
- `check_in_date` → `check_in_pinned` 컬럼 (단계 #2~#3)
- `check_out_date` → `check_out_pinned` 컬럼 (단계 #2~#3)
- `party_size`, `male_count`, `female_count`, `total_price` → 기존 보호 플래그 (`is_split_managed`, `gender_manual`) — **본 마이그레이션 범위 밖**

→ Mutator 의 guarded 평가는 **`check_in_pinned` / `check_out_pinned` 만**. 다른 guarded 필드는 기존 caller 의 보호 로직 (예: `naver_sync.py:720` 의 `is_split_managed`, `gender_manual` 분기) 가 그대로 처리 — Mutator 가 만지지 않음.

본 단계 시점에서는 caller 가 fields 에 다른 guarded 필드 (party_size 등) 를 넣어도 Mutator 는 단순히 setattr 만 함 (`always` 처럼 처리). 기존 보호는 caller 가 미리 분기에서 막음.

### 2-3. pin 자동 세팅 위치 (caller vs Mutator)

설계안 §3-5: pin 세팅을 Mutator 내부로 흡수.

| 옵션 | 평가 |
|---|---|
| A. caller 에 남기고 Mutator 는 setattr 만 | 단계 #6~#8 코드 유지 — Mutator 도입 효과 작음 |
| B. Mutator 내부로 흡수 — caller 는 fields 만 전달 | 단일 게이트웨이 의의 강화 | ✅ **선택** |

따라서 **#12~#14 에서 caller 의 pin 세팅 코드 (단계 #6~#8 에서 추가한 것) 를 제거**.

### 2-4. `_run_post_processing()` 본 단계 범위 외

설계안 §3-5 의 후처리 파이프라인 (`shift_daily_records`, `reconcile_dates`, `reconcile_all_chips`) 은 **별도 설계안** (`room-assignment-pipeline-design.md`) 의 lifecycle 함수들 책임. 본 단계 #11 에서는:
- `_run_post_processing` 미구현 — 향후 lifecycle 함수와 통합 시점에 결정
- caller (단계 #12~#14) 가 기존 후처리 호출 유지

---

## 3. 변경 대상 코드

### `app/services/reservation_mutator.py` — `apply_changes()` 본문 교체

**Before** (단계 #1 결과):

```python
class ReservationMutator:
    @staticmethod
    def apply_changes(
        db: "Session",
        reservation: "Reservation",
        source: ChangeSource,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """..."""
        raise NotImplementedError(
            "ReservationMutator.apply_changes is not implemented yet "
            "(see docs/plans/mutator-migration-plan.md step #11)."
        )
```

**After**:

```python
# 단계 #11: guarded 평가 시 참조할 pin 컬럼 매핑 (확장 가능)
# 다른 guarded 필드 (party_size, male_count, total_price) 는 기존 보호 플래그
# (is_split_managed, gender_manual) 가 caller 측에서 처리 — Mutator 가 만지지 않음
_PIN_ATTR_FOR: dict[str, str] = {
    "check_in_date": "check_in_pinned",
    "check_out_date": "check_out_pinned",
}


class ReservationMutator:
    """예약 필드 변경의 단일 진입점.

    단계 #11 에서 실제 구현. caller 가 source + fields dict 를 넘기면:
      1) FIELD_PERMISSIONS 로 source 별 권한 평가
      2) 권한 통과한 필드만 setattr
      3) check_in/out_date 변경 + source=MANUAL 시 pin 자동 세팅
      4) 적용 결과를 {필드명: (old, new)} 로 반환

    호출자는 본 함수의 결과 dict 로 "실제로 무엇이 변했나" 를 판단해서
    후속 처리 (shift_daily_records, reconcile_all_chips 등) 분기 가능.
    """

    @staticmethod
    def apply_changes(
        db: "Session",
        reservation: "Reservation",
        source: ChangeSource,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        applied: dict[str, Any] = {}

        for field, new_value in fields.items():
            # 1) 권한 평가
            perm_row = FIELD_PERMISSIONS.get(field)
            if perm_row is None:
                # 미등록 필드 — caller 의지 그대로 setattr (allow-all 정책, §2-1)
                permission = "always"
            else:
                permission = perm_row.get(source, "never")

            if permission == "never":
                continue

            if permission == "guarded":
                pin_attr = _PIN_ATTR_FOR.get(field)
                if pin_attr and getattr(reservation, pin_attr, False):
                    # pin 발동 — 덮어쓰기 skip
                    continue
                # pin_attr 없는 guarded 필드 (party_size, male_count 등):
                # 기존 caller 보호 로직 (is_split_managed, gender_manual) 가 미리 처리.
                # Mutator 단계에서는 always 처럼 통과.

            # 2) setattr
            old_value = getattr(reservation, field, None)
            if old_value != new_value:
                setattr(reservation, field, new_value)
                applied[field] = (old_value, new_value)

        # 3) source=MANUAL 의 날짜 변경 시 pin 자동 세팅
        if source == ChangeSource.MANUAL:
            if "check_in_date" in applied:
                reservation.check_in_pinned = True
            if "check_out_date" in applied:
                reservation.check_out_pinned = True

        return applied
```

**변경 내용**:
- `_PIN_ATTR_FOR` 모듈 레벨 상수 추가 (확장 가능)
- `apply_changes` 본문을 `NotImplementedError` 에서 실제 로직으로 교체 (~45 라인)
- docstring 갱신

---

## 4. 동작 동등성 / 의도된 변화

### 4-1. 단계 #11 단독 머지 시점의 영향

**caller 가 Mutator.apply 를 호출하지 않음** (단계 #12~#14 미머지 상태):
- 모든 caller 가 setattr 직접 — 기존 동작 100%
- Mutator.apply 는 정의됐지만 호출 0건 → 동작 변화 0
- `NotImplementedError` 가 사라졌으니 실수로 호출해도 raise 안 됨 — silent skip 위험 ↑?

→ §6 검증 체크리스트에 "외부 참조 0건" 확인 포함 (단계 #1 과 동일).

### 4-2. 단계 #12~#14 시점에서의 동작 매트릭스 검증

caller 가 setattr 루프 + pin 자동 세팅을 Mutator.apply 호출로 교체했을 때, 결과가 단계 #1~#10 와 동등해야 함.

**MANUAL source — `reservations.py PUT` (단계 #12)**:

| 입력 | 단계 #10 결과 | 단계 #12 (Mutator) 결과 | 판정 |
|---|---|---|---|
| `{"customer_name": "X"}` (미등록 필드 케이스 없음 — name 은 always 등록됨) | setattr | Mutator: permission="always" → setattr | ✅ |
| `{"check_in_date": "2026-05-15"}` | setattr + #6 pin=True | Mutator: setattr + #3 pin=True | ✅ |
| `{"check_in_date": "2026-05-15", "check_out_date": "2026-05-20"}` | setattr × 2 + pin × 2 | Mutator: setattr × 2 + pin × 2 | ✅ |
| `{"status": "CANCELLED"}` | setattr | Mutator: setattr (always) | ✅ |
| `{"male_count": 5}` | setattr (caller 가 gender_manual 별도 set) | Mutator: setattr (guarded but pin_attr 없음 → always 통과). caller 가 gender_manual 별도 set (변경 0) | ✅ |
| `{"section": "room"}` | setattr | Mutator: always → setattr | ✅ |

**NAVER source — `naver_sync._update_reservation` (단계 #13)**:

| 입력 | 단계 #10 결과 | 단계 #13 (Mutator) 결과 | 판정 |
|---|---|---|---|
| `{"check_in_date": new}` + pinned=False | setattr | Mutator: guarded → pin_attr=False → setattr | ✅ |
| `{"check_in_date": new}` + pinned=True + new != existing | skip | Mutator: guarded → pin_attr=True → continue (skip) | ✅ |
| `{"check_in_date": new}` + pinned=True + new == existing | skip + #9 catch-up clear pin | **본 단계 #11 만으로는 catch-up 안 함** — caller (#13) 가 별도로 catch-up 분기 처리 또는 Mutator 내부에 흡수 결정 | ⚠️ |
| `{"customer_name": "X"}` | setattr | Mutator: always → setattr | ✅ |
| `{"party_size": 5}` + is_split_managed=True | caller 분기에서 skip (fields 에 안 넣음) | caller 가 미리 fields 에서 제외 | ✅ |
| `{"section": "room"}` | naver_sync 가 안 만짐 (caller 가 fields 에 안 넣음) | 동일 | ✅ |

→ **검토 항목**: catch-up (#9, #10) 로직을 Mutator 내부로 흡수할지 vs caller (#13) 에 남길지. 후자가 본 단계 #11 의 단순성을 유지. 흡수는 별도 단계로 (단계 #13 결정).

### 4-3. permission="never" 케이스

NAVER source 가 `section` 필드 변경 시도:
- FIELD_PERMISSIONS["section"][NAVER] == "never"
- Mutator: `continue` → setattr 안 함

기존 naver_sync 동작: `_update_reservation` 이 `section` 자체를 fields 에 안 넣음 (현재 코드 확인됨).

→ 본 단계 #11 만으로는 영향 0. 단계 #13 에서 caller 가 fields 에 section 을 의도치 않게 넣더라도 Mutator 가 차단 — 안전망 강화.

### 4-4. SYSTEM source

본 마이그레이션 범위에서 SYSTEM source caller 가 명확하게 도입되는 단계 없음. apply 메서드는 정의만 — SYSTEM source 호출 시 매트릭스 따라 동작:
- `check_in_date` / `check_out_date`: "always"
- `customer_name`, `phone`, `visitor_name` 등: "never"
- `section`: "always"

향후 자동 객실 배정 / push-out cleanup 등에서 활용. 본 단계는 인터페이스만.

---

## 5. 영향받지 않음을 확인할 코드 경로

- `ChangeSource` enum — 변경 0
- `FIELD_PERMISSIONS` 매트릭스 — 변경 0
- 모든 caller (reservations.py, naver_sync.py, reservations_stay.py 등) — 변경 0
- 다른 services / scheduler — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/reservation_mutator.py` 에러 0
- [ ] **import 가능**: `python -c "from app.services.reservation_mutator import ReservationMutator; print(ReservationMutator.apply_changes.__doc__)"`
- [ ] **외부 참조 0건** (단계 #12~#14 미머지 시): `grep -rn "ReservationMutator\|apply_changes" app/ tests/ | grep -v reservation_mutator.py | grep -v __pycache__` → 0건
- [ ] **단위 테스트** (선택, 권장):
  ```python
  from app.services.reservation_mutator import ReservationMutator, ChangeSource

  # 1) NAVER + pinned=False → setattr 진행
  res = make_reservation(check_in_date="2026-05-15", check_in_pinned=False)
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.NAVER, {"check_in_date": "2026-05-20"})
  assert applied == {"check_in_date": ("2026-05-15", "2026-05-20")}
  assert res.check_in_date == "2026-05-20"
  assert res.check_in_pinned is False  # NAVER 는 pin 자동 세팅 안 함

  # 2) NAVER + pinned=True → skip
  res = make_reservation(check_in_date="2026-05-15", check_in_pinned=True)
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.NAVER, {"check_in_date": "2026-05-20"})
  assert applied == {}
  assert res.check_in_date == "2026-05-15"

  # 3) MANUAL + check_in_date 변경 → pin 자동 세팅
  res = make_reservation(check_in_date="2026-05-15", check_in_pinned=False)
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.MANUAL, {"check_in_date": "2026-05-20"})
  assert applied == {"check_in_date": ("2026-05-15", "2026-05-20")}
  assert res.check_in_pinned is True  # MANUAL pin 자동

  # 4) 미등록 필드 통과 (allow-all 정책)
  res = make_reservation()
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.MANUAL, {"notes": "X"})
  assert applied == {"notes": (None, "X")}
  assert res.notes == "X"

  # 5) NAVER + section (never) → skip
  res = make_reservation(section="room")
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.NAVER, {"section": "party"})
  assert applied == {}
  assert res.section == "room"

  # 6) 값 동일 → applied 에 미포함
  res = make_reservation(customer_name="X")
  applied = ReservationMutator.apply_changes(db, res, ChangeSource.MANUAL, {"customer_name": "X"})
  assert applied == {}
  ```
- [ ] **기존 pytest 회귀**: pass/fail 개수 #10 시점과 동일 (caller 가 호출 안 하므로 동작 변화 0)

---

## 7. 본 단계 이후의 후속 의존성

- **#12** reservations.py PUT → Mutator.apply 호출 (단계 #6~#7 의 pin 세팅 흡수)
- **#13** naver_sync._update_reservation → Mutator.apply 호출. catch-up (#9~#10) 처리 방식 결정:
  - 옵션 A: caller (#13) 에서 catch-up 분기 처리, Mutator 는 setattr/skip 만
  - 옵션 B: Mutator 내부에서 catch-up 처리 (`source=NAVER` 분기 추가)
- **#14** extend_stay / reduce_extension → Mutator.apply 호출 (단계 #8 의 pin 세팅 흡수)

---

## 8. 미결 검토 항목

- [ ] catch-up 로직 (#9, #10) 의 위치 — caller vs Mutator 내부. **#13 사전조사에서 결정**.
- [ ] `_run_post_processing()` 도입 시점 — 본 단계 #11 미구현. lifecycle 함수 도입 (별도 마일스톤) 시 결정.
- [ ] `is_split_managed` / `gender_manual` 보호 플래그 — 본 마이그레이션 범위 외. 별도 PR.

---

## 9. 머지 후 다음 액션

`mutator-step-12-reservations-put-via-mutator.md` 작성.
