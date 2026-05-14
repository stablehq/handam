# 단계 #5 사전조사 — naver_sync `check_out_pinned` 가드 OR 추가

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §B
> 분류: ⚪ 동작 변화 없음 (단계 #7~#8 이후 의미 발생)
> 변경 규모: `app/services/naver_sync.py` 4 라인 추가

---

## 1. 목적

`naver_sync._update_reservation` 의 `check_out_date` 보호 분기 (L675~L702) 에 `check_out_pinned` 가드를 **OR 조건으로 병행** 추가. 기존 `manually_extended_until` 보호 로직은 그대로 유지 — 호환성 100%. 본 단계에서는 모든 레코드의 `check_out_pinned` 가 False (단계 #2~#3 default) 이므로 동작 변화 0.

단계 #15 (`manually_extended_until` deprecation) 까지 두 보호 메커니즘이 공존.

---

## 2. 변경 대상 코드

### `app/services/naver_sync.py` L674~L692 (incoming_end 분기 전체)

**Before** (실측):

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        if (
            existing.manually_extended_until
            and incoming_end < existing.check_out_date
            and incoming_end < existing.manually_extended_until
        ):
            # User manually extended — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                reservation_id=existing.id,
                incoming_end=incoming_end,
                existing_end=existing.check_out_date,
                manually_extended_until=existing.manually_extended_until,
                naver_booking_id=existing.naver_booking_id,
            )
            # skip overwrite
        else:
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
                reservation_id=existing.id,
                incoming_end=incoming_end,
                existing_end=existing.check_out_date,
                manually_extended_until=existing.manually_extended_until,
                naver_booking_id=existing.naver_booking_id,
            )
            # skip overwrite
        else:
```

**변경 내용**: 첫 번째 `if (...)` 의 조건에 OR 절을 추가. 나머지 라인 (diag 로그, else 분기, 본문) 모두 변경 0.

**변경 의도**:
- `manually_extended_until` 가드: "줄이는 방향만 보호" (`incoming < check_out_date AND incoming < manually_extended_until`)
- 신규 `check_out_pinned` 가드: "줄이는 방향만 보호" (`incoming < check_out_date`)
- 두 가드는 의미적으로 같고 — `check_out_pinned=True` 의 의미가 "수동으로 변경됨, 보호 필요"
- 둘 중 하나라도 만족하면 skip → 호환성 보존

---

## 3. 동작 동등성 근거

### 3-1. pin 상태별 진입 경로

| `manually_extended_until` | `check_out_pinned` | `incoming < check_out_date` | Before 결과 | After 결과 | 동등 |
|---|---|---|---|---|---|
| 값 있음, incoming < both | False | True | skip | skip | ✅ |
| 값 있음, incoming >= manually_extended_until | False | True | else 분기 (catch-up) | else 분기 (catch-up) | ✅ |
| 값 있음, incoming < both | False | False | else 분기 | else 분기 | ✅ |
| 없음 | False | * | else 분기 (기존 동작) | else 분기 (`check_out_pinned=False` 라 OR 새 절도 False) | ✅ |
| 없음 | True | True | (단계 #5 단독에선 발생 안 함 — #8 부터) | skip | 신규 동작 (단계 #8 이후) |
| 없음 | True | False | (단계 #5 단독에선 발생 안 함) | else 분기 (incoming 이 미래 → catch-up 격) | 신규 동작 |

**본 단계 머지 시점**: 모든 레코드 `check_out_pinned=False` → 신규 OR 절은 항상 False → 기존 분기 결과 100% 동일.

### 3-2. catch-up (else 분기) 영향

else 분기 안의 `manually_extended_until` catch-up 로직 (L693~L702) 은 변경 0:

```python
else:
    if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
        # Naver caught up — clear flag
        diag(...)
        existing.manually_extended_until = None
    existing.check_out_date = incoming_end
```

`check_out_pinned` 의 catch-up (자동 해제) 은 단계 #10 에서 별도로 처리. 본 단계는 catch-up 없음.

### 3-3. SQL 호출 / DB 행 비교

본 단계 변경은 Python 조건절만 추가. `existing.check_out_date` / `existing.manually_extended_until` 의 set 경로는 모두 else 분기 안. pinned=False 상태에서 OR 절이 False 라 분기 결과 동일 → INSERT/UPDATE 결과 동일.

---

## 4. 시나리오별 결과

| 시나리오 | Before | After (본 단계 단독) | 판정 |
|---|---|---|---|
| 일반 동기화, `check_out_date` 변경 없음 | 덮어씀 (값 동일, idempotent) | 동일 | ✅ |
| 일반 동기화, 사용자 미관여 | 덮어씀 | 동일 | ✅ |
| `manually_extended_until` 보호 케이스 (incoming < both) | skip | 동일 | ✅ |
| `manually_extended_until` catch-up | 플래그 해제 + 덮어씀 | 동일 | ✅ |
| 수동 PUT 으로 check_out_date 변경 → 5분 뒤 네이버 동기화 | 덮어씀 (버그 #4 의 부분 케이스) | 동일 — pinned False 라 가드 무력. **단계 #7 머지 후 해결** | ⚪ |
| `extend_stay` 후 동기화 | `manually_extended_until` 가드로 보호 | 동일 | ✅ |

---

## 5. 영향받지 않음을 확인할 코드 경로

- L674 `incoming_end = res_data.get("end_date")` — 변경 0
- L692~L702 else 분기 본문 (catch-up + 덮어쓰기) — 변경 0
- `manually_extended_until` 의 set 경로 (`reservations_stay.py:223`, `_do_reduce_extension`, `naver_sync.py` cancel 분기) — 변경 0
- `_create_reservation` (신규 예약) — 가드 무관
- 동일 함수의 다른 필드 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff**: 4 라인 추가, 다른 라인 변경 0 (특히 diag 로그 / else 분기 본문)
- [ ] **OR 조건 위치 정확**: `git diff` 결과가 §2 의 After 와 1:1 일치
- [ ] **들여쓰기**: `or (` 가 첫 `if (` 와 같은 들여쓰기 레벨 (괄호 그룹화)
- [ ] **기존 pytest 회귀**: pass/fail 개수 #4 시점과 동일
- [ ] **분기 logic 검증** (선택 — 단위 테스트):
  ```python
  # pinned=False, manually_extended_until 없음: 덮어씀 (기존)
  existing.check_out_pinned = False; existing.manually_extended_until = None
  existing.check_out_date = "2026-05-15"
  _update_reservation(db, existing, {..., "end_date": "2026-05-10"})
  assert existing.check_out_date == "2026-05-10"
  # pinned=True, incoming 작음: 보호
  existing.check_out_pinned = True; existing.check_out_date = "2026-05-15"
  _update_reservation(db, existing, {..., "end_date": "2026-05-10"})
  assert existing.check_out_date == "2026-05-15"
  ```

---

## 7. 본 단계 이후의 후속 의존성

- **#7** (reservations.py PUT 의 check_out_pinned 자동 세팅) — 본 단계의 가드가 비로소 의미 갖춤
- **#8** (extend_stay 의 check_out_pinned 자동 세팅) — 동일
- **#10** (catch-up: incoming > current 시 pin 해제) — 본 단계 OR 절과는 직교
- **#15** (`manually_extended_until` deprecation) — 본 단계의 첫 if 절 (3 조건) 을 삭제하고 OR 절만 남기는 작업

---

## 8. 미결 검토 항목

- [ ] **diag 로그 — pin 케이스 분리 여부**: 본 단계는 `manually_extended_until` 의 기존 로그를 그대로 재사용. detail 에 `manually_extended_until=existing.manually_extended_until` 가 None 으로 나갈 수 있음 (pinned=True 인데 manually_extended_until 은 없는 케이스). 본 단계 단독 머지 시에는 발생 0 (pinned 가 항상 False). #8 머지 후 발생 가능. 로깅 개선은 별도 PR 권장.

---

## 9. 머지 후 다음 액션

`mutator-step-06-manual-checkin-pin.md` 작성.
