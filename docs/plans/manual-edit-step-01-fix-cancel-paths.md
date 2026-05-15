# PR1-fix 사전조사 — 연박취소/CANCELLED 경로의 dict 클리어 누락 회귀

> 부모 계획: [manual-edit-protection-plan.md](./manual-edit-protection-plan.md)
> 선행 PR: [manual-edit-step-01-infrastructure.md](./manual-edit-step-01-infrastructure.md)
> 분류: 🔴 회귀 수정 — PR1 부작용 패치
> 변경 규모: Mutator 헬퍼 1개 + caller 2곳 + 단위 테스트 2건

---

## 1. 목적

PR1 에서 `Mutator.apply_changes(MANUAL, check_out_date=...)` 가 호출되면
`manually_edited_fields["check_out_date"]` 가 자동 등록된다. 그러나 연박취소
/ 예약취소 경로에서 caller 가 `check_out_pinned=False` 만 클리어하고 dict 는
그대로 남기는 패턴이 발견됨 → 다음 naver_sync 가 `is_pinned_dict=True` 로
영구 차단되는 회귀.

수정: Mutator 에 `release_manual_pin(reservation, field)` 헬퍼 추가 → caller 가
dict + pin 컬럼을 단일 호출로 해제. diag `mutator.pin_released` 로 가시화.

---

## 2. 변경 대상 코드

### 2-1. `app/services/reservation_mutator.py`
신규 staticmethod 추가:
```python
@staticmethod
def release_manual_pin(reservation: "Reservation", field: str) -> bool:
    """Manual pin 해제 (방명록 dict + pin 컬럼 둘 다).

    cancel/연박취소 경로 등 "운영자 수정 → 자동 동기화로 복귀" 의도 호출자가 사용.
    실제 해제 1건 이상 발생 시 mutator.pin_released diag 발화.
    """
    from app.diag_logger import diag

    released_dict = False
    released_column = False

    edits = dict(reservation.manually_edited_fields or {})
    if field in edits:
        del edits[field]
        reservation.manually_edited_fields = edits
        released_dict = True

    pin_attr = _PIN_ATTR_FOR.get(field)
    if pin_attr and getattr(reservation, pin_attr, False):
        setattr(reservation, pin_attr, False)
        released_column = True

    if released_dict or released_column:
        diag(
            "mutator.pin_released",
            level="critical",
            res_id=reservation.id,
            field=field,
            released_dict=released_dict,
            released_column=released_column,
        )
    return released_dict or released_column
```

### 2-2. `app/api/reservations_stay.py:_do_reduce_extension` (line 425-441)
**Before**:
```python
ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
if days_remaining <= 1:
    original.manually_extended_until = None
    original.check_out_pinned = False
    diag("reduce_extension.flag_cleared", ...)
else:
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True
```

**After**:
```python
ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
if days_remaining <= 1:
    original.manually_extended_until = None
    # PR1-fix: pin 컬럼 + dict 둘 다 클리어 (naver_sync 정상화)
    ReservationMutator.release_manual_pin(original, "check_out_date")
    diag("reduce_extension.flag_cleared", ...)
else:
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True
    # else 분기: dict 에 "check_out_date" 남아있음 → 의도된 보호 (운영자 부분 축소도 손 댄 것)
```

### 2-3. `app/api/reservations.py:update_reservation` (line 343-349)
**Before**:
```python
if (
    "status" in update_data
    and update_data["status"] == ReservationStatus.CANCELLED
    and db_reservation.manually_extended_until
):
    db_reservation.manually_extended_until = None
    db_reservation.check_out_pinned = False
```

**After**:
```python
if (
    "status" in update_data
    and update_data["status"] == ReservationStatus.CANCELLED
    and db_reservation.manually_extended_until
):
    db_reservation.manually_extended_until = None
    # PR1-fix: pin 컬럼 + dict 둘 다 클리어 (취소 후 재활성 시 naver_sync 정상화)
    from app.services.reservation_mutator import ReservationMutator as _RM
    _RM.release_manual_pin(db_reservation, "check_out_date")
```

---

## 3. 동작 동등성

### 3-1. 연박취소 (`days_remaining<=1`)
| 단계 | Before (회귀) | After (수정) |
|------|--------------|-------------|
| Mutator 호출 후 | `dict["check_out_date"]=ts` 등록 | 동일 |
| `check_out_pinned` | False | False |
| `manually_extended_until` | None | None |
| **`manually_edited_fields["check_out_date"]`** | **잔존 (회귀)** | **삭제 (정상)** |
| 다음 naver_sync | `is_pinned_dict=True` → skip ❌ | dict 비어있음 → 통과 ✅ |

### 3-2. 예약 CANCELLED + 연박 흔적 있음
| 단계 | Before | After |
|------|--------|-------|
| caller 가 status=CANCELLED + manually_extended_until 보유 감지 | 동일 | 동일 |
| `check_out_pinned` | False | False |
| **dict** | **잔존 (회귀)** | **삭제 (정상)** |
| 재활성 후 naver_sync | 차단 ❌ | 통과 ✅ |

### 3-3. 부분 축소 (`days_remaining>1`)
- Mutator 호출 → dict 등록 + `check_out_pinned=True` 유지
- 의도된 보호: 운영자가 "부분 축소" 한 것도 손 댄 것 — naver 가 다시 늘리지 못해야 함
- After 에서도 동일 동작 (else 분기는 손대지 않음)
- ✅ 의도된 보호

### 3-4. `release_manual_pin` 의 idempotency
- dict + 컬럼 둘 다 비어있을 때 호출 → 둘 다 False → diag 발화 없음, return False
- dict 만 있고 컬럼 없을 때 (5필드 케이스) → dict 만 클리어 후 diag
- 컬럼만 있고 dict 없을 때 (구 데이터) → 컬럼만 클리어 후 diag
- ✅ 안전

---

## 4. 시나리오별 결과 (단위 테스트 검증)

| 시나리오 | 결과 | 테스트 |
|---------|------|--------|
| MANUAL check_out_date 변경 후 release → dict 비고 컬럼 False | ✅ | test_release_clears_both_dict_and_column |
| dict 만 있는 5 필드 release → dict 만 클리어 | ✅ | test_release_phone_clears_dict_only |
| 둘 다 비어있을 때 release → no-op, diag 발화 없음 | ✅ | test_release_noop_when_clean |
| release 후 NAVER → 차단 풀림 (정상 갱신) | ✅ | test_naver_unblocked_after_release |
| reduce_extension `days_remaining<=1` 시 dict 클리어 확인 | ✅ | (통합 - 옵션) |

총 4 케이스 신규 + 회귀 0 검증.

---

## 5. 영향받지 않음을 확인할 코드 경로

- `extend_stay` (line 224-227): 그대로 — 연박 추가는 손 댐, dict 등록 유지가 정답
- `reservations_stay.py:_do_reduce_extension` 의 `else` 분기 (부분 축소): 그대로
- `reservations.py update_reservation` 의 status≠CANCELLED 경로: 그대로
- naver_sync 의 Mutator 호출 3곳: 그대로 (NAVER source 는 dict 갱신 안 함)
- `chip-store` 마이그레이션 결과: 변경 0
- `sync-sms-tags` 마이그레이션 결과: 변경 0

---

## 6. 검증 체크리스트

- [ ] Mutator.release_manual_pin staticmethod 추가
- [ ] reservations_stay.py `_do_reduce_extension` 호출 교체
- [ ] reservations.py `update_reservation` CANCELLED 분기 호출 교체
- [ ] test_mutator_manually_edited.py 에 release 테스트 4건 추가
- [ ] pytest 통과 (기존 58 + 신규 4 = 62)
- [ ] py_compile 통과

---

## 7. 운영 검증 (배포 후)

`diag-golden` 검증 회차에서 확인할 신호:
- `mutator.pin_released(field=check_out_date)` — reduce/cancel 진입 시 발화
- 발화 빈도 = 연박취소 + 예약취소(연박포함) 액션 횟수
- `mutator.skipped(reason=pinned, field=check_out_date)` — 정상 사용 시 발화 감소 예상
  (이전엔 dict 잔존으로 무한 skip 발화 가능성)

---

## 8. 후속 PR

- **PR2**: `check_in_pinned` / `check_out_pinned` 컬럼 데이터를 dict 로 이주
  (data migration)
- **PR3**: pin 컬럼 2개 제거 + `_PIN_ATTR_FOR` 삭제 + `release_manual_pin` 의
  컬럼 처리 분기 삭제

PR1-fix 진입 조건: 회귀 발견 즉시 (현재). PR2 진입 조건은 변경 없음.

---

## 9. 회귀 위험 평가

| 위험 | 평가 |
|---|---|
| 부분 축소 시 보호 풀림 | 없음 (else 분기 손대지 않음) |
| extend_stay 보호 풀림 | 없음 (호출 안 됨) |
| 5 필드 보호 영향 | 없음 (release_manual_pin 은 명시 호출 시에만 작동) |
| naver_sync 정상화 | 🟢 회귀 해소 |
| diag-golden 정답지 | mutator.pin_released 신규 발화 — pending 등록 |
