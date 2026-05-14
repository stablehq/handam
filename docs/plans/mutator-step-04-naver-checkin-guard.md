# 단계 #4 사전조사 — naver_sync `check_in_pinned` 가드 추가

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §B
> 분류: ⚪ 동작 변화 없음 (단계 #6 이후 의미 발생)
> 변경 규모: `app/services/naver_sync.py` 3 라인 수정

---

## 1. 목적

`naver_sync._update_reservation` 의 `check_in_date` 무조건 덮어쓰기 (L672) 를 `check_in_pinned` 가드로 감싼다. 본 단계 시점에서는 모든 레코드의 `check_in_pinned` 가 False (단계 #2~#3 default) 이므로 동작 변화 0. 단계 #6 에서 수동 PUT 이 pin 을 세팅하면 이 가드가 비로소 효과를 발휘.

---

## 2. 변경 대상 코드

### `app/services/naver_sync.py` L670~L673

**Before** (실측 — sed 출력 그대로):

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    existing.check_in_date = res_data.get("date", existing.check_in_date)
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**After**:

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    if not existing.check_in_pinned:
        existing.check_in_date = res_data.get("date", existing.check_in_date)
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**변경 의도**:
- L672 `existing.check_in_date = ...` 를 `if not existing.check_in_pinned:` 분기 안으로 이동
- 다른 라인 변화 없음 (L670/L671/L673 그대로)
- `check_in_time` 은 보호 대상 아님 — 별도 컬럼, 동작 동등성 위해 외부에 유지

---

## 3. 동작 동등성 근거

### 3-1. pin 상태별 동작

| `existing.check_in_pinned` | Before | After | 동등 |
|---|---|---|---|
| `False` (단계 #2~#3 default — 모든 레코드) | `existing.check_in_date = ...` 실행 | 동일 — `if not False:` → 진입 | ✅ |
| `True` | (단계 #6 이전엔 발생 안 함) | `if not True:` → skip — 덮어쓰기 안 함 | 신규 동작 (단계 #6 이후) |

본 단계 머지 시점에는 **레코드 전체가 False** 라 분기 결과가 Before 와 100% 동일.

### 3-2. 시나리오별 결과

| 시나리오 | Before | After (본 단계 단독) | 판정 |
|---|---|---|---|
| 네이버 동기화 (신규 예약) | `_create_reservation` 경로 — 본 함수 진입 안 함 | 동일 | ✅ |
| 네이버 동기화 (기존 예약, check_in_pinned=False) | `existing.check_in_date` 덮어씀 | 동일 — `if not False:` 통과 | ✅ |
| 수동 PUT 으로 check_in_date 변경 후 5분 뒤 네이버 동기화 | 덮어씀 (버그 #3) | 동일 — pinned 가 False 라 가드 효과 0. 단계 #6 머지 후에야 해결 | ⚪ |
| `check_in_time` 만 바뀐 케이스 | L673 실행 | 동일 | ✅ |

### 3-3. SQL 호출 / DB 행 비교

`existing` 은 ORM 객체. 본 단계 변경은 Python 분기만 추가 — SQLAlchemy 의 `before_flush` 가 보는 dirty 필드 집합은 동일 (`check_in_pinned=False` 인 동안). INSERT/UPDATE 결과 동일.

### 3-4. 의도된 변화는 *언제* 발생하나

본 단계 #4 단독 머지: 변화 0 (모든 pinned=False).
단계 #6 머지 후: 수동 PUT 으로 check_in_date 변경된 레코드는 check_in_pinned=True → naver_sync 가 skip → 시나리오 #1/#3/#4 해결.

---

## 4. 영향받지 않음을 확인할 코드 경로

다음은 본 단계에서 변경 0:
- `_create_reservation` (L594) — 신규 예약은 가드 무관
- L674~ check_out_date 보호 로직 (`manually_extended_until` 기존 분기) — 단계 #5 에서 별도 처리
- 동일 함수의 다른 필드 (visitor_phone, naver_biz_item_id, naver_room_type, party_size, biz_item_name, booking_count, booking_options, special_requests, total_price, status, gender, age_group, ...) 모두 그대로
- 다른 caller (reservations.py, reservations_stay.py 등) 변경 0

---

## 5. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff 라인 수**: `git diff app/services/naver_sync.py` 결과 라인 추가 1, 삭제 0, 수정 1 (들여쓰기) — 총 변경 3 라인 (L672 → 분기 3줄)
- [ ] **외부 영향**: `git diff main -- app/` 가 본 파일 외 0 라인
- [ ] **기존 pytest 회귀**: pass/fail 개수가 #2~#3 시점과 동일
- [ ] **분기 logic 검증** (선택 — 단위 테스트로):
  ```python
  # pinned=False: 덮어씀
  existing.check_in_pinned = False; existing.check_in_date = "2026-05-10"
  _update_reservation(db, existing, {"date": "2026-05-15", ...})
  assert existing.check_in_date == "2026-05-15"
  # pinned=True: 보존
  existing.check_in_pinned = True; existing.check_in_date = "2026-05-10"
  _update_reservation(db, existing, {"date": "2026-05-15", ...})
  assert existing.check_in_date == "2026-05-10"
  ```

---

## 6. 본 단계 이후의 후속 의존성

- **#5** (check_out_pinned OR 조건) — 본 단계와 독립, 같은 함수 안의 다른 분기
- **#6** (수동 PUT 의 check_in_pinned 자동 세팅) — 본 단계의 가드가 비로소 의미를 가짐
- **#9** (catch-up: incoming > current 시 pin 해제) — 본 단계 이후

본 단계 단독 머지로는 의도된 동작 변화 0.

---

## 7. 미결 검토 항목

- [ ] **catch-up 정책 (#9)** 도입 전에 시나리오 검토 필요: pinned=True 인 채로 네이버가 "더 미래로" 옮긴 (실제 사용자 변경을 백엔드가 따라잡은) 경우의 처리. 본 단계 머지 후 사용자가 다음 사이클 동기화 때까지 pin 이 풀리지 않는 일시 상태가 존재 — **단계 #6 머지 전까지는 어차피 pin 이 안 세팅되므로 영향 0**, #9 도입 전 단순 운영 시나리오는 다음과 같다:
  1. 사용자가 수동 PUT 으로 check_in 변경 → pin=True (단계 #6)
  2. 네이버가 다음 사이클에 같은 값을 보내면 → 가드가 skip 해도 결과 동일 (값 같음)
  3. 네이버가 다른 값으로 catch-up → 가드가 skip → 사용자 입력 보존 (의도된 동작)
  4. 네이버가 "더 정확한 새 값" 으로 따라잡으면 → 가드가 skip → 사용자 입력 보존 (이건 #9 catch-up 정책 도입 후 자동 해제)

---

## 8. 머지 후 다음 액션

`mutator-step-05-naver-checkout-guard.md` 작성.
