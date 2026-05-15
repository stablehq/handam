# Chip Store 마이그레이션 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: 사전조사 완료 (OQ 모두 결정) — PR1 진입 가능
> 부모 설계: 이 문서 §1 "현황 진단"
> 관련 마이그레이션: [mutator-migration-plan.md](./mutator-migration-plan.md) (완료), [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) (완료)
> 사상: ded670f 의 RoomAssignment 통합과 동형 — 같은 비대칭 위험, 같은 해결책

---

## 원칙 (Mutator/Lifecycle 마이그레이션과 동일)

1. **기존 기능 변화 금지** — 의도된 변화 (silent 보호 누락 11곳 정상화) 만 허용. 그 외 silent behavior change 0
2. **각 단계는 별도 PR + 별도 사전조사 문서** — `chip-store-step-NN-*.md`
3. **각 사전조사 문서에 Before/After 코드 인용 + 동작 동등성 근거 명시**
4. **각 단계는 직전 단계와 독립** — 단계 #N 롤백 시 시스템 동작
5. **함수보다 세세한 단위 검증** — 라인 단위 인용 + diag-golden 정답지 비교

---

## 1. 현황 진단

### 1-1. 직접 조작 위치 (정확한 카운트)

```
17 파일 · 30+ 직접 조작 지점
├─ INSERT 8곳   (db.add(ReservationSmsAssignment(...)) )
├─ DELETE 13곳  (db.query(...).delete(...))
├─ UPDATE N곳   (sent_at, assigned_by 직접 setattr)
└─ SELECT N곳   (필터링용, 본 계획 범위 외)
```

### 1-2. INSERT 8곳 — **6 자체 구현, 2 공통 헬퍼**

| 파일 | 라인 | 어떤 칩 | 패턴 |
|------|------|--------|------|
| `room_upgrade_common.py` | 196 | upgrade promise/review | **공통 헬퍼** (`ensure_chip`) |
| `surcharge.py` | 213 | 추가요금 | **자체 구현** (`_ensure_chip`) |
| `party3_mms.py` | 112, 201 | 파티3 MMS | **자체 inline** |
| `sms_tracking.py` | 90, 136 | 발송 결과 (sent/failed) | **자체 inline** |
| `chip_reconciler.py` | 311, 371 | 기본 SMS | **자체 inline** |
| `reservations_sms.py` | 52, 116 | 운영자 수동 토글 | **자체 inline** |

→ 같은 일을 **6 가지 다른 방식**. 필드 누락·중복 INSERT·잘못된 default 사고 vector.

### 1-3. ⚠️ DELETE 13곳 — 삭제 보호의 비대칭 (가장 큰 위험)

```
✅ "올바른 보호" (sent_at + manual/excluded) — 2곳
❌ "부분 보호" (sent_at 만, manual/excluded 가드 누락) — 11곳
```

| 파일 | 라인 | sent_at | manual/excluded | 의도? |
|------|------|---------|-----------------|------|
| `templates.py` | 351 | ✅ | ✅ | 정답 |
| `template_schedules.py` | 518 | ✅ | ✅ | 정답 |
| `surcharge.py` | 257 | ✅ | ❌ | 🚨 OQ-1 |
| `room_upgrade_common.py` | 275 | ✅ | ❌ | 🚨 OQ-1 |
| `reservation_lifecycle.py` | 184 (cc1/cc2) | ✅ | ❌ | 🚨 OQ-2 |
| `reservation_lifecycle.py` | 247 (delete) | (없음) | (없음) | force=True 추정 (예약 cascade) |
| `chip_reconciler.py` | 다수 | 일부만 | ❌ | 🚨 OQ-1 |
| 외 4곳 | ... | 일부만 | ❌ | 🚨 |

📌 **단순 DRY 위반이 아니라 실재하는 silent 버그**. 운영자가 `assigned_by='manual'` 로 만든 칩이 11곳에서 보호 안 됨.

### 1-4. 가드 키 불일치

같은 의도 ("스케줄 변경 시 칩 정리") 인데 두 가지 키로:

```python
# templates.py:347~351 (template_key 기준)
ReservationSmsAssignment.template_key == db_template.template_key

# template_schedules.py:514~518 (schedule_id 기준)
ReservationSmsAssignment.schedule_id == schedule_id

# surcharge.py:252~257 (schedule_id 기준)
ReservationSmsAssignment.schedule_id.in_(surcharge_schedule_ids)
```

→ template_key 가 같지만 schedule_id 다른 칩이 있으면 한쪽은 잡고 다른 쪽은 못 잡음. **OQ-3 에서 결정**.

---

## 2. 의도된 동작 변화 (= 해결 대상)

| # | 누락/버그 | 현재 위치 | 영향 |
|---|---|---|---|
| 1 | manual/excluded 칩 silent 삭제 가능 (11 DELETE 위치) | surcharge, room_upgrade, lifecycle, chip_reconciler 외 | 운영자가 수동 표시한 칩이 reconcile 사이클에서 사라짐 |
| 2 | INSERT 패턴 6 가지 다른 방식 | 위 표 8 위치 | 필드 누락 (`tenant_id` / `schedule_id` 등) 시 silent 잘못된 매칭 |
| 3 | 가드 키 `template_key` vs `schedule_id` 혼재 | templates vs template_schedules vs surcharge | 같은 칩이 한 쪽은 잡히고 다른 쪽은 안 잡힘 — 비결정적 reconcile |
| 4 | room_upgrade_common 의 ensure_chip 만 idempotent, 나머지는 중복 INSERT 가능성 | sms_tracking / chip_reconciler 등 | 동일 (예약, 템플릿, 날짜) 칩이 중복 생성 가능 |

---

## 3. Non-goals (안 다룸)

- **칩 종류 자체 추가/제거** — 5종 칩 (basic/surcharge/party3/upgrade_promise/upgrade_review) 그대로 유지
- **reconcile_all_chips 진입점 변경** — 외부 API 유지
- **DB 스키마 변경** — `ReservationSmsAssignment` 컬럼 그대로
- **diag-golden 정답지 일괄 갱신** — 단계별로 영향 받는 정답지만 검증
- **`record_sent` 의 발송 후 INSERT 동작 정책 변경** — OQ-4 에서 결정 후 별도 처리

---

## 4. 정책 결정 (OQ — Open Questions, 확정 완료)

> ✅ 2026-05-15 사용자 확정. 본 섹션 기준으로 PR 진행.

### 정책 매트릭스 (핵심 요약)

| 시나리오 | `force` | manual/excluded/failed 칩 처리 |
|---------|---------|---------|
| **자동 reconcile** (surcharge / room_upgrade / chip_reconciler / sync_sms_tags 외) | **False** | 보호 (운영자 의도 존중) |
| **`on_status_cancelled`** (예약 취소 — 당일/사전) | **True** | 모두 삭제 (손님 안 옴 → SMS 보낼 이유 없음) |
| **`on_reservation_deleted`** (예약 row DELETE) | **True** | cascade 모두 삭제 (예약 자체 사라짐) |
| **템플릿/스케줄 삭제·비활성** (`templates.py:351` / `template_schedules.py:518`) | **False** | 현재 가드 그대로 (이미 올바름) |

원칙: **자동 reconcile 은 manual 보호, 명시적 lifecycle 이벤트는 cascade 정리**.

### OQ-1 ✅ manual/excluded 칩은 **자동 reconcile 사이클에서 보호**

**현재 비대칭** (11곳이 `sent_at NULL` 만 가드, manual/excluded 가드 없음) → **모든 자동 reconcile 경로에 manual/excluded/failed 가드 추가**.

**시나리오 검증**:
- **A. 운영자 수동 환영 SMS**: 김주임이 res=5001 에 "VIP 환영 인사" 추가 (`assigned_by='manual'`). 다른 예약 surcharge reconcile 사이클이 돌아도 김주임 칩 보존 ✅
- **B. 명시적 발송 제외**: 외국인 손님에게 `assigned_by='excluded'` 토글 → 자동 reconcile 이 매번 다시 만들지 못함 ✅

### OQ-2-a ✅ 예약 **취소** 시 manual/excluded 도 cascade 삭제 (`force=True`)

**시나리오**: res=5005 (홍길동, 5/14 도착) 에 5/12 운영자가 manual 환영 SMS 추가. 5/13 취소 → `on_status_cancelled` 발동 → 모든 칩 정리 (manual 포함).

**근거**: 손님이 안 옴 → 어떤 SMS 도 보낼 이유 없음. 보호하면 취소된 손님에게 SMS 발송 위험.

### OQ-2-b ✅ 예약 **row 삭제** 시 cascade 모두 삭제 (`force=True`)

**시나리오**: 운영자가 잘못 만든 테스트 예약 휴지통 클릭 → 예약 row + 모든 칩 정리.

**근거**: 예약 row 자체가 사라지는데 칩만 남으면 orphan. 데이터 무결성 위반.

### OQ-3 ✅ 가드 키 — **`schedule_id` 우선 + `template_key` fallback**

**시나리오**: "객실 비밀번호 안내" 템플릿이 schedule_id=1 (평일) + schedule_id=2 (주말) 둘에 연결. schedule_id=2 비활성화 시 주말 칩만 정리.

```python
# chip_store.remove_chip 매칭 로직
if schedule_id is not None:
    filter += [ReservationSmsAssignment.schedule_id == schedule_id]
else:
    filter += [
        ReservationSmsAssignment.template_key == template_key,
        ReservationSmsAssignment.schedule_id.is_(None),  # 운영자 수동 칩
    ]
```

### OQ-4 ✅ `record_sent` 칩 없을 시 신규 INSERT — **정상 흐름**

**시나리오**: 운영자가 "이벤트 SMS 즉시 발송" UI 에서 res=5010 에게 발송 → reconcile 없이 직발송 → 발송 후 record_sent 가 칩 신규 생성 (기록 보존).

**보강 결정**: `ensure_chip` 의 idempotent 가드로 race (스케줄러 + record_sent 동시 실행) 시 unique 충돌 방지 — 이미 있으면 그대로 반환.

### OQ-5 ✅ `failed` 칩 — **영구 보호** (운영자 개입 대기)

**시나리오**: res=5099 phone='010655<2887' 오타 → 13:10 발송 실패 → `assigned_by='failed'` 칩.

- 다음날 reconcile → failed 칩 보존 → 운영자 화면 ⚠️
- 운영자 phone 수정 후 재발송: 별도 UI 기능 필요 (failed → manual 전환 또는 force delete 후 새 자동 칩)

**Non-goal**: failed 재발송 UI 기능은 본 마이그레이션 외 별도 작업.

---

## 5. 최종 모습 — `chip_store` 모듈 API

```python
# app/services/chip_store.py

def ensure_chip(
    db, *,
    reservation_id: int,
    template_key: str,
    date: str,
    assigned_by: str = "auto",
    schedule_id: int | None = None,
    **extra,
) -> ReservationSmsAssignment:
    """Idempotent INSERT — 이미 존재하면 그대로 반환, 없으면 생성.

    매칭 키 (OQ-3):
      - schedule_id 가 있으면: (reservation_id, schedule_id, date)
      - schedule_id 가 None 이면: (reservation_id, template_key, date) + schedule_id IS NULL
    tenant_id 자동 주입 (ContextVar). 중복 INSERT 방지.
    """

def remove_chip(
    db, *,
    reservation_id: int,
    template_key: str,
    date: str,
    force: bool = False,
) -> int:
    """단건 삭제.
    
    force=False (기본): sent_at IS NULL AND assigned_by NOT IN ('manual', 'excluded', 'failed')
    force=True: 무조건 삭제 (예약 cascade 등 명시적 의도)
    """

def delete_chips_for_reservation(
    db, *,
    reservation_id: int,
    dates: list[str] | None = None,
    template_keys: list[str] | None = None,
    schedule_ids: list[int] | None = None,
    force: bool = False,
) -> int:
    """범위 삭제 — 예약 단위. 옵션 dates/template_keys/schedule_ids 조합."""

def delete_chips_for_schedule(
    db, *,
    schedule_id: int,
    force: bool = False,
) -> int:
    """스케줄 단위 — 템플릿/스케줄 삭제·비활성 시."""

def record_sent(
    db, *,
    reservation_id: int,
    template_key: str,
    date: str | None = None,
    sent_at: datetime | None = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 성공 기록 — 기존 칩 update or 신규 (OQ-4 결정 반영)."""

def record_failed(
    db, *,
    reservation_id: int,
    template_key: str,
    error: str | None = None,
    **extra,
) -> ReservationSmsAssignment:
    """발송 실패 기록."""
```

---

## 6. 단계 분해 (15 단계)

각 단계의 **실제 동작 변화 유무** 명시:
- ⚪ 동작 변화 없음 (구조/인프라)
- 🔵 의도된 변화 (silent 보호 누락 정상화)
- ⚫ 정리/리팩토링 (동작 동등)

### A. 기초 인프라 (⚪ 동작 변화 없음)

| # | 작업 | 변경 파일 | 변경량 |
|---|---|---|---|
| 1 | `chip_store.py` 스켈레톤 — 6 함수 signature 만 (`NotImplementedError`) | `app/services/chip_store.py` (신규) | 추가 ~80 lines |
| 2 | `ensure_chip` 구현 + 단위 테스트 | 동일 | 수정 ~30 lines |
| 3 | `remove_chip` 구현 + 가드 테스트 | 동일 | 수정 ~30 lines |
| 4 | `delete_chips_for_reservation` 구현 | 동일 | 수정 ~30 lines |
| 5 | `delete_chips_for_schedule` 구현 | 동일 | 수정 ~25 lines |
| 6 | `record_sent` + `record_failed` 구현 (OQ-4 정책 반영) | 동일 | 수정 ~50 lines |

**동작 동등성**: caller 0건. import 만 됨.

### B. caller 이주 (🔵 OQ-1/OQ-2 결정 반영, 외 ⚫)

Easy → Hard 순. 가장 격리된 곳부터.

| # | 작업 | 변경 파일 | 위험 |
|---|---|---|---|
| 7 | `sms_tracking.py` 이주 — `record_sms_sent` / `record_sms_failed` → `chip_store.record_*` | `app/services/sms_tracking.py` | 🟡 OQ-4 결정 반영 |
| 8 | `surcharge.py` 이주 — `_ensure_chip` / `_remove_chip` / `_delete_all_surcharge_chips` 제거 → chip_store 호출 | `app/services/surcharge.py` | 🚨 OQ-1 (manual 가드 추가) |
| 9 | `party3_mms.py` 이주 — inline INSERT → `ensure_chip` | `app/services/party3_mms.py` | 🟡 |
| 10 | `room_upgrade_common.py` 이주 — 자체 헬퍼 → `chip_store` 위임 | `app/services/room_upgrade_common.py` | ⚫ 위임만 |
| 11 | `chip_reconciler.py` 이주 | `app/services/chip_reconciler.py` | 🚨 OQ-1 (가장 영향 큼) |
| 12 | `reservations_sms.py` 이주 (운영자 토글) | `app/api/reservations_sms.py` | 🟡 운영자 즉시 영향 |
| 13 | `reservation_lifecycle.py` 이주 — cc1/cc2 + on_reservation_deleted | `app/services/reservation_lifecycle.py` | 🚨 OQ-2 결정 반영 |
| 14 | 잔여 4 파일 이주 — `reservations_stay.py` / `reservations_shared.py` / `templates.py` / `template_schedules.py` | 4 파일 | 🟡 일부는 이미 올바른 가드 |

### C. 회귀 차단 (⚪ 인프라)

| # | 작업 | 변경 파일 |
|---|---|---|
| 15 | CI Lint 추가 — `scripts/check_chip_lint.sh` — `db.add(ReservationSmsAssignment(...))` / `db.query(ReservationSmsAssignment).delete()` 가 `chip_store.py` 외부 → fail | `backend/scripts/check_chip_lint.sh` (신규) + CI 통합 |

---

## 7. 단계별 위험 매트릭스

| 단계 | 위험 | 검증 방법 |
|------|------|---------|
| #1~#6 | 0 (미호출) | py_compile + 단위테스트 |
| #7 sms_tracking | sent/failed 기록 회귀 | diag-golden `sms.failed_recorded` 케이스 비교 |
| #8 surcharge | **추가요금 칩 silent 삭제 회귀** | manual 칩 시나리오 + 5/12 res=5254/5255 케이스 |
| #9 party3_mms | party3 MMS reconcile 회귀 | `_draft/chip-reconcile-party3-mms` 정답지 비교 |
| #10 room_upgrade | 부수효과 큼 (5종 중 2종 이주) | `_draft/room-upgrade-promise/review-batch` 정답지 비교 |
| #11 chip_reconciler | reconcile_all_chips 의 1번째 단계 | 모든 다이어그램 정답지 |
| #12 reservations_sms | 운영자 토글 즉시 영향 | UI 시나리오 테스트 |
| #13 lifecycle | **OQ-2 정책 변경** | 정책 결정 필요 + 회귀 모니터링 |
| #14 잔여 | 작음 | 표 |
| #15 lint | 회귀 차단 | dry-run pass |

---

## 8. 예상 이득

| 항목 | 이전 | 이후 |
|------|------|------|
| 칩 직접 조작 위치 | 17 파일 / 30+ 지점 | **2 파일** (chip_store + db/models) |
| 삭제 보호 비대칭 | 13곳 중 2곳만 완전 보호 | **모든 곳 자동 보호** (force=True 만 우회) |
| INSERT 패턴 | 6 가지 다른 방식 | **1 가지** (`ensure_chip`) |
| 가드 키 불일치 | template_key vs schedule_id 혼재 | **통일** (OQ-3 결정 반영) |
| 새 caller 추가 시 | 30개 패턴 중 어떤 거? 가드 빼먹지 마! | `ensure_chip` 1번 호출 |
| 새 칩 종류 추가 시 | 6 가지 방식 중 골라 복붙 | `chip_store` 1곳 확장 |
| CI 보호 | 없음 — 회귀 가능 | **lint 차단** |

LOC 감소 예상: ~200 LOC + 18 파일 단순화.

---

## 9. PR 분할

```
PR1   chip_store 스켈레톤 + ensure_chip + remove_chip   (단계 #1~#3)
PR2   delete_chips_for_reservation + delete_chips_for_schedule  (#4~#5)
PR3   record_sent + record_failed (OQ-4 정책 반영)       (#6)
PR4   sms_tracking 이주                                  (#7)
PR5   surcharge 이주 + OQ-1 정책 검토 결과 반영           (#8)
PR6   party3_mms + room_upgrade_common 이주              (#9~#10)
PR7   chip_reconciler 이주                               (#11)
PR8   reservations_sms 이주                              (#12)
PR9   lifecycle 이주 (OQ-2 결정 반영)                     (#13)
PR10  잔여 4 파일 이주                                    (#14)
PR11  CI lint 추가                                       (#15)
```

각 PR 후 diag-golden 검증 회차 실행 → 정답지 어긋남 0건 확인 후 다음 PR.

---

## 10. 진행 상태 (체크리스트)

- [x] OQ-1 결정 — manual/excluded 보호 (자동 reconcile 사이클)
- [x] OQ-2-a 결정 — 예약 취소 시 cascade 삭제 (force=True)
- [x] OQ-2-b 결정 — 예약 row 삭제 시 cascade (force=True)
- [x] OQ-3 결정 — schedule_id 우선 + template_key fallback
- [x] OQ-4 결정 — 신규 INSERT 정상 (ensure_chip idempotent)
- [x] OQ-5 결정 — failed 칩 영구 보호 (재발송 UI 별도)
- [ ] PR1 (#1~#3)
- [ ] PR2 (#4~#5)
- [ ] PR3 (#6)
- [ ] PR4 (#7 sms_tracking)
- [ ] PR5 (#8 surcharge)
- [ ] PR6 (#9~#10 party3 + room_upgrade)
- [ ] PR7 (#11 chip_reconciler)
- [ ] PR8 (#12 reservations_sms)
- [ ] PR9 (#13 lifecycle)
- [ ] PR10 (#14 잔여)
- [ ] PR11 (#15 lint)
