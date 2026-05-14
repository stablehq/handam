# Lifecycle 마이그레이션 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: 단계 분해안
> 부모 설계: [room-assignment-pipeline-design.md](./room-assignment-pipeline-design.md)
> 관련 마이그레이션: [mutator-migration-plan.md](./mutator-migration-plan.md) (선행, 완료)

---

## 원칙 (Mutator 마이그레이션과 동일)

1. **기존 기능 변화 금지** — 의도된 변화 (5개 누락 패턴 해결) 만 허용. 그 외 silent behavior change 0
2. **각 단계는 별도 PR + 별도 사전조사 문서** — `lifecycle-step-NN-*.md`
3. **각 사전조사 문서에 Before/After 코드 인용 + 동작 동등성 근거 명시**
4. **각 단계는 직전 단계와 독립** — 단계 #N 롤백 시 시스템 동작
5. **함수보다 세세한 단위 검증** — 라인 단위 인용 + "이 코드가 지워지면 어디서 대신 수행하나" 명시

---

## 의도된 동작 변화 (= 해결 대상)

`room-assignment-pipeline-design.md` §2 의 실측 매트릭스에서 도출된 5개 누락 패턴:

| # | 누락 | 발생 위치 | 영향 |
|---|---|---|---|
| 1 | `extend_stay` 의 shift_daily_records 누락 | `reservations_stay.py:157` | check_out +1일 후 PartyCheckin / DailyInfo 이동 안 됨 |
| 2 | `_do_reduce_extension` 의 shift_daily_records 누락 | `reservations_stay.py:306` | 동일 |
| 3 | `reduce_extension` 의 `db.delete(ra)` 직접 호출 | `reservations_stay.py:378` | bed_order 재정렬, push-out 가드, surcharge cleanup 미실행 |
| 4 | `naver_sync` cc1 의 `db.query(RA).delete()` 직접 호출 | `naver_sync.py:795~807` | 동일 |
| 5 | 칩 reconcile 함수 3종 혼재 (full/기본/구버전) | extend/reduce/naver_sync/PUT 진입점별 불일치 | surcharge/party3/upgrade 칩 stale |

→ 5개 모두 "동일 사건 (날짜 변경 / 인원 변경 / 취소 / 배정 / 삭제) 의 후처리를 caller 책임으로 분산" 이 원인. lifecycle 함수 도입으로 책임 단일화.

---

## Non-goals (안 다룸)

- Reservation 필드 변경 (Mutator 가 처리 — 완료)
- 신규 예약 생성/삭제의 도메인 메서드 통합 (별도 마일스톤)
- `room_auto_assign` 의 배치 최적화 (성능 이슈 별도)
- `stay_group` unlink + peer sync_sms_tags 의 lifecycle 흡수 (caller 책임 유지)
- DDD Aggregate 풀버전

---

## 단계 분해 (22단계)

각 단계의 **실제 동작 변화 유무** 명시:
- ⚪ 동작 변화 없음 (구조/인프라)
- 🔵 의도된 변화 (5 누락 패턴 중 하나 해결)
- ⚫ 정리/리팩토링 (동작 동등)

### A. 기초 인프라 (⚪ 동작 변화 없음)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 1 | `unassign_dates(reservation_id, dates: list[str])` 함수 신규 — `services/room_assignment.py` 내부에 추가 | `app/services/room_assignment.py` | 추가 ~25 lines |
| 2 | `reservation_lifecycle.py` 신규 — 5개 lifecycle 함수 스켈레톤 (`NotImplementedError`) | `app/services/reservation_lifecycle.py` (신규) | 추가 ~60 lines |

**동작 동등성**: 어디서도 호출 안 함. `unassign_dates` 는 caller 0건, lifecycle 함수도 caller 0건.

### B. RoomAssignment 직접 조작 제거 (🔵 누락 패턴 #3, #4 해결)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 3 | `reservations_stay.py:378` `db.delete(ra)` → `unassign_dates(reservation_id, dates_to_remove)` 호출 | `app/api/reservations_stay.py` | 수정 ~5 lines |
| 4 | `naver_sync.py:795~807` 직접 `db.query(RA).filter().delete()` → `unassign_dates` 호출 | `app/services/naver_sync.py` | 수정 ~10 lines |

**해결되는 누락**:
- 패턴 #3 (`reduce_extension` 의 bed_order 미정렬) — #3 으로 해결
- 패턴 #4 (`naver_sync` cc1 의 bed_order 미정렬) — #4 로 해결

**분기점**: **#4 머지 = bed_order 정렬 누락 해결 분기점**

### C. lifecycle 함수 실제 구현 (⚪ caller 호출 0건, 호출 시점에 발동)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 5 | `on_dates_changed(db, reservation, old_check_in, old_check_out)` 실제 구현 (shift_daily + reconcile_dates + reconcile_all_chips) | `app/services/reservation_lifecycle.py` | 수정 ~20 lines |
| 6 | `on_constraints_changed(db, reservation, changed_fields)` 실제 구현 (invariant + unassign + reconcile_all_chips) | 동일 | 수정 ~30 lines |
| 7 | `on_status_cancelled(db, reservation, *, same_day: bool)` 실제 구현 (cc1/cc2 분기 흡수) | 동일 | 수정 ~25 lines |
| 8 | `on_room_assigned(db, reservation, pushed_out)` 실제 구현 (reconcile_all_chips + push-out 칩 재계산) | 동일 | 수정 ~15 lines |
| 9 | `on_reservation_deleted(db, reservation_id)` 실제 구현 (clear_all + 칩 정리) | 동일 | 수정 ~15 lines |

**동작 동등성**: 단계 #5~#9 머지 시점에는 caller 가 호출 안 함. 단위 테스트만 cover.

### D. caller 전환 (⚫ 리팩토링 + 🔵 누락 해결)

| # | 작업 | 변경 파일 | 코드 변경량 | 해결 누락 |
|---|---|---|---|---|
| 10 | `reservations.py:261 update_reservation` 날짜 변경 분기 → `on_dates_changed` 호출 | `app/api/reservations.py` | 치환 ~5 lines | — (기존 동작 유지) |
| 11 | `reservations.py:261 update_reservation` 인원 변경 분기 → `on_constraints_changed` 호출 | 동일 | 치환 ~30 lines | — |
| 12 | `reservations.py:459 delete_reservation` → `on_reservation_deleted` 호출 | 동일 | 치환 ~5 lines | — |
| 13 | `naver_sync._update_reservation` 날짜 변경 분기 → `on_dates_changed` 호출 | `app/services/naver_sync.py` | 치환 ~5 lines | **#5 (칩 reconcile)** |
| 14 | `naver_sync._update_reservation` 인원 변경 분기 → `on_constraints_changed` 호출 | 동일 | 치환 ~30 lines | — |
| 15 | `naver_sync` cc1/cc2 분기 → `on_status_cancelled(same_day=…)` 호출 | 동일 | 치환 ~50 lines | — |
| 16 | `reservations_stay.py:157 extend_stay` → `on_dates_changed` + `on_room_assigned` 호출 | `app/api/reservations_stay.py` | 추가 ~10 lines | **#1 (shift_daily), #5 (칩)** |
| 17 | `reservations_stay.py:306 _do_reduce_extension` → `on_dates_changed` 호출 | 동일 | 추가 ~5 lines | **#2 (shift_daily), #5 (칩)** |
| 18 | `reservations_room.py:45 assign_room` PUT 핸들러 → `on_room_assigned` 호출 추가 | `app/api/reservations_room.py` | 추가 ~5 lines | — |
| 19 | `room_auto_assign.py:425/446` → `on_room_assigned` 호출 추가 (매 배정마다, 보수적 default) | `app/services/room_auto_assign.py` | 추가 ~3 lines | — |

**분기점**:
- **#17 머지 = 칩 reconcile 비대칭 + shift_daily 누락 해결 분기점** (가장 큰 운영 효과)
- **#19 머지 = 모든 caller 가 lifecycle 통과**

### E. 정리 + 회귀 차단 (⚫)

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|---|---|---|
| 20 | `shift_daily_records` / `reconcile_dates` 외부 직접 호출 처가 0건임을 확인 → `_` prefix 로 private 화 | `app/services/room_assignment.py` 및 caller grep 검증 | rename + 호출처 갱신 |
| 21 | `reconcile_chips_for_reservation` (구버전, `chip_reconciler.py:41`) 사용처 0건 확인 후 삭제 | `app/services/chip_reconciler.py` | 함수 삭제 ~100 lines |
| 22 | CI lint 규칙 추가 — RA 직접 조작 / 구버전 함수 호출 차단 (pre-commit hook 또는 GitHub Actions) | `.github/workflows/` 또는 `pre-commit-config.yaml` | 신규 |

**분기점**: **#22 머지 = 회귀 차단 완료**

---

## 단계간 의존성

```
A. 1 → 2

B. 3 (의존: 1 의 unassign_dates)
   4 (의존: 1 의 unassign_dates)
   ↓ 분기점 #4 — bed_order 해결

C. 5 → 6 → 7 → 8 → 9 (lifecycle 구현)

D. 10, 11, 12 (의존: 5, 6, 9 — reservations.py)
   13, 14, 15 (의존: 5, 6, 7 — naver_sync)
   16 (의존: 5, 8 — extend_stay)
   17 (의존: 5 — reduce)
   ↓ 분기점 #17 — 칩 누락 해결
   18, 19 (의존: 8 — room_assignment)
   ↓ 분기점 #19 — 전체 통합

E. 20 (의존: D 전체 — 외부 호출 0건 보장)
   21 (의존: 16, 17 — extend/reduce 가 새 함수 사용)
   22 (의존: 3, 4, 21 — lint 규칙 안전)
   ↓ 분기점 #22 — 회귀 차단
```

각 분기점에서 멈춰도 그 시점까지의 효과 유지.

---

## 미결 검토 항목 결정 (default 보수 선택)

### Q1. 자동 배정 (`room_auto_assign`) 의 `on_room_assigned` 호출 빈도

**결정 (default)**: 매 배정마다 호출 (옵션 A).

근거:
- 단순하고 silent regression 없음
- 성능 이슈 (N+M 회 reconcile_all_chips 발동) 는 별도 최적화 마일스톤
- `on_batch_assigned` 같은 변형은 본 마이그레이션 범위 외

### Q2. `stay_group` unlink + peer `sync_sms_tags` 흡수 여부

**결정 (default)**: lifecycle 외부 유지 (옵션 B).

근거:
- 기존 caller (`naver_sync.py:846`, `reservations.py:369`) 가 stay_group 처리 후 peer sync_sms_tags 단발 호출
- 이걸 `on_status_cancelled` 안으로 흡수하면 의존성 ↑ + 동작 동등성 검증 ↑
- 본 마이그레이션 범위 밖, 별도 PR 권장

### Q3. lifecycle 함수 내부 `db.flush()` 위치

**결정 (default)**: caller 책임 유지 (옵션 B).

근거:
- 기존 패턴 일관 — services 함수가 flush 안 함
- caller 가 `db.commit()` / `db.flush()` 시점을 가짐
- lifecycle 함수는 ORM 객체 변경만, flush 는 caller

---

## 단계당 부속 작업 (Mutator 때와 동일)

```
1) 사전조사 문서 (lifecycle-step-NN-*.md) 작성
   - §1 목적
   - §2 변경 대상 코드 (Before/After 라인 단위 인용)
   - §3 동작 동등성 근거 (또는 의도된 변화 명시)
   - §4 매트릭스 비교 (입력 → 단계 #N 전/후 결과)
   - §5 영향받지 않음을 확인할 코드 경로
   - §6 검증 체크리스트
   - §7 후속 의존성
   - §8 미결 검토 항목

2) 코드 변경 — 사전조사 §2 의 After 그대로

3) 자동 검증
   - venv/bin/python -m py_compile <파일>
   - 단위 테스트 (lifecycle 함수마다 fakeRes 로 8~10 케이스, Mutator 때 패턴 동일)
   - 외부 참조 grep (caller 미머지 단계에서 0건 확인)
   - 매트릭스 비교 (Before vs After 의 동작 동등성 표)
   - git diff --stat 라인 수가 사전조사 §2 와 일치
```

---

## 진행 방식 — Mutator 사이클 그대로

```
1) 부모 계획 문서 작성  ← 본 문서
2) 단계 #1 사전조사 → 코드 → 검증 → 다음 …
3) 분기점 #4 / #17 / #19 / #22 도달 시 자동 검증 결과 보고
4) 전체 머지 후 최종 종합 보고 + frontend 영향 전수조사 (필요 시)
```

---

## 다음 액션

본 분해안 머지 → 단계 #1 사전조사 (`lifecycle-step-01-unassign-dates.md`) 작성 → 코드 변경 → 검증 → 단계 #2 ...
