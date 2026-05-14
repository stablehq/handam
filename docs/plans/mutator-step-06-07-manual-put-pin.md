# 단계 #6~#7 사전조사 — 수동 PUT 에서 `check_in_pinned` / `check_out_pinned` 자동 세팅

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §C
> 분류: 🔵 **의도된 동작 변화** — 4 개 버그 시나리오 중 #1, #3, #4 해결
> 변경 규모: `app/api/reservations.py` 5 라인 추가 (setattr 루프 직후)
> 묶음 사유: 동일 함수의 동일 위치, 반대 필드만 다름

---

## 1. 목적

`reservations.py` PUT `update_reservation` 가 `check_in_date` / `check_out_date` 를 수정할 때 해당 필드의 pin 컬럼을 `True` 로 자동 세팅. naver_sync (#4, #5 가드) 가 이후 이 pin 을 읽고 덮어쓰기 skip.

설계안 §1-2 버그 시나리오:
- #1 "내일 → 오늘 드래그" → frontend `dateCrossMutation` 이 `reservations.py PUT (check_in_date, check_out_date)` 호출 → 본 단계로 해결
- #3 "수동 PUT 으로 날짜 수정" → 본 단계로 직접 해결
- #4 "수정 + 드래그 + 연박 조합" 의 check_in 부분 → 본 단계로 해결

---

## 2. 변경 대상 코드

### `app/api/reservations.py` L336~L338 (setattr 루프 직후)

**Before** (실측):

```python
    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    # status 가 CANCELLED 로 바뀌면 stay_group 자동 해제 (naver_sync 와 동일 정책)
```

**After**:

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

**변경 내용**: setattr 루프 직후, 기존 status/CANCELLED 분기 *위*에 5 라인 추가. 다른 코드 변경 0.

---

## 3. 정책 결정 — 왜 "update_data 에 키 존재" 만 검사하나

세 가지 옵션 검토:

| 옵션 | 동작 | 평가 |
|---|---|---|
| A. `"check_in_date" in update_data` (값 동등성 무관) | 사용자가 PUT 으로 명시했으면 pin | **선택**. 가장 단순. silent 케이스 없음. 같은 값 재PUT 도 사용자 의지 — pin OK |
| B. `update_data["check_in_date"] != old_check_in` (실제 변경 시만) | 값이 실제로 바뀐 경우만 pin | 미세하게 더 보수적. 단 frontend 가 같은 값을 의도적으로 PUT 하는 경우 (예: 자동 새로고침 후) pin 못 함 |
| C. setattr 루프 안에 분기 | 필드별 처리 | 가독성 ↓ — 별도 블록이 명확 |

**A 선택 근거**:
- `reservation.dict(exclude_unset=True)` (L271) 로 update_data 가 빌더되므로, **명시되지 않은 필드는 키 자체가 없음**
- 즉 `"check_in_date" in update_data` 가 True 라는 건 frontend 또는 직원 도구가 의도적으로 그 필드를 보냈다는 뜻
- 값이 같든 다르든 "사용자가 그 값을 지정함" → pin 해두는 게 의도 보존

---

## 4. 동작 동등성 / 의도된 변화

### 4-1. 케이스 매트릭스

| 시나리오 | Before | After (본 단계) | 판정 |
|---|---|---|---|
| `check_in_date` 미포함 PUT (예: 인원만 변경) | pin 변화 0 | pin 변화 0 (`if "check_in_date" in update_data` False) | ✅ 동등 |
| `check_in_date` 포함 PUT, 값 동일 | pin=False 유지 | pin=True 로 변경 | 🔵 의도 (값 의지 명시) |
| `check_in_date` 포함 PUT, 값 변경 | pin=False 유지 | pin=True | 🔵 의도 |
| `check_out_date` 포함 PUT | check_out_pinned=False 유지 | pin=True | 🔵 의도 |
| `check_in_date`/`check_out_date` 모두 포함 (`dateCrossMutation`) | 둘 다 False | 둘 다 True | 🔵 의도 |

### 4-2. 4 개 버그 시나리오 해결 검증 (단계 #6+#7 단독 머지 후)

| 버그 # | 시나리오 | 본 단계 단독 효과 | 완전 해결 시점 |
|---|---|---|---|
| #1 | 내일→오늘 드래그 → 5분 뒤 원복 | dateCrossMutation 이 PUT 으로 check_in/out 변경 → 본 단계로 pin=True → 다음 naver_sync 가 #4/#5 가드로 skip → **해결** | #6+#7 |
| #3 | 수동 PUT 으로 날짜 수정 → 5분 뒤 원복 | PUT 직접 호출 → 본 단계로 pin → naver_sync skip → **해결** | #6+#7 |
| #4 | 수정+드래그+연박 조합 → check_in 만 원복 | check_in 은 본 단계로 해결, check_out 은 manually_extended_until (기존) 또는 본 단계로 해결 → **해결** | #6+#7 |
| #2 | 드래그+수동 연박 → 5분 뒤 원복 | 드래그 부분은 본 단계로 해결. 연박(`extend_stay`) 의 check_out_pinned 세팅은 단계 #8 이 필요 | **#8 필요** |

→ **본 단계 #6+#7 머지 후 4개 중 3개 해결**. 시나리오 #2 의 extend_stay 부분만 #8 에 남음.

### 4-3. 다른 caller 영향

| caller | 본 단계 영향 |
|---|---|
| `naver_sync._update_reservation` | `check_in_pinned`/`check_out_pinned` 를 읽기만 (단계 #4, #5 가드) — 본 단계 머지 후 pin=True 인 레코드를 만나면 skip 함 |
| `reservations_stay.extend_stay` | 본 함수 안 호출 — 별도 endpoint. check_out_date 직접 setattr (L222), 본 단계 영향 없음. 단계 #8 에서 별도 처리 |
| `_do_reduce_extension` | check_out_date 직접 변경, 본 함수 안 호출 — 본 단계 영향 없음 |
| `reservations_room.assign_room` | check_in/out 안 만짐 — 영향 없음 |
| 자동 객실 배정 | 동일 — 영향 없음 |

### 4-4. ActivityLog / 외부 시스템 영향

- ActivityLog: 본 단계는 pin 컬럼 외에 다른 필드 변경 없음. log_activity 호출 흐름 변경 0
- SSE 이벤트: 동일
- frontend 응답: `ReservationResponse` 가 `check_in_pinned` / `check_out_pinned` 를 포함하지 않음 (단계 #2~#3 사전조사 §3-1 확인) — frontend 응답 형태 변화 0

---

## 5. 영향받지 않음을 확인할 코드 경로

- L314 `old_dates = ...` — 변경 0
- L336 setattr 루프 — 변경 0
- L339~ status CANCELLED 분기 (불변)
- L374 `new_dates = ...` — 변경 0
- L383~ `shift_daily_records` / `reconcile_dates` 분기 — 변경 0
- 다른 caller 모두 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/api/reservations.py` 에러 0
- [ ] **diff**: 정확히 5 라인 추가, 다른 라인 변경 0
- [ ] **외부 영향**: `git diff main -- app/` 가 본 파일 외 0 라인
- [ ] **기존 pytest 회귀**: pass/fail 개수 #5 시점과 동일
- [ ] **수동 검증 시나리오 #1** (내일→오늘 드래그):
  1. 내일 날짜 예약 1개 생성
  2. frontend 에서 오늘 방으로 드래그
  3. DB 에서 `check_in_pinned=True`, `check_out_pinned=True` 확인
  4. 5분 후 (또는 수동 sync) → check_in_date 가 보존되는지 확인
- [ ] **수동 검증 시나리오 #3** (수동 PUT):
  1. 예약 1개 골라 frontend 에서 check_in_date 수정 + 저장
  2. DB 에서 `check_in_pinned=True` 확인
  3. 수동 sync → check_in_date 보존 확인
- [ ] **수동 검증 시나리오 #4** (조합):
  1. 시나리오 #1 + #3 모두 수행 후 검증
- [ ] **단위 테스트** (선택):
  ```python
  # frontend PUT 시뮬레이션
  response = client.put(f"/reservations/{res_id}", json={"check_in_date": "2026-05-15"}, headers=...)
  assert response.status_code == 200
  db_res = db.query(Reservation).get(res_id)
  assert db_res.check_in_pinned is True
  ```

---

## 7. 본 단계 이후의 후속 의존성

- **#8** (extend_stay 의 check_out_pinned 자동 세팅) — 시나리오 #2 의 잔여 해결
- **#9, #10** (catch-up 정책) — 본 단계로 pin 된 레코드의 자동 해제 조건
- **#11~#14** (Mutator 라우팅) — 본 단계의 pin 세팅을 Mutator 내부로 흡수

---

## 8. 미결 검토 항목

- [ ] **pin 의 lifecycle**: 본 단계는 pin 만 세팅. 해제는 #9, #10 의 catch-up 또는 사용자가 수동 PUT 으로 pin 해제 (별도 작업 필요) 까지 영구. 운영상 stale pin 가시화 도구 필요한지 검토 (예: admin UI 에 pin 표시)
- [ ] **frontend `dateCrossMutation` (`useGuestMove.ts:313`) 동작 확인**: PUT 으로 check_in_date+check_out_date 둘 다 보내는지 (`useGuestMove.ts` L313~L316 인용):
  ```typescript
  await reservationsAPI.update(vars.resId, {
    check_in_date: vars.destDateStr,
    check_out_date: vars.destCheckout,
  });
  ```
  → 둘 다 보냄 ✅ — 본 단계로 시나리오 #1 자동 해결

---

## 9. 머지 후 다음 액션

`mutator-step-08-extend-stay-pin.md` 작성.
