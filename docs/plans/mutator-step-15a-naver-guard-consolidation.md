# 단계 #15a 사전조사 — naver_sync 보호 가드 통합

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §F
> 분류: ⚫ 리팩토링 — 동작 동등성 보장 (단계 #8 의 1:1 매핑에 의존)
> 변경 규모: `app/services/naver_sync.py` ~7 라인 제거
> **방안 1 적용** — 두 플래그 책임 분리: `manually_extended_until` 은 운영 표시, `check_out_pinned` 는 동기화 보호

---

## 1. 비즈니스 컨텍스트

사용자 확인 (2026-05-15):
> 수동연박은 서비스로 1박 추가하는 케이스. 객실배정 페이지에서 지우려면 예약자 전체 삭제 또는 날짜조정으로만 가능해서 번거롭고, 나중에 수동 추가인지 실제예약인지 헷갈릴 수 있어 `manually_extended_until` 로 별도 표시함.

→ **두 플래그의 책임이 다름**:

| 필드 | 책임 | 사용처 |
|---|---|---|
| `manually_extended_until` | "이 예약은 수동 연박이었음" 운영 표시 | UI "연박 취소" 버튼 + `cancel_extend_stay` 진입 조건 |
| `check_out_pinned` | "사용자가 check_out 을 수동 변경" 동기화 보호 | naver_sync 가드 |

→ 통합 불가. 의미 분리 유지하면서 backend 가드만 정리.

---

## 2. 본 단계의 정확한 정의

| 작업 | 변경 |
|---|---|
| naver_sync 의 OR 가드 첫 절 (`manually_extended_until` 보호 조건) 제거 | `check_out_pinned` 가드 단독으로 보호 |
| `manually_extended_until` catch-up 분기 | **유지** — 네이버가 사용자 의도 도달 시 표시 해제 (운영 의미) |
| `manually_extended_until` set/clear 모든 위치 (extend/reduce/cancel) | **유지** — UI 분기용 |
| `_to_response` / `ReservationResponse` 의 `manually_extended_until` | **유지** — frontend 가 사용 |
| frontend 모든 코드 | **변경 0** — silent regression 위험 0 |

---

## 3. 동작 동등성 근거

### 3-1. 단계 #8 의 1:1 매핑이 보장하는 것

위 단계 #8 사전조사 §3 에서 검증한 것처럼, `manually_extended_until` set/clear 와 `check_out_pinned` set/clear 가 5곳 모두에서 1:1 동기.

```
manually_extended_until truthy  ⟺  check_out_pinned = True
```

따라서 OR 가드의 두 절이 같은 케이스를 잡는다:

| `manually_extended_until` 가드 절 | `check_out_pinned` 가드 절 |
|---|---|
| `me and incoming < co and incoming < me` | `cp and incoming < co` |
| `me` (truthy) ⟺ `cp=True` (단계 #8) | 동일 |
| 단 단계 #6~#7 이후: PUT 으로 check_out 변경한 케이스는 `me=None` 이지만 `cp=True` — 신규 케이스 | 가드 발동 (보호) |
| 즉 `cp=True` 가 `me=truthy` 의 모든 케이스 + 추가 (PUT, 드래그) 케이스를 cover | OR 첫 절 제거해도 같은 보호 (혹은 더 넓게) |

→ **OR 첫 절은 redundant**. 제거해도 동작 동등 또는 더 안전.

### 3-2. 추가 검증 — `check_out_pinned=False` 인데 `manually_extended_until` truthy 인 상태 가능?

단계 #8 이후 1:1 매핑이라 발생 0. 단 다음 케이스를 검토:
- `extend_stay` 직후: 둘 다 set (단계 #8 §3-1)
- `reduce 완전축소`: 둘 다 clear (단계 #8 §3-2 Case A)
- `reduce 부분축소`: 둘 다 set (단계 #8 §3-2 Case B)
- `cancel`: 둘 다 clear (단계 #8 §3-4, §3-5)
- `PUT` 으로 check_out 변경: `cp=True`, `me` 변화 0 (단계 #7) — 단방향 (cp 만 True)
- `naver_sync` 의 manually_extended_until catch-up: `me=None`, `cp` 변화 0 — 단방향 (me 만 None)

→ **catch-up 후 `me=None` 인데 `cp=True` 인 상태 발생 가능**. 이 상태에서 다음 sync 시:
- OR 가드 첫 절 (me 가드): `me=None` → False → 발동 안 함
- OR 가드 두 번째 절 (cp 가드): `cp=True` → incoming < check_out_date 면 보호 발동

→ **두 번째 절이 단독으로 보호 — 첫 절 제거해도 보호 효과 동등**.

### 3-3. 단순화 후 가드 매트릭스

| me | cp | incoming < co | After (방안 1 적용) | Before | 동등 |
|---|---|---|---|---|---|
| None | False | * | else (catch-up) | else | ✅ |
| 있음 | True | True | skip (cp 가드) | skip (me 가드 OR cp 가드) | ✅ |
| 있음 | True | False | else | else | ✅ |
| None | True | True (PUT 케이스) | skip (cp 가드) | skip (cp 가드만) | ✅ |
| None | True | False | else | else | ✅ |
| 있음 | False | * | (단계 #8 1:1 매핑이라 발생 0) | (동일) | N/A |

→ 모든 케이스 동등.

### 3-4. catch-up 분기 영향 — 유지함

else 분기 안의 두 catch-up 은 **그대로 유지**:

```python
# manually_extended_until catch-up — 운영 표시 해제
if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
    existing.manually_extended_until = None
    diag(...)

# check_out_pinned catch-up — 보호 해제
if existing.check_out_pinned and incoming_end >= existing.check_out_date:
    existing.check_out_pinned = False
    diag(...)
```

두 catch-up 은 독립 — 어느 한쪽만 발동되어도 다른 쪽 영향 없음. 책임 분리 명확.

---

## 4. 변경 대상 코드

### `app/services/naver_sync.py` L686~L696 (OR 가드)

**Before** (단계 #10 머지 결과):

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
```

**After** (방안 1):

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        # 보호 가드 — check_out_pinned 단독으로 모든 수동 변경 케이스 cover.
        # manually_extended_until 의 보호 효과는 단계 #8 1:1 매핑으로 check_out_pinned 가 흡수.
        # manually_extended_until 은 운영 표시용 (UI "연박 취소" 버튼 + cancel 진입 조건).
        if existing.check_out_pinned and incoming_end < existing.check_out_date:
            # User manually changed check_out — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
```

**변경 내용**:
- OR 의 첫 절 (manually_extended_until 가드 — 3 조건) 제거
- 두 번째 절만 남김 (check_out_pinned)
- 책임 분리 주석 추가 (책임 명시)
- 주석 라인 `# User manually extended — preserve` 를 `# User manually changed check_out — preserve` 로 갱신 (의미 확장 반영)

else 분기 (catch-up 두 개 + Mutator 호출) 는 변경 0.

---

## 5. 영향받지 않음을 확인할 코드 경로

- `manually_extended_until` catch-up 분기 (L709~L719) — 변경 0
- `check_out_pinned` catch-up 분기 (L720~L729) — 변경 0
- Mutator 호출 라인 (L730~L733) — 변경 0
- diag 로깅 본문 (L697~L706) — 변경 0
- `extend_stay`, `_do_reduce_extension`, naver_sync cancel 의 `manually_extended_until` set/clear — 변경 0
- `_to_response` / `ReservationResponse` 의 manually_extended_until — 변경 0
- frontend 전체 — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff**: OR 첫 절 (4 라인) 제거 + 주석 추가 (3 라인) = 약 -1 라인
- [ ] **가드 매트릭스 회귀** (단계 #5/#8 시나리오):
  - me=truthy, cp=True, incoming < co → skip (보호)
  - me=truthy, cp=True, incoming >= co → else (catch-up + Mutator)
  - me=None, cp=True (PUT 케이스), incoming < co → skip (cp 가드)
  - me=None, cp=False → else (정상 동기화)
- [ ] **catch-up 시나리오** (단계 #9/#10):
  - extend 후 naver catch-up (incoming=me=co): manually_extended_until → None, check_out_pinned → False, check_out 덮어쓰기
  - 둘 다 동일 분기 진입
- [ ] **frontend 영향**: `git diff main -- frontend/` 결과 0 라인
- [ ] **기존 pytest 회귀**: pass/fail 개수 #14 시점과 동일

---

## 7. 본 단계 이후의 후속 의존성

- 본 단계만으로 방안 1 완료. 다른 단계 의존성 없음.
- 향후 "수동 연박" 외 새 종류의 연장 (프로모션, 로열티 등) 도입 시 → 별도 마일스톤에서 `extension_type` 컬럼 신설 검토 (방안 2)

---

## 8. 머지 후 다음 액션

- 본 단계 머지 = **Mutator 마이그레이션 (단계 #1~#15a) 전체 완료**
- 단계 #15b/c/d (manually_extended_until 완전 제거) 는 비즈니스 의미상 진행 안 함
- 향후 운영 가시화: stale `check_out_pinned` (catch-up 안 일어난 잔존) 모니터링 도구 검토
