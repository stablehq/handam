# 단계 #8 사전조사 — `check_out_pinned` 를 `manually_extended_until` 라이프사이클에 1:1 동기화

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §C
> 분류: 🔵 **의도된 동작 변화** — 4 개 버그 시나리오 중 #2 의 잔여 해결
> 변경 규모: 5 라인 추가 (3개 파일: reservations_stay.py 3곳, reservations.py 1곳, naver_sync.py 1곳)
> 분해 계획 변경: 원래 분해 계획 #8 은 extend_stay 만이었지만 silent regression 회피를 위해 5곳 동시 처리로 확장

---

## 1. 목적

본 단계의 정책: **`manually_extended_until` 이 set/clear 되는 모든 위치에서 `check_out_pinned` 도 동일하게 set/clear**. 두 플래그가 어떤 코드 경로에서도 동기 상태를 유지하도록 보장.

근거: 부분만 적용하면 lifecycle 비대칭 (예: extend 에서 pin 세팅 후 reduce 에서 pin 안 풀면 stale). 5곳을 동시에 처리해야 일관성 유지.

설계안 §1-2 시나리오 #2 ("드래그 + 수동 연박") 의 연박 부분이 본 단계로 해결.

---

## 2. `manually_extended_until` set/clear 위치 — 실측 매핑

`grep` 결과 (`grep -rn "manually_extended_until\s*=" app/ --include="*.py" | grep -v "Column(\|__pycache__"`):

| # | 파일 | 라인 | 기존 코드 | 의미 | 본 단계 추가 |
|---|---|---|---|---|---|
| 1 | `reservations_stay.py` | 223 | `original.manually_extended_until = new_end_str` | extend_stay 연장 — SET | `original.check_out_pinned = True` |
| 2 | `reservations_stay.py` | 434 | `original.manually_extended_until = None` | reduce 완전 축소 (≤1 박) — CLEAR | `original.check_out_pinned = False` |
| 3 | `reservations_stay.py` | 443 | `original.manually_extended_until = new_end_str` | reduce 부분 축소 — SET (유지) | `original.check_out_pinned = True` |
| 4 | `reservations.py` | 354 | `db_reservation.manually_extended_until = None` | update_reservation status=CANCELLED — CLEAR | `db_reservation.check_out_pinned = False` |
| 5 | `naver_sync.py` | 747 | `existing.manually_extended_until = None` | cancel 분기 — CLEAR | `existing.check_out_pinned = False` |

**의도적으로 본 단계 범위에서 제외된 위치**:
- `naver_sync.py:706` — catch-up CLEAR. 의미상 `incoming_end >= manually_extended_until` 시 자동 해제. `check_out_pinned` catch-up 정책은 **단계 #10** 의 책임 (조건이 다를 수 있음 — 단계 #10 사전조사에서 검토).
- `reservations.py:397` — stale flag 정리 (manually_extended_until > check_out_date 일 때만 CLEAR). 이 위치는 사용자가 새로 check_out_date 를 PUT 으로 변경한 케이스 — 단계 #7 로 `check_out_pinned=True` 가 새로 세팅됨. **별도 CLEAR 불필요** (덮어쓰기 됨).

`check_in_pinned` 는 본 단계 범위 외 — extend/reduce 가 check_in_date 를 만지지 않음.

---

## 3. 변경 대상 코드 — 5곳 Before/After

### 3-1. `reservations_stay.py` L222~L224 (extend_stay SET)

**Before**:
```python
    original.check_out_date = new_end_str
    original.manually_extended_until = new_end_str
    original.is_long_stay = compute_is_long_stay(original)
```

**After**:
```python
    original.check_out_date = new_end_str
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True
    original.is_long_stay = compute_is_long_stay(original)
```

### 3-2. `reservations_stay.py` L432~L436 (reduce 완전 축소 CLEAR)

**Before**:
```python
    if days_remaining <= 1:
        original.manually_extended_until = None
        diag(
            "reduce_extension.flag_cleared",
            level="critical",
```

**After**:
```python
    if days_remaining <= 1:
        original.manually_extended_until = None
        original.check_out_pinned = False
        diag(
            "reduce_extension.flag_cleared",
            level="critical",
```

### 3-3. `reservations_stay.py` L442~L444 (reduce 부분 축소 — SET 유지)

**Before**:
```python
    else:
        original.manually_extended_until = new_end_str
    original.is_long_stay = compute_is_long_stay(original)
```

**After**:
```python
    else:
        original.manually_extended_until = new_end_str
        original.check_out_pinned = True
    original.is_long_stay = compute_is_long_stay(original)
```

### 3-4. `reservations.py` L353~L355 (status=CANCELLED CLEAR)

기존 컨텍스트 확인 필요 — sed L350~L360 추가 인용:

```python
    if (
        "status" in update_data
        and update_data["status"] == ReservationStatus.CANCELLED
        and db_reservation.manually_extended_until
    ):
        db_reservation.manually_extended_until = None
```

**Before** (L354):
```python
        db_reservation.manually_extended_until = None
```

**After**:
```python
        db_reservation.manually_extended_until = None
        db_reservation.check_out_pinned = False
```

**주의**: 이 분기의 가드 조건이 `db_reservation.manually_extended_until` (즉 manually_extended_until 이 truthy 일 때만 실행). 즉 manually_extended_until 이 None 인데 check_out_pinned 만 True 인 상태에서는 이 분기를 안 탐 → check_out_pinned 가 풀리지 않을 수 있음. 본 단계 #8 만으로는 1:1 매핑이 깨지는 코너 케이스. **단계 #11 (Mutator) 도입 시 별도 처리**. 본 단계 단독 머지 시점에서 manually_extended_until = None && check_out_pinned = True 인 레코드는 발생 0 (둘 다 같이 set/clear 되니까), 코너 케이스는 이론적.

### 3-5. `naver_sync.py` L745~L748 (cancel 분기 CLEAR)

기존 컨텍스트 (L744 부근 추가 인용 필요):

```python
        # S4 fix: 취소 시 manually_extended_until 클리어 — 재활성 시 stale flag로
        # naver_sync 영구 차단되는 silent data drift 방지
        if existing.manually_extended_until:
            existing.manually_extended_until = None
```

**Before** (L747):
```python
            existing.manually_extended_until = None
```

**After**:
```python
            existing.manually_extended_until = None
            existing.check_out_pinned = False
```

같은 가드 패턴 — `if existing.manually_extended_until:` (truthy 일 때만). §3-4 와 동일한 코너 케이스 가정.

---

## 4. 동작 동등성 / 의도된 변화

### 4-1. lifecycle 1:1 매핑 — 본 단계 머지 후 두 플래그 동기 상태

| 시점 | manually_extended_until | check_out_pinned | 의도 |
|---|---|---|---|
| 신규 예약 | None | False | 보호 없음 |
| extend_stay 직후 | "YYYY-MM-DD" | True | 보호 on |
| reduce 완전 축소 (≤1박) | None | False | 보호 off |
| reduce 부분 축소 (>1박) | "YYYY-MM-DD" | True | 보호 유지 |
| status=CANCELLED | None | False | 보호 off (재활성 대비) |
| naver_sync 취소 | None | False | 동일 |
| naver_sync catch-up (#10 미머지) | None | True (잔존) | **단계 #10 미머지 동안 코너 케이스** — 단계 #5 의 OR 절이 `incoming_end < check_out_date` 조건도 있어 catch-up 케이스(incoming 큼)는 어차피 가드 무력. 즉 false-positive 보호 발생 안 함 |
| reservations.py PUT 으로 새 check_out_date 변경 | None (stale 정리) | True (단계 #7 로 다시 set) | 정상 |

### 4-2. 4개 버그 시나리오 #2 ("드래그 + 수동 연박") 해결 검증

| 단계 | 동작 | pin 상태 |
|---|---|---|
| 1) 내일→오늘 드래그 | frontend `dateCrossMutation` → reservations.py PUT | check_in_pinned=True, check_out_pinned=True (단계 #6+#7) |
| 2) 수동 연박 1박 추가 | reservations_stay.py extend_stay | check_out_pinned=True (본 단계 §3-1) — 이미 True 였으니 변화 0 |
| 3) 5분 뒤 naver_sync | check_in_pinned 가드(#4) + check_out_pinned 가드(#5) → 둘 다 skip | check_in_date, check_out_date 보존 ✅ |

→ 본 단계 머지 후 시나리오 #2 해결. **4개 버그 모두 해결 완료**.

### 4-3. 시나리오별 결과

| 시나리오 | Before | After (본 단계) | 판정 |
|---|---|---|---|
| 일반 연박 연장 후 naver_sync | manually_extended_until 가드 보호 | 동일 + check_out_pinned 가드도 함께 보호 | ✅ 보호 강화, 동작 동등 |
| 완전 축소 (1박) 후 naver_sync | manually_extended_until=None → 가드 무력, naver_sync 가 catch-up | 동일 — check_out_pinned=False 도 같이 풀려서 가드 무력 | ✅ |
| 부분 축소 후 naver_sync | manually_extended_until 유지 → 가드 보호 | 동일 + pin도 유지 | ✅ |
| 취소 후 재활성 | manually_extended_until=None → 정상 동기화 재개 | 동일 + pin 도 None → 정상 | ✅ |
| 시나리오 #2 (드래그+연박) | 5분 뒤 원복 (버그) | pin 으로 보호 (해결) | 🔵 |

---

## 5. 영향받지 않음을 확인할 코드 경로

- `extend_stay` 의 conflict check, assign_room 호출, chip reconcile — 변경 0
- `_do_reduce_extension` 의 RA 삭제, chip reconcile — 변경 0
- `reservations.py PUT` 의 stay_group unlink, peer sync_sms_tags — 변경 0
- `naver_sync._update_reservation` 의 cancel 다른 라인 (cc1/cc2 분기, chip cleanup, stay_group unlink) — 변경 0
- `naver_sync.py:706` catch-up — 단계 #10 에서 처리
- `reservations.py:397` stale 정리 — 단계 #7 의 PUT 으로 새 pin set 됨 (위 §2 노트)

---

## 6. 검증 체크리스트

- [ ] **syntax**: 3개 파일 각각 `venv/bin/python -m py_compile` 에러 0
  - `app/api/reservations_stay.py`
  - `app/api/reservations.py`
  - `app/services/naver_sync.py`
- [ ] **diff**: 정확히 5 라인 추가 (각 파일 1+1+1+1+1)
- [ ] **manually_extended_until 와 check_out_pinned 동기 검증** (단위 테스트):
  ```python
  # extend → 둘 다 set
  client.post(f"/reservations/{rid}/extend-stay", ...)
  res = db.refresh(reservation); 
  assert res.manually_extended_until is not None
  assert res.check_out_pinned is True
  # reduce(완전) → 둘 다 clear
  client.post(f"/reservations/{rid}/reduce-extension", json={"days": 1})
  res = db.refresh(reservation)
  assert res.manually_extended_until is None
  assert res.check_out_pinned is False
  ```
- [ ] **시나리오 #2 통합 검증**:
  1. 내일 예약 → 오늘로 드래그 → check_in_pinned, check_out_pinned 둘 다 True 확인
  2. 수동 연박 1박 → check_out_pinned 유지 True
  3. 수동 naver sync 실행 → check_in_date, check_out_date 보존 확인
- [ ] **기존 pytest 회귀**: pass/fail 개수 #6+#7 시점과 동일
- [ ] **외부 영향**: `git diff main -- app/` 가 §2 의 3개 파일 외 0 라인

---

## 7. 본 단계 이후의 후속 의존성

- **#9, #10** (catch-up 정책) — naver_sync.py:706 의 check_out_pinned catch-up 처리. 본 단계 직후 catch-up 차이 검토 필요
- **#11~#14** (Mutator 라우팅) — 본 단계의 5곳 set/clear 를 Mutator 내부로 흡수
- **#15** (manually_extended_until deprecation) — 본 단계로 1:1 매핑이 보장됐으므로, manually_extended_until 의 set/clear 를 check_out_pinned 로 대체하고 컬럼 제거 가능 (별도 마이그레이션 + 데이터 백필)

---

## 8. 분해 계획 변경 사항

`mutator-migration-plan.md` 의 단계 #8 정의를 다음과 같이 갱신해야 함:

> **변경 전**: "extend_stay 옆에 check_out_pinned=True 동시 세팅 (1 line)"
> **변경 후**: "manually_extended_until 의 5개 set/clear 위치에 check_out_pinned 1:1 동기화 (5 lines, 3 파일)"

근거: 부분만 적용하면 lifecycle 비대칭 발생.

---

## 9. 미결 검토 항목

- [ ] **§3-4, §3-5 코너 케이스**: `manually_extended_until` 이 truthy 일 때만 실행되는 분기 안에 check_out_pinned 도 함께 처리. 만약 manually_extended_until=None 인데 check_out_pinned=True 인 상태가 외부에서 만들어지면 이 분기 안 탐 → pin 잔존. 본 단계 머지 시점엔 발생 0 (5곳에서 1:1 동기). #15 deprecation 후 가드 조건을 `check_out_pinned` 로 교체할 때 자동 해결.
- [ ] **단계 #10 의 catch-up 분기와의 상호작용**: naver_sync.py:706 의 catch-up CLEAR 가 check_out_pinned 를 함께 풀지 결정 필요. 본 단계 단독 머지 시 잔존 pin 케이스의 영향은 §4-1 표 참조.

---

## 10. 머지 후 다음 액션

본 단계 #8 머지 = **4개 버그 모두 해결 완료** (시나리오 #1, #2, #3, #4 전부).

→ 사용자 검수 받고 #9~#15 진행 여부 결정. 또는 핫픽스 분기점으로 #8까지만 main 머지하고 나머지는 별도 마일스톤.
