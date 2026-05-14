# 단계 #14 사전조사 — `extend_stay` / `_do_reduce_extension` 의 check_out_date 를 Mutator 로 위임

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §E
> 분류: ⚫ 리팩토링 — 동작 동등성 보장
> 변경 규모: `app/api/reservations_stay.py` 2개 라인 교체

---

## 1. 목적

연박 연장 (`extend_stay`) / 축소 (`_do_reduce_extension`) 시 `original.check_out_date = new_end_str` 직접 대입을 Mutator.apply 호출로 교체. Mutator 가 MANUAL source 의 자동 `check_out_pinned=True` 세팅을 흡수.

`manually_extended_until` 의 set/clear (단계 #8 에서 추가) 와 caller 의 명시적 `check_out_pinned` 라인 (단계 #8) 은 **그대로 유지** — 안전망 (Mutator 의 자동 세팅과 idempotent).

---

## 2. 변경 대상 코드

### 2-1. `app/api/reservations_stay.py` L221~L226 (`extend_stay`)

**Before** (단계 #8 머지 결과):

```python
    # 3. Extend end_date
    from app.services.consecutive_stay import compute_is_long_stay
    original.check_out_date = new_end_str
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()
```

**After**:

```python
    # 3. Extend end_date
    from app.services.consecutive_stay import compute_is_long_stay
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True  # Mutator 가 MANUAL→자동 True, 안전망으로 명시 유지
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()
```

**변경 내용**:
- `original.check_out_date = new_end_str` → Mutator.apply 호출로 교체
- `manually_extended_until = new_end_str` 그대로 유지 (Mutator 가 안 만짐)
- `check_out_pinned = True` 명시 라인 유지 — Mutator 의 자동 세팅과 idempotent, silent regression 안전망

### 2-2. `app/api/reservations_stay.py` L431~L447 (`_do_reduce_extension`)

**Before** (단계 #8 머지 결과):

```python
    original.check_out_date = new_end_str
    # Clear flag when fully retracted to a 1-night (or shorter) stay — naver_sync resumes normal sync
    if days_remaining <= 1:
        original.manually_extended_until = None
        original.check_out_pinned = False
        diag(
            "reduce_extension.flag_cleared",
            level="critical",
            reservation_id=reservation_id,
            new_end=new_end_str,
            days_remaining=days_remaining,
        )
    else:
        original.manually_extended_until = new_end_str
        original.check_out_pinned = True
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()
```

**After**:

```python
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
    # Clear flag when fully retracted to a 1-night (or shorter) stay — naver_sync resumes normal sync
    if days_remaining <= 1:
        original.manually_extended_until = None
        original.check_out_pinned = False  # Mutator 가 MANUAL→자동 True 였으나 완전 축소 케이스는 False 로 override
        diag(
            "reduce_extension.flag_cleared",
            level="critical",
            reservation_id=reservation_id,
            new_end=new_end_str,
            days_remaining=days_remaining,
        )
    else:
        original.manually_extended_until = new_end_str
        original.check_out_pinned = True  # Mutator 자동 True 와 idempotent (안전망)
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()
```

**변경 내용**:
- `original.check_out_date = new_end_str` → Mutator.apply 호출로 교체
- `if days_remaining <= 1` 분기 안의 `check_out_pinned = False` 명시 라인은 그대로 — Mutator 가 자동으로 True 한 것을 caller 가 다시 False 로 override (의도된 동작: 완전 축소 시 보호 해제)
- `else` 분기의 `check_out_pinned = True` 도 그대로 — Mutator 자동 세팅과 동일 결과 (idempotent 안전망)
- diag 로깅, `manually_extended_until` set/clear 모두 변경 0

---

## 3. 동작 동등성

### 3-1. extend_stay 매트릭스

| 단계 | 단계 #8 결과 (Before) | 단계 #14 결과 (After) |
|---|---|---|
| 1) check_out_date 변경 | `original.check_out_date = new_end_str` | `ReservationMutator.apply(MANUAL, {"check_out_date": new_end_str})` |
| 1-1) Mutator 내부 setattr | (직접) | guarded → pin_attr (check_out_pinned)=False 기존 → setattr |
| 1-2) Mutator MANUAL 자동 pin | (없음) | `original.check_out_pinned = True` (Mutator 내부) |
| 2) `manually_extended_until = new_end_str` | 동일 | 동일 |
| 3) `check_out_pinned = True` (caller 명시) | True 로 세팅 | True 로 세팅 (Mutator 자동 True 와 idempotent) |

→ 최종 상태 동일. `check_out_pinned=True` 가 한 번 vs 두 번 세팅되는 차이만 (idempotent).

### 3-2. _do_reduce_extension 매트릭스

**Case A — 완전 축소 (days_remaining ≤ 1)**:

| 단계 | Before | After |
|---|---|---|
| 1) check_out_date 변경 | 직접 대입 | Mutator.apply → check_out_pinned=True 자동 (MANUAL) |
| 2) `manually_extended_until = None` | 동일 | 동일 |
| 3) `check_out_pinned = False` | False 세팅 | False 세팅 (Mutator 의 True 를 override) |

→ 최종 상태: `check_out_pinned=False`. 동일.

**Case B — 부분 축소 (days_remaining > 1)**:

| 단계 | Before | After |
|---|---|---|
| 1) check_out_date 변경 | 직접 대입 | Mutator.apply → check_out_pinned=True 자동 |
| 2) `manually_extended_until = new_end_str` | 동일 | 동일 |
| 3) `check_out_pinned = True` | True 세팅 | True 세팅 (idempotent) |

→ 최종 상태: `check_out_pinned=True`. 동일.

### 3-3. 사전 조건 — `original.check_out_pinned` 의 호출 시점 상태

extend_stay / reduce 진입 시점에 `original.check_out_pinned` 가 어떤 값이든:
- Mutator.apply 의 guarded 평가: 들어가기 전 pinned=True 면 skip 가능
  - 단 extend_stay 의 경우: 사용자가 이미 한 번 extend 해서 pinned=True 인 상태에서 또 extend → check_out_pinned=True → Mutator 가 skip → setattr 안 됨 → ❌ check_out_date 갱신 누락!

**위험 발견**: pinned=True 상태에서 또 extend 호출 시 Mutator 가 skip → 의도와 다름.

**해결 옵션**:
1. extend_stay 가 Mutator 호출 전에 `check_out_pinned = False` 로 미리 풀기 → 그러나 사용자 보호 의도 깨짐
2. Mutator 가 MANUAL source 의 guarded 평가를 우회 — `MANUAL` 권한은 "always" 이므로 pin 무시
3. FIELD_PERMISSIONS 의 `check_out_date` MANUAL 권한이 "always" 인지 재확인

**FIELD_PERMISSIONS 확인**:
```python
"check_out_date":   {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
```

→ `MANUAL` 권한은 "always". Mutator 코드:
```python
permission = perm_row.get(source, "never")
if permission == "never": continue
if permission == "guarded": ... pin 평가
# always → 분기 안 함, 바로 setattr
```

즉 MANUAL 은 pin 무관 — 항상 setattr. ✅ 위 우려는 잘못된 분석. extend_stay/reduce 는 MANUAL 이라 항상 통과.

→ **위 §3-1, §3-2 매트릭스 유효**.

### 3-4. NAVER source 의 영향 없음

본 단계는 MANUAL caller 만 변경. naver_sync (#13) 은 NAVER, 영향 없음. extend/reduce 는 항상 MANUAL — caller 가 명시.

---

## 4. 영향받지 않음을 확인할 코드 경로

- extend_stay 의 conflict check, assign_room, chip reconcile — 변경 0
- _do_reduce_extension 의 RA 삭제, chip reconcile, diag 로깅 — 변경 0
- reduce_extension HTTP 핸들러 + cancel_extend_stay 핸들러 (둘 다 _do_reduce_extension 호출) — 변경 0
- `manually_extended_until` set/clear (단계 #8) — 변경 0
- `check_out_pinned` 명시 라인 (단계 #8) — 변경 0 (안전망 유지)

---

## 5. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/api/reservations_stay.py` 에러 0
- [ ] **diff**: 각 함수에서 `check_out_date = new_end_str` 1 라인 → Mutator import + apply 2 라인 (즉 +2/+2)
- [ ] **Mutator 호출 site (전체)**: `grep -rn "ReservationMutator" app/` → reservations.py + naver_sync.py × 2 + reservations_stay.py × 2 = 5 호출
- [ ] **extend_stay 후 상태 검증**:
  - `check_out_date` 가 새 날짜로 설정됨
  - `check_out_pinned = True` (Mutator 자동 + caller 명시)
  - `manually_extended_until = new_end_str`
- [ ] **reduce 완전 축소 후 상태**:
  - `check_out_pinned = False` (caller 가 Mutator True 를 override)
  - `manually_extended_until = None`
- [ ] **reduce 부분 축소 후 상태**:
  - `check_out_pinned = True` (idempotent)
  - `manually_extended_until = new_end_str`
- [ ] **기존 pytest 회귀**: pass/fail 개수 #13 시점과 동일

---

## 6. 본 단계 이후의 후속 의존성

- **#15** `manually_extended_until` deprecation (별도 마일스톤) — 본 단계의 `manually_extended_until` 라인들을 모두 제거할 수 있음 (caller 의 명시 `check_out_pinned` 라인은 Mutator 자동 세팅에 의존, 안전망으로 유지 또는 제거 결정)

---

## 7. 머지 후 다음 액션

`mutator-step-15-manually-extended-until-deprecation.md` 작성 (별도 마일스톤 — 본 마이그레이션 핫픽스 분기점 이후).
