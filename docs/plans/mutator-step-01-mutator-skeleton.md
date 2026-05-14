# 단계 #1 사전조사 — `reservation_mutator.py` 스켈레톤 생성

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §A
> 분류: ⚪ 동작 변화 없음 (인프라)
> 변경 규모: 신규 파일 1개 (~80 lines), 기존 파일 변경 0

---

## 1. 목적

`backend/app/services/reservation_mutator.py` 를 신규 생성. 본 단계의 범위는 **타입/테이블/스켈레톤만**이고, **어디서도 import/호출되지 않는다**. 후속 단계 (#11~#14) 에서 caller 가 이 파일의 클래스를 호출할 때 인터페이스를 사전에 확정하기 위한 인프라 작업.

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|---|---|
| `apply_changes()` 실제 로직 (FIELD_PERMISSIONS 평가 + setattr + pin) | #11 |
| `_run_post_processing()` 후처리 호출 | #11 |
| DB 컬럼 (`check_in_pinned`, `check_out_pinned`) | #2, #3 |
| naver_sync / reservations.py / extend_stay 코드 변경 | #4~#14 |
| 기존 `manually_extended_until` 제거 | #15 |

---

## 2. 변경 대상 코드

**기존 파일 변경**: 없음.
**신규 파일**: `backend/app/services/reservation_mutator.py` 1개.

신규 파일이라 "Before" 는 부재. "After" 의 각 섹션을 라인 단위로 설계한다.

### 2-1. 파일 헤더 + import

```python
"""ReservationMutator — Reservation 필드 변경 단일 게이트웨이 (스켈레톤).

본 모듈은 단계 #1 시점에서는 어디서도 호출되지 않는다. FIELD_PERMISSIONS /
ChangeSource 정의를 후속 단계 (#4 이후 가드 추가, #11 이후 caller 전환) 가
참조할 수 있도록 인터페이스만 노출한다.

참고: docs/plans/reservation-mutator-design.md
      docs/plans/mutator-migration-plan.md
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.db.models import Reservation
```

**각 라인 향후 사용처**:
- docstring: 변경 없음, 참조 문서로 유지
- `from __future__ import annotations`: 모든 타입 힌트를 문자열로 평가 → 순환 import 방지 (필요)
- `enum.Enum`: §2-2 `ChangeSource` 에 사용
- `TYPE_CHECKING` 분기: Session / Reservation 타입 힌트만 필요, 런타임 import 회피

### 2-2. `ChangeSource` enum

```python
class ChangeSource(str, Enum):
    """예약 필드 변경의 출처. FIELD_PERMISSIONS 의 행 인덱스."""

    NAVER = "naver"     # naver_sync._update_reservation 경로
    MANUAL = "manual"   # reservations.py PUT, reservations_stay extend/reduce, reservations_room 등 직원 조작
    SYSTEM = "system"   # 자동 객실 배정, push-out, reconcile 내부 처리, 마이그레이션 등
```

**향후 사용처**:
- 단계 #11 에서 `ReservationMutator.apply_changes(source: ChangeSource, ...)` 의 첫 파라미터 타입
- 단계 #12 에서 `Mutator.apply(source=ChangeSource.MANUAL, ...)` (reservations.py)
- 단계 #13 에서 `Mutator.apply(source=ChangeSource.NAVER, ...)` (naver_sync)
- 단계 #14 에서 `Mutator.apply(source=ChangeSource.MANUAL, ...)` (extend/reduce)

**설계 결정 근거**:
- `str` 혼합 — JSON 로그/ActivityLog detail 직렬화 시 별도 변환 불필요
- 값을 소문자 — 기존 `booking_source` 컬럼 ("naver"/"manual"/"phone") 과 컨벤션 일치 → 추후 ActivityLog 비교에 활용

### 2-3. `FIELD_PERMISSIONS` 테이블

설계안 §3-3 의 매트릭스 그대로. 단, **Reservation 모델 실제 Python 속성명** 과 1:1 매핑 검증 완료 (§3 참조).

```python
# Reservation 필드별 source 권한 — 단계 #11 부터 ReservationMutator.apply_changes 가 평가.
# 단계 #1 시점에서는 어떤 caller 도 이 테이블을 참조하지 않음.
#
# 권한 값:
#   "guarded" = 해당 필드의 pin 이 True 인 레코드에서만 skip, 아니면 덮어씀
#   "always"  = pin 무관, 항상 덮어씀
#   "never"   = 이 source 는 이 필드 변경 불가
FIELD_PERMISSIONS: dict[str, dict[ChangeSource, str]] = {
    "check_in_date":    {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    "check_out_date":   {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    "customer_name":    {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "phone":            {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "visitor_name":     {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "party_size":       {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "male_count":       {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "female_count":     {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "gender":           {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "status":           {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "section":          {ChangeSource.NAVER: "never",   ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "always"},
    "naver_room_type":  {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "never",  ChangeSource.SYSTEM: "never" },
    "booking_options":  {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "never",  ChangeSource.SYSTEM: "never" },
    "special_requests": {ChangeSource.NAVER: "always",  ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
    "total_price":      {ChangeSource.NAVER: "guarded", ChangeSource.MANUAL: "always", ChangeSource.SYSTEM: "never" },
}
```

**각 행의 정당화 — 현재 코드와 1:1 매핑**:

| 필드 | NAVER 현재 동작 | MANUAL 현재 동작 | 권한 매핑 정당화 |
|---|---|---|---|
| `check_in_date` | `naver_sync.py:672` 무조건 덮어씀 (버그) | `reservations.py PUT` 가 setattr | NAVER=guarded (#4 가드 추가 시 pin 확인), MANUAL=always (현재 동작 유지) |
| `check_out_date` | `naver_sync.py:678~702` `manually_extended_until` 가드 후 덮어씀 | `reservations.py PUT` setattr, `extend_stay` 직접 변경 | NAVER=guarded (#5 가드 추가), MANUAL=always |
| `customer_name`, `phone`, `visitor_name`, `gender`, `status`, `booking_options`, `naver_room_type` | naver 가 무조건 동기화 | reservations.py setattr | NAVER=always (현재 동작), MANUAL=always 또는 never 는 필드별로 다름 |
| `party_size`, `male_count`, `female_count` | `gender_manual` 플래그가 True 면 skip (`naver_sync.py:720`) | reservations.py setattr | NAVER=guarded — 단, 본 단계는 `gender_manual` 을 그대로 두므로 #11 에서 가드 함수가 두 플래그를 모두 참조. 본 단계 시점에서는 테이블만 선언. |
| `section` | naver 가 안 만짐 | reservations.py setattr | NAVER=never (현재 코드에서 `_update_reservation` 이 section 안 건드림 — 확인됨) |
| `total_price` | naver 동기화 | reservations.py | guarded (보호 받아야 함) |

**향후 사용처**:
- 단계 #11 의 `apply_changes()` 가 `FIELD_PERMISSIONS[field][source]` 로 조회
- 본 단계 #1 에서는 **선언만**, 참조 0개. 모든 caller 의 setattr 흐름은 직전과 동일.

### 2-4. `ReservationMutator` 클래스 스켈레톤

```python
class ReservationMutator:
    """예약 필드 변경의 단일 진입점 (스켈레톤).

    실제 구현은 단계 #11. 본 단계에서는 인터페이스만 노출하여 후속 PR 의
    이름 충돌 / signature drift 를 사전 방지한다.
    """

    @staticmethod
    def apply_changes(
        db: "Session",
        reservation: "Reservation",
        source: ChangeSource,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Reservation 필드 변경을 권한 검사 후 적용.

        Args:
            db: 호출자가 관리하는 트랜잭션. 본 함수는 flush/commit 하지 않음.
            reservation: 변경 대상 ORM 객체.
            source: 변경 출처 (NAVER / MANUAL / SYSTEM).
            fields: {필드명: 새 값} dict.

        Returns:
            {필드명: (old, new)} 형태로 실제 적용된 변경만 반환. 권한 거부된
            필드는 포함하지 않음. 후처리 함수 / ActivityLog 가 이 결과를 사용.

        Notes:
            단계 #1 시점에서는 NotImplementedError 를 raise — 호출 시도가
            있으면 즉시 가시화 (silent skip 방지).
        """
        raise NotImplementedError(
            "ReservationMutator.apply_changes is not implemented yet "
            "(see docs/plans/mutator-migration-plan.md step #11)."
        )
```

**향후 변경 지점**:
- 단계 #11 에서 `NotImplementedError` 를 실제 구현으로 교체
- 단계 #12~#14 에서 각 caller 가 이 메서드 호출
- signature 는 본 단계에서 확정 — 이후 변경 시 PR 별도 사유 명시

**설계 결정 근거**:
- `@staticmethod` — Mutator 는 상태 없음 (테이블 + 함수). 인스턴스화 강제 X
- `db` 첫 인자 — sqlalchemy 컨벤션과 일치 (다른 services/* 함수와 동일)
- `fields: dict[str, Any]` — caller 가 `{"check_in_date": "2026-05-15", ...}` 형태로 넘김. 설계안 §3-1 의 "변경할 changes dict" 와 동일
- 반환을 `{필드명: (old, new)}` 로 — caller 가 "실제로 무엇이 변했나" 를 알아야 후처리 분기 가능 (예: 날짜 변경 여부)
- `NotImplementedError` — 단계 #1 단독 머지 시 caller 가 실수로 호출하면 즉시 실패. silent regression 차단

---

## 3. Reservation 모델 컬럼 검증 (실측)

`backend/app/db/models.py` Reservation 클래스 (L42~L103) 실측 결과:

| FIELD_PERMISSIONS 키 (Python 속성) | DB 컬럼명 | 모델 라인 | 매핑 OK |
|---|---|---|---|
| `check_in_date` | `"date"` | 48 | ✅ |
| `check_out_date` | `"end_date"` | 96 | ✅ |
| `customer_name` | `customer_name` | 46 | ✅ |
| `phone` | `phone` | 47 | ✅ |
| `visitor_name` | `visitor_name` | 60 | ✅ |
| `party_size` | `"party_participants"` | 79 | ✅ |
| `male_count` | `male_count` | 74 | ✅ |
| `female_count` | `female_count` | 75 | ✅ |
| `gender` | `gender` | 69 | ✅ |
| `status` | `status` | 50 | ✅ |
| `section` | `section` | 55 | ✅ |
| `naver_room_type` | `"room_info"` | 66 | ✅ |
| `booking_options` | `booking_options` | 99 | ✅ |
| `special_requests` | `"custom_form_input"` | 100 | ✅ |
| `total_price` | `total_price` | 101 | ✅ |

`setattr(reservation, field, value)` 가 Python 속성명을 받으므로 위 매핑이 그대로 유효 (DB 컬럼명 차이는 SQLAlchemy 가 흡수).

**FIELD_PERMISSIONS 에서 의도적으로 누락한 컬럼** (모두 본 단계 #1 의 범위 밖):

| 컬럼 (Python) | 누락 사유 |
|---|---|
| `manually_extended_until` | 보호 플래그 — `check_out_pinned` 로 대체 예정 (#7, #15) |
| `gender_manual` | 보호 플래그 — 본 마이그레이션 범위 밖 (설계안 §6 미결) |
| `stay_group_id`, `stay_group_order`, `is_last_in_group`, `is_long_stay`, `stay_group_excluded` | 시스템 계산 필드 — Mutator 가 직접 만지지 않음 (`consecutive_stay.py` 가 담당) |
| `is_multi_booking`, `confirmed_at`, `cancelled_at`, `created_at`, `updated_at` | 시스템 자동 세팅, caller 가 직접 안 만짐 |
| `notes`, `visitor_phone`, `age_group`, `visit_count`, `booking_count`, `booking_source`, `biz_item_name`, `naver_biz_item_id`, `check_in_time`, `external_id`, `highlight_color`, `party_type`, `room_number`, `room_password` | 본 마이그레이션 §1-2 4개 버그와 무관 — 추후 caller 분석 후 확장. 본 단계에 미포함이지만, 단계 #11 까지 누락된 필드는 **`setattr` 가 그대로 처리** (Mutator 가 처리하지 않는 필드는 caller 가 기존 방식 유지) |

→ FIELD_PERMISSIONS 누락 필드를 caller 가 변경하려고 하면, 단계 #11 의 apply_changes 가 **테이블에 없으면 그대로 통과시키는** 정책으로 갈지 / **명시되지 않은 필드는 거부** 정책으로 갈지 결정 필요. **본 단계에서는 결정 보류 — 단계 #11 사전조사에서 결정**. #1 시점에서는 단지 테이블 선언만이므로 영향 없음.

---

## 4. 동작 동등성 근거

본 단계의 변경: **신규 파일 1개 추가, 어디서도 import/호출 안 함**.

### 4-1. 정적 분석 기반 동등성

| 검증 항목 | 검증 방법 | 기대 결과 |
|---|---|---|
| 다른 파일이 이 모듈을 import 하는지 | `grep -rn "from app.services.reservation_mutator\|from app.services import reservation_mutator\|import reservation_mutator" app/ tests/` | 0건 |
| `ReservationMutator` / `ChangeSource` / `FIELD_PERMISSIONS` 식별자 참조 | `grep -rn "ReservationMutator\|ChangeSource\|FIELD_PERMISSIONS" app/ tests/` (단, 본 신규 파일 제외) | 0건 |
| 기존 caller 의 동작 변화 | `naver_sync._update_reservation`, `reservations.update_reservation`, `extend_stay`, `reduce_extension`, `assign_room` 각 함수 진입/분기 흐름 — 본 PR 전후 diff 없음 | diff 0 |

### 4-2. 런타임 동등성

- 신규 파일이 module discovery 에 의해 lazy-import 될 가능성: SQLAlchemy ORM 의 `Base.registry` 가 자동 등록하는 경로 — 본 파일은 `Base` 상속 클래스를 정의하지 않으므로 자동 등록 대상 아님 ✅
- FastAPI 라우터 자동 발견: `app/main.py` 가 명시적으로 router 를 `include_router` 함 — 본 파일은 router 정의 0개 ✅
- 본 파일이 import 안 되면 `ChangeSource.MANUAL` 등의 enum 값이 메모리에 적재되지 않음 → 모든 SELECT/INSERT 쿼리 동일

### 4-3. 케이스별 비교

| 입력 / 시나리오 | 단계 #0 (현재) 결과 | 단계 #1 (본 단계) 결과 | 판정 |
|---|---|---|---|
| 네이버 동기화 — `existing.check_in_date` 덮어쓰기 | 덮어씀 (`naver_sync.py:672`) | 동일하게 덮어씀 — 본 파일 import 안 됨 | ✅ |
| 수동 PUT `update_reservation` | `setattr` 후 db.commit | 동일 | ✅ |
| `extend_stay` — `manually_extended_until` 세팅 | 정상 진행 | 동일 | ✅ |
| `reduce_extension` — `db.delete(ra)` | 정상 진행 | 동일 (room-assignment-pipeline 설계안 단계 #2 에서 별도 정리) | ✅ |
| 자동 객실 배정 | 정상 진행 | 동일 | ✅ |
| pytest backend/tests/* | 통과 | 통과 (신규 파일은 import 안 됨) | ✅ |
| python -c "from app.services.reservation_mutator import ChangeSource" | ImportError | OK — 새로 import 가능 | 신규 능력 추가 (영향 없음) |

---

## 5. 영향받지 않음을 확인할 코드 경로

다음 caller / 함수 / 진입점은 본 단계에서 **단 1 byte도 변경되지 않음**:

```
app/api/
  reservations.py              (update_reservation, create_reservation, delete_reservation)
  reservations_room.py         (assign_room handler)
  reservations_stay.py         (extend_stay, reduce_extension, _do_reduce_extension)
app/services/
  naver_sync.py                (_update_reservation, _create_reservation, sync_naver_to_db)
  room_assignment.py           (assign_room, unassign_room, clear_all_for_reservation)
  room_auto_assign.py          (auto_assign_rooms, _assign_all_rooms)
  consecutive_stay.py
  chip_reconciler.py
  reconcile.py
app/scheduler/
  jobs.py                       (daily_room_assign_job, sync_naver_reservations_job)
  template_scheduler.py
  schedule_manager.py
app/db/
  models.py                     (Reservation 모델 컬럼 추가는 단계 #2~#3)
  tenant_context.py
```

frontend 측: 변경 없음.

---

## 6. 검증 체크리스트

PR 작성 시 모두 ✅ 되어야 함.

- [ ] **파일 syntax**: `python -m py_compile backend/app/services/reservation_mutator.py` 에러 0
- [ ] **import 가능**: `python -c "from app.services.reservation_mutator import ReservationMutator, ChangeSource, FIELD_PERMISSIONS"` 성공
- [ ] **caller 변화 없음**: `git diff main -- backend/app/api/ backend/app/services/naver_sync.py backend/app/services/room_assignment.py backend/app/scheduler/` 결과 0 라인
- [ ] **외부 참조 0건** (#1 단독 머지 시점):
  - `grep -rn "ReservationMutator" backend/ --exclude-dir=__pycache__ | grep -v reservation_mutator.py` → 0건
  - `grep -rn "ChangeSource" backend/ --exclude-dir=__pycache__ | grep -v reservation_mutator.py` → 0건
- [ ] **NotImplementedError 가시화**: 테스트 환경에서 임의로 `ReservationMutator.apply_changes(...)` 호출 시 즉시 raise (잠재적 silent skip 차단)
- [ ] **기존 pytest 회귀**: `cd backend && pytest` 결과가 #0 시점과 동일 (pass/fail 개수 일치)
- [ ] **ruff / mypy**: 본 신규 파일이 프로젝트 lint 통과
- [ ] **FIELD_PERMISSIONS 키 ↔ Reservation 속성명 일치**: §3 매핑 표대로 — 자동 검증 스크립트 1줄로 충분:
  ```python
  # tests/unit/test_mutator_skeleton.py 신규 (선택)
  from app.db.models import Reservation
  from app.services.reservation_mutator import FIELD_PERMISSIONS
  def test_field_permissions_keys_are_valid_attrs():
      for field in FIELD_PERMISSIONS:
          assert hasattr(Reservation, field), f"Reservation has no attribute {field}"
  ```

---

## 7. 본 단계 이후의 후속 의존성

본 단계가 머지된 후 진행 가능한 후속 단계:

- **#2** (DB 마이그레이션): 본 단계와 독립 — 컬럼 추가만, Mutator 코드 호출 안 함
- **#11** (apply_changes 실제 구현): 본 단계의 signature 를 따름
- **#12~#14** (caller 전환): 본 단계의 클래스/enum/테이블을 참조

본 단계 단독으로는 의도된 동작 변화 없음. 4개 버그 해결은 단계 #6~#8 시점에 발생.

---

## 8. 결정 보류 항목 (단계 #11 사전조사로 위임)

- [ ] `FIELD_PERMISSIONS` 에 없는 필드를 caller 가 변경 요청하면 → 통과 vs 거부 정책
- [ ] `apply_changes` 가 ActivityLog 를 직접 기록할지 vs caller 가 기록할지
- [ ] pin 자동 세팅 (단계 #6~#8 의 동작) 을 #11 시점에 Mutator 내부로 흡수할지 vs caller 코드에 남길지
- [ ] `gender_manual`, `is_split_managed`, `stay_group_excluded` 등 기존 보호 플래그를 Mutator 가 통합할지 (설계안 §6)

본 단계 머지 후에도 위 결정은 코드에 영향 없음 (스켈레톤만 존재).

---

## 9. 머지 후 다음 액션

본 단계 PR 머지 → `docs/plans/mutator-step-02-pinned-columns.md` 작성 (DB 컬럼 추가 사전조사).
