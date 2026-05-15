# 단계 #1~#3 사전조사 — `chip_store.py` 스켈레톤 + `ensure_chip` + `remove_chip`

> 부모 계획: [chip-store-migration-plan.md](./chip-store-migration-plan.md) §6 단계 #1~#3
> 분류: ⚪ 인프라 — caller 0 (호출처 없음). 동작 변화 0.
> 변경 규모: `app/services/chip_store.py` 신규 (261 LOC) + `backend/tests/integration/test_chip_store.py` 신규 (16 케이스)

---

## 1. 목적

17개 파일에 분산된 `ReservationSmsAssignment` (=칩) 직접 조작 (`db.add` / `db.query().delete()`) 을 흡수할 **단일 게이트웨이 모듈**의 기초 인프라를 구축. 본 단계는 미호출 — 후속 caller 이주 PR 들의 의존성.

핵심 함수 2개:
- **`ensure_chip`** — Idempotent INSERT (race-safe SAVEPOINT). 기존 6 가지 INSERT 패턴 (`room_upgrade_common`, `surcharge`, `party3_mms`, `sms_tracking`, `chip_reconciler`, `reservations_sms`) 흡수 대상.
- **`remove_chip`** — 보호 가드 (`PROTECTED_ASSIGNED_BY = ('manual', 'excluded', 'failed')`) + force=True 우회. 13곳 DELETE 패턴 중 11곳의 silent 보호 누락 정상화 대상.

스켈레톤 4 함수 (`delete_chips_for_reservation`, `delete_chips_for_schedule`, `record_sent`, `record_failed`) 는 `NotImplementedError` — 단계 #4~#6 에서 구현.

---

## 2. 변경 대상 코드

### 2-1. 신규 파일: `app/services/chip_store.py` (261 LOC)

전체 신규. 기존 파일 변경 0.

| 영역 | 라인 | 내용 |
|---|---|---|
| 모듈 docstring | 1~25 | 목적 + PR 분할 정책 + 참조 plan |
| import | 26~36 | stdlib, sqlalchemy, app.db.models, app.db.tenant_context, app.diag_logger |
| 상수 `PROTECTED_ASSIGNED_BY` | 41 | `('manual', 'excluded', 'failed')` — OQ-1/OQ-5 결정 |
| `ensure_chip` | 44~124 | 본 단계 구현 |
| `remove_chip` | 127~187 | 본 단계 구현 |
| 스켈레톤 (`delete_chips_for_reservation` 외 3종) | 194~261 | `NotImplementedError` — PR2/PR3 |

### 2-2. 신규 파일: `backend/tests/integration/test_chip_store.py` (260 LOC)

기존 테스트 영향 0. 신규 16 케이스.

---

## 3. 동작 동등성 근거

### 3-1. 기존 코드 변경 0

본 단계는 caller 가 0건. 따라서 어떤 기존 함수/엔드포인트의 행동도 변경하지 않음.

검증: `grep -rn "chip_store\|chip_store\." app/` → 단계 #1~#3 후에도 정의 1건만 (사용처 0).

### 3-2. `ensure_chip` 의 race-safe 패턴은 `room_upgrade_common.ensure_chip` 와 동형

본 단계 신규 함수가 후속 PR (#10) 에서 `room_upgrade_common.ensure_chip` 를 대체할 예정. 따라서 race 처리 패턴이 동등해야 함.

| 패턴 | `room_upgrade_common.ensure_chip` (line 165~219) | `chip_store.ensure_chip` (line 44~124) |
|---|---|---|
| 매칭 키 | (reservation_id, template_key, date) | (reservation_id, template_key, date) — DB unique 일치 |
| 기존 칩 있을 시 | `return` (None) | `return existing` (객체) — 후속 caller 활용 가능 |
| SAVEPOINT | `db.begin_nested()` | 동일 |
| IntegrityError | `diag(f"{prefix}.chip_insert_race")` → return None | `diag("chip_store.ensure.race")` → 재조회 후 return existing |
| diag 키 prefix | caller 가 지정 (4 변형) | 단일 (`chip_store.ensure.created/race`) — 가시화 일관성 ↑ |
| tenant_id | `get_session_tenant_id(db)` 명시 | 동일 |

**동작 동등성**: 본 단계는 미호출이라 의미 없음. 후속 #10 에서 1:1 매핑 검증.

### 3-3. `remove_chip` 의 보호 가드는 ded670f 의 chip_reconciler:341~378 패턴 일반화

`services/chip_reconciler.py:341` `_sync_chips_for_schedule` 가 이미 사용 중인 보호 로직:

```python
# chip_reconciler.py:341~378 (현재)
existing_chips = db.query(ReservationSmsAssignment).filter(
    ReservationSmsAssignment.schedule_id == schedule.id,
    ReservationSmsAssignment.date == date,
    ~ReservationSmsAssignment.reservation_id.in_(target_ids),
    ReservationSmsAssignment.sent_at.is_(None),
    ~ReservationSmsAssignment.assigned_by.in_(['manual', 'excluded'])
).delete(synchronize_session='fetch')
```

→ 본 단계의 `remove_chip(force=False)` 가드 = 위 패턴에 `'failed'` 추가 (OQ-5).

`'failed'` 추가의 영향:
- 현재 11곳에서 `assigned_by='failed'` 칩이 어떻게 처리되는지 확인 → 일부에서 silent 삭제됨 (`sms.failed_recorded` 중복 발화의 일부 원인 가능성)
- 후속 #11 (chip_reconciler 이주) 시점에 실제 매핑 검증

본 단계는 미호출이라 행동 변화 0.

---

## 4. 시나리오별 결과 (본 단계는 미호출이므로 단위테스트 시나리오로 대체)

| 시나리오 | 함수 호출 | 결과 | 판정 |
|---|---|---|---|
| 새 auto 칩 생성 | `ensure_chip(res=1, key='k', date='D', assigned_by='auto')` | row 1 INSERT, returns object | ✅ |
| 같은 키 중복 호출 | `ensure_chip` 동일 인자 2회 | row 1 만, 같은 객체 반환 | ✅ |
| manual 칩 자동 삭제 시도 | `remove_chip(force=False)` on manual chip | 0 deleted, 보존 | ✅ ⭐ OQ-1 |
| excluded 칩 자동 삭제 시도 | 동일 | 0 deleted | ✅ |
| failed 칩 자동 삭제 시도 | 동일 | 0 deleted | ✅ ⭐ OQ-5 |
| sent_at 있는 칩 자동 삭제 시도 | 동일 | 0 deleted | ✅ |
| cancel cascade — manual 칩 | `remove_chip(force=True)` | 1 deleted | ✅ ⭐ OQ-2 |
| cancel cascade — sent 칩 | 동일 | 1 deleted | ✅ |
| schedule_id 매칭 (특정 스케줄만) | `remove_chip(schedule_id=s1)` | s1 만 삭제, s2 skip | ✅ ⭐ OQ-3 |
| schedule_id=None 매칭 | `remove_chip(schedule_id=None, template_key='k')` | NULL 인 칩만 매칭 | ✅ |

전체 16 케이스 모두 PASS (실제 실행 결과).

---

## 5. 영향받지 않음을 확인할 코드 경로

본 단계는 신규 파일만 추가하므로 기존 코드 0 변경:

- `app/services/chip_reconciler.py` — 변경 0
- `app/services/surcharge.py` — 변경 0
- `app/services/party3_mms.py` — 변경 0
- `app/services/sms_tracking.py` — 변경 0
- `app/services/room_upgrade_common.py` — 변경 0
- `app/services/reservation_lifecycle.py` — 변경 0
- `app/api/reservations_sms.py` — 변경 0
- `app/api/reservations_stay.py` — 변경 0
- `app/api/reservations_shared.py` — 변경 0
- `app/api/templates.py` — 변경 0
- `app/api/template_schedules.py` — 변경 0
- `app/scheduler/template_scheduler.py` — 변경 0

검증: `git diff f8c55dc..HEAD --stat | grep -v "chip_store\|test_chip_store\|chip-store" | grep -v "^$"` → 0 라인.

---

## 6. 검증 체크리스트

- [x] **syntax**: `python -m py_compile app/services/chip_store.py` 통과
- [x] **import**: 6 함수 + 1 상수 모두 import 성공
- [x] **단위 테스트**: 16 / 16 PASS (`pytest tests/integration/test_chip_store.py -v`)
- [x] **외부 참조 (caller site)**: `grep -rn "from app.services.chip_store" app/` → 0건 (의도)
- [x] **회귀 비교**: 기존 테스트 영향 0 (caller 0)
- [x] **diag-golden 영향**: 0 (chip_store.* 이벤트는 아직 emit 없음. 단계 #4~#6 후 첫 발화 시 pending 등록 예정)

---

## 7. 본 단계 이후의 후속 의존성

- **#4 (PR2)**: `delete_chips_for_reservation` 구현 — `on_status_cancelled` / `on_reservation_deleted` 가 호출 예정 (PR9)
- **#5 (PR2)**: `delete_chips_for_schedule` 구현 — `templates.py:351` / `template_schedules.py:518` 이주 (PR10)
- **#6 (PR3)**: `record_sent` / `record_failed` 구현 — `sms_tracking.py` 이주 (PR4)
- **#7~#14**: caller 별 이주 — 각 단계마다 본 사전조사 패턴 동일 적용
- **#15 (PR11)**: CI lint — `check_chip_lint.sh`

---

## 8. 머지 후 다음 액션

- `chip-store-step-04-05-delete-ranges.md` 작성 (PR2)
- `chip_store.delete_chips_for_reservation` / `delete_chips_for_schedule` 구현 + 단위 테스트

---

## 9. 회귀 위험 평가

| 위험 카테고리 | 평가 | 근거 |
|---|---|---|
| 기존 기능 회귀 | **없음** | caller 0 — 어떤 기존 코드 경로도 안 거침 |
| 데이터 무결성 | **없음** | DB 스키마 변경 0, 직접 INSERT/DELETE 새로 발생 0 |
| 성능 영향 | **없음** | 호출 0 |
| 보안 영향 | **없음** | tenant_id 자동 주입은 기존 ContextVar 패턴 사용 |
| diag-golden 회귀 | **없음** | `chip_store.*` 신규 이벤트 (아직 발화 0). 기존 이벤트 영향 0 |

**판정**: ⚪ 인프라 단계, 회귀 위험 0. 단순 merge 가능.
