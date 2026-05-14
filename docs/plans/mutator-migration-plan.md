# Mutator 마이그레이션 — 단계 분해 계획

> 작성일: 2026-05-14
> 상태: 단계 분해안 검토 대기
> 부모 설계: [reservation-mutator-design.md](./reservation-mutator-design.md)
> 후속 단계: [room-assignment-pipeline-design.md](./room-assignment-pipeline-design.md) (별도)

---

## 원칙

1. **기존 기능 변화 금지** — 의도된 변화(설계안 §1-2의 4개 버그 해결)만 허용. 그 외 silent behavior change 금지.
2. **각 단계는 별도 PR + 별도 사전조사 문서** — 본 디렉터리에 `mutator-step-NN-*.md` 형식.
3. **각 사전조사 문서에 Before/After 코드 인용 + 동작 동등성 근거 명시**.
4. **각 단계는 직전 단계와 독립** — 단계 #N을 롤백해도 시스템 동작.

## 의도된 동작 변화 (= 해결 대상)

설계안 §1-2의 4개 케이스 (모두 `naver_sync.py:672`의 `check_in_date` 무조건 덮어쓰기가 원인):

| # | 시나리오 | 호출 경로 | 원인 |
|---|---|---|---|
| 1 | 내일→오늘 드래그 → 5분 뒤 원복 | `reservations.py:261 update_reservation` → check_in_date 변경 → naver_sync가 덮어씀 | check_in 보호 없음 |
| 2 | 드래그+수동 연박 → 5분 뒤 원복 | 위 + `reservations_stay.py:157 extend_stay` | manually_extended_until은 check_out만 보호 |
| 3 | 수동 PUT으로 날짜 수정 → 5분 뒤 원복 | `reservations.py:261` 직접 | 동일 |
| 4 | 수정+드래그+연박 조합 → check_in만 원복 | 위 모두 조합 | 두 필드 보호 비대칭 |

→ 4개 모두 "수동 변경된 `check_in_date` / `check_out_date`가 네이버 동기화로 덮이지 않게 한다"가 해결 조건.

---

## 단계 분해 (15개)

각 단계의 **실제 동작 변화 유무**를 명시. ⚪ = 동작 변화 없음 (구조/인프라), 🔵 = 의도된 변화 (버그 해결), ⚫ = 정리/리팩토링 (동작 동등).

### A. 기초 인프라 (⚪ 동작 변화 없음)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 1 | `reservation_mutator.py` 신규 — `ChangeSource` enum + `FIELD_PERMISSIONS` 테이블 (호출 안 함) | `backend/app/services/reservation_mutator.py` (신규) | 추가 ~80 lines |
| 2 | DB 마이그레이션 — `check_in_pinned`, `check_out_pinned` 컬럼 추가 (default False) | alembic versions/ + `db/models.py` | 추가 ~30 lines |
| 3 | `Reservation` 모델에 컬럼 선언 + ORM 매핑 확인 | `app/db/models.py` | 추가 2 lines |

**동작 동등성**: 어디서도 set/check 안 함. 컬럼 추가 자체만으로는 모든 SELECT/INSERT 결과 동일 (default False, 비교 안 함).

### B. Naver guard 추가 (⚪ 동작 변화 없음, 단 #6~#8 이후부터 의미 발생)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 4 | `naver_sync.py:672` 직전에 `if not existing.check_in_pinned:` 가드 — `existing.check_in_date = ...`를 그 안으로 이동 | `app/services/naver_sync.py` | 수정 ~3 lines |
| 5 | `naver_sync.py:676~702` `manually_extended_until` 가드 옆에 `or existing.check_out_pinned` OR 조건 추가 (기존 `manually_extended_until` 보호 유지) | `app/services/naver_sync.py` | 수정 ~2 lines |

**동작 동등성**: #1~#3에 의해 모든 레코드의 pinned 컬럼이 False. 가드가 추가됐어도 항상 False라 기존 분기와 동일하게 진행. SELECT 결과·INSERT 결과 동일.

### C. Pin 자동 설정 (🔵 의도된 변화 — 4개 버그 해결의 핵심)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 6 | `reservations.py:261 update_reservation` 본문 — `setattr` 루프 후 `check_in_date`가 `update_data`에 포함되어 변경됐으면 `db_reservation.check_in_pinned = True` 자동 세팅 | `app/api/reservations.py` | 추가 ~5 lines |
| 7 | 동일 위치에서 `check_out_date` 변경 시 `check_out_pinned = True` 자동 세팅 | `app/api/reservations.py` | 추가 ~5 lines |
| 8 | `reservations_stay.py:157 extend_stay` — 기존 `original.manually_extended_until = new_end_str` 옆에 `original.check_out_pinned = True` 동시 세팅 (병행 유지) | `app/api/reservations_stay.py` | 추가 1 line |

**해결되는 버그** (이 단계 이후):
- 시나리오 #3 (수동 PUT): #6 로 check_in_pinned=True → naver_sync(#4)가 덮어쓰기 skip
- 시나리오 #1 (내일→오늘 드래그): 프론트가 `reservations.py PUT`을 호출 (`dateCrossMutation`, `useGuestMove.ts:313`) → #6 경로로 해결
- 시나리오 #2 (드래그+연박): #1 + #8 (extend_stay에서 check_out_pinned 자동 세팅)
- 시나리오 #4 (조합): 위 모두 누적 효과

**그 외 동작은 불변** (검증 항목):
- naver_sync가 신규 예약을 가져오면? → existing 없으니 `_create_reservation` 경로, pinned 영향 없음
- naver_sync가 다른 필드(name/phone 등)만 바꾸면? → check_in_date 자체가 변경 안 되니 가드 무관
- pinned=True인 예약을 사용자가 또 다시 수정 PUT? → setattr가 그대로 변경, pinned는 True 유지 (idempotent)
- 자동 객실 배정/내부 처리? → check_in_date 안 건드림

### D. Catch-up — pin 자동 해제 (⚫ 정리 — 호환성)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 9 | `naver_sync._update_reservation` — `if incoming_check_in > existing.check_in_date: existing.check_in_pinned = False` (네이버 측에서 더 미래로 옮긴 경우 pin 해제) | `app/services/naver_sync.py` | 추가 ~5 lines |
| 10 | 동일 함수 — `if incoming_end > existing.check_out_date: existing.check_out_pinned = False` (기존 `manually_extended_until` 의 catch-up 로직과 의미적 일치 확인 필요) | `app/services/naver_sync.py` | 추가 ~5 lines |

**동작 동등성 검토 포인트**:
- 기존 `manually_extended_until` 카치업 조건은 `incoming_end >= manually_extended_until` (설계안 §2-4)
- 신규 조건은 `incoming_end > existing.check_out_date`
- **두 조건의 의미가 일치하지 않을 수 있음** — 사전조사 문서에서 케이스 비교 필요
- 이 단계는 **반드시 #8 이후**에 진행 (extend_stay에서 두 플래그를 함께 세팅한 상태에서 catch-up 적용)

### E. Mutator 클래스 라우팅 (⚫ 리팩토링)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 11 | `reservation_mutator.py` — `apply_changes(db, reservation, source, fields)` 실제 구현 (FIELD_PERMISSIONS 체크 + pin 세팅을 함수 내부로 흡수) | `app/services/reservation_mutator.py` | 추가 ~80 lines |
| 12 | `reservations.py:261 update_reservation` — `setattr` 루프 + 수동 pin 세팅(#6,#7)을 `Mutator.apply(source=MANUAL)` 호출로 교체 | `app/api/reservations.py` | 치환 ~10 lines |
| 13 | `naver_sync._update_reservation` — 필드 변경 부분 + 가드(#4,#5,#9,#10)를 `Mutator.apply(source=NAVER)` 호출로 교체 | `app/services/naver_sync.py` | 치환 ~30 lines |
| 14 | `reservations_stay.py extend_stay` — `check_out_date` + `check_out_pinned` 직접 세팅을 `Mutator.apply` 호출로 교체. `reduce_extension` 도 동일 | `app/api/reservations_stay.py` | 치환 ~10 lines |

**동작 동등성**: 각 caller에서 Mutator.apply 호출로 바꿔도, Mutator 내부의 분기(`FIELD_PERMISSIONS["check_in_date"]["MANUAL"] == "always"` 등) 가 직전 단계의 if/setattr 와 1:1 매핑이 되도록 구현. 사전조사 문서에서 각 호출별 매핑 표 작성 필수.

### F. 정리 (⚫ — 의도된 동작 변화 0)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 15 | `manually_extended_until` 점진적 deprecation 검토 — 컬럼 자체는 유지하되 모든 set/check를 `check_out_pinned`로 위임. 마이그레이션 SQL: 기존 `manually_extended_until IS NOT NULL` → `check_out_pinned = True`. **별도 PR 권장**. | `app/db/models.py`, alembic | 별도 |

---

## 단계간 의존성

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15
                  └─ #6~#8 이후 4개 버그 해결됨 ─┘
                                            └─ #11~#14 Mutator 도입, 동작 불변 ─┘
```

- **롤백 안전성**: #N 롤백 시 #N-1 상태로 회귀, 시스템 동작.
- **#8 이후가 핫픽스 분기점**: #8까지만 머지해도 4개 버그 해결됨. #9~#15 는 구조 개선.
- **#15 는 별도 마일스톤 권장** — 기존 `manually_extended_until` 사용 코드가 잔존할 수 있어 grep 전수 조사 후 진행.

---

## 사전조사 문서 템플릿

각 단계별로 `docs/plans/mutator-step-NN-<slug>.md` 생성. 권장 섹션:

```markdown
# 단계 N: <제목>

## 1. 목적
- (1~2줄)

## 2. 변경 대상 코드
### 2-1. <파일>:<라인범위>
**Before** (현재 코드):
```python
<인용>
```
**After** (변경 후):
```python
<인용>
```
**변경 의도**: …

(여러 파일/위치 반복)

## 3. 동작 동등성 근거 (또는 의도된 변화 명시)
- 입력 케이스별 비교:
  - 케이스 A: 기존 결과 X → 새 결과 X ✅
  - 케이스 B: 기존 결과 Y → 새 결과 Z 🔵 (의도된 변화)
- 검증 방법: …

## 4. 영향받지 않음을 확인할 코드 경로
- (이 변경이 건드리지 않는 caller / 함수 / 테이블 목록)

## 5. 검증 체크리스트
- [ ] 변경 라인이 사전조사 §2와 정확히 일치
- [ ] backend/tests 회귀 통과
- [ ] (의도된 변화가 있다면) 해당 시나리오 수동 검증
```

---

## 미결 검토 항목 (전체 통합)

설계안 §6 미결 항목 중 마이그레이션 진행 전에 결정 필요한 것:

- [ ] **`check_in_pinned` 자동 해제 조건** (#9) — `incoming > current` 단순화가 안전한가? 기존 manually_extended_until 의미와 어긋나는 케이스 없는가?
- [ ] **`is_split_managed` / `gender_manual`** 처리 — 본 마이그레이션 범위에 포함? 별도 후속?
- [ ] **`SYSTEM` source** — #11에서 어떤 caller가 SYSTEM으로 분류되는가? (자동 객실 배정, reconcile 내부 등)
- [ ] **기존 `manually_extended_until` 데이터 마이그레이션** (#15) — 데이터 백필 SQL 필요
- [ ] **room-assignment-pipeline 설계안 ([별도](./room-assignment-pipeline-design.md))** — 어느 시점에 진행? Mutator #14 이후?

---

## 다음 액션

1. 본 분해안 검토 → 합의되면
2. 단계 #1 사전조사 문서 (`mutator-step-01-mutator-skeleton.md`) 작성
3. 검토 후 단계 #1 코드 변경 PR
4. 머지 후 단계 #2 사전조사 문서 작성 … (반복)
