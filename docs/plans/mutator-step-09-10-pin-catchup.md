# 단계 #9~#10 사전조사 — pin 자동 해제 (catch-up)

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §D
> 분류: 🔵 **의도된 동작 변화** — pin 의 영구 잔존을 방지, 기존 `manually_extended_until` catch-up 의미와 일치
> 변경 규모: `app/services/naver_sync.py` ~7 라인 추가

---

## 1. 목적

`naver_sync._update_reservation` 가 pin 된 레코드를 처리할 때, 네이버 측 값이 사용자 의도 값에 **도달** 한 경우 pin 을 자동 해제. 영구 잔존 방지 + 운영자가 매번 수동 해제할 필요 없음.

기존 `manually_extended_until` 의 catch-up (`incoming_end >= manually_extended_until` → `manually_extended_until = None`) 의미를 일반화.

---

## 2. 정책 결정

### 2-1. catch-up 조건

| 필드 | 조건 | 근거 |
|---|---|---|
| `check_in_pinned` | `incoming_check_in == existing.check_in_date` | 사용자 의도 값에 도달했을 때만 해제. 줄어들든 늘어나든 다른 값은 보호 유지 (운영자 명시적 PUT 으로 해제) |
| `check_out_pinned` | `incoming_end >= existing.check_out_date` | 기존 `manually_extended_until` catch-up 과 동일. else 분기 (보호 발동 안 함) 에 진입했다는 건 이미 `incoming >= existing` 케이스 |

### 2-2. 비대칭 사유

- `check_out_date` 는 "연장 보호" 의미 (사용자가 늘렸는데 네이버가 따라잡으면 해제). `>=` 가 자연스러움.
- `check_in_date` 는 어느 방향이든 변경 가능 (당기거나 늦추거나). equality 가 보수적.

### 2-3. 대안 검토

| 정책 | 장점 | 단점 | 채택 |
|---|---|---|---|
| catch-up 없음 (영구 pin) | silent regression 0 | pin 잔존, 운영자 매번 수동 해제 | ❌ |
| `incoming != existing` 시 해제 (강력) | pin 잔존 없음 | 운영자가 네이버에서 의도적으로 다른 값으로 바꾼 경우도 사용자 의도 무시 | ❌ |
| `incoming == existing` (보수) — check_in | 사용자 의도 영구 보존 | 운영자가 네이버 측 변경하려면 PUT 으로 pin 명시 해제 필요 | ✅ |
| `incoming >= existing` (연장 catch-up) — check_out | 기존 동작과 100% 일관 | 단방향만 (늘리는 catch-up) | ✅ |

---

## 3. 변경 대상 코드

### 3-1. `app/services/naver_sync.py` L672 부근 (check_in_pinned catch-up — 단계 #9)

**Before** (단계 #4 머지 결과):

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    if not existing.check_in_pinned:
        existing.check_in_date = res_data.get("date", existing.check_in_date)
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**After**:

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    incoming_check_in = res_data.get("date", existing.check_in_date)
    if not existing.check_in_pinned:
        existing.check_in_date = incoming_check_in
    elif incoming_check_in == existing.check_in_date:
        # Naver caught up to user-set value — clear pin
        existing.check_in_pinned = False
        diag(
            "naver_sync.check_in_pin_cleared",
            level="critical",
            reservation_id=existing.id,
            check_in_date=existing.check_in_date,
        )
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**변경 내용**:
- `res_data.get("date", ...)` 를 별도 변수 `incoming_check_in` 으로 추출 (조건문에서 두 번 참조)
- `elif incoming_check_in == existing.check_in_date:` 분기 추가 — pin=True 이면서 네이버 값이 사용자 의도와 같으면 pin 해제
- diag 로깅 — catch-up 이력 추적

### 3-2. `app/services/naver_sync.py` L685 부근 (check_out_pinned catch-up — 단계 #10)

**Before** (단계 #5 + #8 머지 결과):

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        if (
            existing.manually_extended_until
            and incoming_end < existing.check_out_date
            and incoming_end < existing.manually_extended_until
        ) or (
            existing.check_out_pinned
            and incoming_end < existing.check_out_date
        ):
            # User manually extended — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                ...
            )
            # skip overwrite
        else:
            if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
                # Naver caught up — clear flag
                diag(
                    "naver_sync.user_extension_overridden",
                    level="critical",
                    ...
                )
                existing.manually_extended_until = None
            existing.check_out_date = incoming_end
```

**After**:

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        if (
            existing.manually_extended_until
            and incoming_end < existing.check_out_date
            and incoming_end < existing.manually_extended_until
        ) or (
            existing.check_out_pinned
            and incoming_end < existing.check_out_date
        ):
            # User manually extended — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                ...
            )
            # skip overwrite
        else:
            if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
                # Naver caught up — clear flag
                diag(
                    "naver_sync.user_extension_overridden",
                    level="critical",
                    ...
                )
                existing.manually_extended_until = None
            if existing.check_out_pinned and incoming_end >= existing.check_out_date:
                # Naver caught up to user-set value — clear pin
                existing.check_out_pinned = False
                diag(
                    "naver_sync.check_out_pin_cleared",
                    level="critical",
                    reservation_id=existing.id,
                    check_out_date=existing.check_out_date,
                    incoming_end=incoming_end,
                )
            existing.check_out_date = incoming_end
```

**변경 내용**:
- else 분기 안 `existing.check_out_date = incoming_end` 직전에 4 라인 추가
- `manually_extended_until` catch-up 패턴과 동일 구조

---

## 4. 동작 동등성 / 의도된 변화

### 4-1. catch-up 발동 조건 매트릭스 — check_in

| `check_in_pinned` | `incoming == existing` | Before (#4) | After (#9) | 판정 |
|---|---|---|---|---|
| False | 무관 | 덮어씀 | 동일 — 첫 분기 통과 | ✅ |
| True | True | skip (값 동일 — 덮어쓰기 의미 없음) | pin=False, 값은 그대로 (덮어쓰기 안 함) | 🔵 의도 (pin 해제만) |
| True | False | skip | 동일 — elif 조건 False | ✅ |

### 4-2. catch-up 발동 조건 매트릭스 — check_out

`else` 분기 진입 조건: 보호 발동 안 함 = (`manually_extended_until` 가드 False) AND (`check_out_pinned and incoming < existing.check_out_date` False)

| `check_out_pinned` | `incoming >= existing.check_out_date` | else 진입? | Before (#5+#8) | After (#10) | 판정 |
|---|---|---|---|---|---|
| False | * | 첫 절 manually_extended_until 따라 | 덮어씀 | 동일 | ✅ |
| True | True | 진입 (OR 절의 두 조건 중 `incoming < existing` False) | check_out 덮어씀, pin 잔존 | check_out 덮어씀 + pin=False | 🔵 의도 (pin 해제 추가) |
| True | False (`incoming < existing`) | 진입 안 함 (OR 절 True → skip) | skip | 동일 | ✅ |

### 4-3. 의도된 변화 — pin 잔존 시나리오 해소

| 시나리오 | Before (#1~#8) | After (#9+#10) |
|---|---|---|
| 사용자 PUT 으로 check_in=5/15 → 네이버에서 5/15 반영 → 동기화 | pin=True 영구, 매 sync 마다 skip 로그만 쌓임 | 첫 sync 에서 pin=False 자동 해제 → 다음부터 정상 동기화 |
| extend_stay 5/16 → 5/20 → 네이버에서 5/20 반영 | `manually_extended_until=None` 은 됐지만 `check_out_pinned=True` 잔존 | `check_out_pinned=False` 까지 자동 해제 (1:1 매핑 유지) |

---

## 5. 영향받지 않음을 확인할 코드 경로

- L670 `old_date = existing.check_in_date` — 변경 0
- L673 `existing.check_in_time = ...` — 변경 0 (catch-up 분기 밖)
- L674 `incoming_end = res_data.get("end_date")` — 변경 0
- 첫 if 절 (보호 발동) — 변경 0
- else 분기의 `manually_extended_until` catch-up — 변경 0
- 다른 caller (reservations.py, reservations_stay.py 등) — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff**: check_in 분기 +8 라인, check_out 분기 +10 라인 (diag 로깅 포함)
- [ ] **catch-up 시나리오 단위 검증**:
  - check_in: pin=True, existing.check_in_date="2026-05-15", incoming="2026-05-15" → pin=False 결과
  - check_in: pin=True, existing.check_in_date="2026-05-15", incoming="2026-05-20" → pin=True 유지, existing.check_in_date="2026-05-15" 유지
  - check_out: pin=True, existing.check_out_date="2026-05-20", incoming="2026-05-25" → pin=False 결과, existing.check_out_date="2026-05-25"
- [ ] **기존 catch-up (manually_extended_until) 회귀**:
  - manually_extended_until="2026-05-20", incoming="2026-05-20" → manually_extended_until=None (기존 동작 유지)
- [ ] **diag 로깅 확인**: 위 시나리오 실행 시 `naver_sync.check_in_pin_cleared` / `naver_sync.check_out_pin_cleared` 로그 발생

---

## 7. 본 단계 이후의 후속 의존성

- **#11~#14** Mutator apply 도입 시 본 단계의 catch-up 로직을 Mutator 내부로 흡수 (네이버 source 분기)
- **#15** `manually_extended_until` deprecation 시 본 단계의 `check_out_pinned` catch-up 만 남기고 기존 catch-up 제거

---

## 8. 머지 후 다음 액션

`mutator-step-11-apply-implementation.md` 작성.
