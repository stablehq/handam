# 단계 #2~#3 사전조사 — `check_in_pinned` / `check_out_pinned` 컬럼 추가

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §A
> 분류: ⚪ 동작 변화 없음 (인프라)
> 변경 규모: 신규 alembic 파일 1개 (~40 lines) + `db/models.py` 4 라인 추가
> 묶음 사유: 마이그레이션과 모델 컬럼 선언을 분리하면 중간 상태에서 ORM 이 컬럼을 인식하지 못함

---

## 1. 목적

`Reservation` 테이블에 `check_in_pinned` / `check_out_pinned` Boolean 컬럼을 추가하고, ORM 모델에도 동일하게 선언. 두 컬럼은 단계 #2~#3 시점에서 **어디서도 set/read 되지 않으며**, 후속 단계 (#4 가드, #6~#8 자동 세팅) 가 사용한다.

### 본 단계가 다루지 *않는* 것
| 항목 | 다루는 단계 |
|---|---|
| naver_sync 가드 (`if not existing.check_in_pinned`) | #4 |
| reservations.py PUT 의 pin 자동 세팅 | #6, #7 |
| extend_stay 의 pin 자동 세팅 | #8 |
| 기존 `manually_extended_until` 데이터를 `check_out_pinned` 로 backfill | #15 |

---

## 2. 변경 대상 코드

### 2-1. 신규 파일: `backend/alembic/versions/020_add_pinned_fields.py`

**Before**: 없음.
**After**:

```python
"""Add check_in_pinned, check_out_pinned to reservations

Revision ID: 020
Revises: 019
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reservations',
        sa.Column('check_in_pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'reservations',
        sa.Column('check_out_pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('reservations', 'check_out_pinned')
    op.drop_column('reservations', 'check_in_pinned')
```

**스타일 정당화**:
- 파일명 `020_add_pinned_fields.py` — 기존 패턴 (`018_add_manually_extended_until.py`, `019_add_grade_to_rooms_and_biz_items.py`) 과 일치
- `revision = '020'`, `down_revision = '019'` — `019` 가 현재 head (revision chain grep 으로 확정)
- `server_default=sa.false()` — 기존 레코드 전부 `False` 로 백필됨. NULL 대신 명시적 False (SQLite/PostgreSQL 양쪽 안전)
- `nullable=False` — pin 은 항상 명확한 True/False (NULL 상태 없음)
- `downgrade` 도 작성 — 단계 롤백 가능성 확보

**참고: 018 패턴 비교**
```python
# 018: manually_extended_until = String(20), nullable=True
op.add_column('reservations', sa.Column('manually_extended_until', sa.String(20), nullable=True))
```
018 은 nullable=True (값 없음 = 보호 없음). 본 단계는 Boolean nullable=False (default False = 보호 없음) — 의미 동일하지만 타입이 더 명확.

### 2-2. `backend/app/db/models.py` Reservation 클래스에 컬럼 선언 추가

**Before** (현재 L91~L93 부근, `manually_extended_until` 라인 직전/직후):

```python
    stay_group_excluded = Column(Boolean, nullable=False, server_default='false', default=False)  # True: 사용자가 수동 unlink → 자동 재묶기 방지
    highlight_color = Column(String(20), nullable=True)              # UI highlight color for reservation card

    manually_extended_until = Column(String(20), nullable=True)  # protects against naver_sync overwrite when user manually extends
```

**After**: `manually_extended_until` 다음 줄에 두 컬럼 선언 추가:

```python
    stay_group_excluded = Column(Boolean, nullable=False, server_default='false', default=False)  # True: 사용자가 수동 unlink → 자동 재묶기 방지
    highlight_color = Column(String(20), nullable=True)              # UI highlight color for reservation card

    manually_extended_until = Column(String(20), nullable=True)  # protects against naver_sync overwrite when user manually extends

    # Mutator pin flags — set by manual paths, checked by naver_sync (단계 #4~#8 부터 활성)
    check_in_pinned = Column(Boolean, nullable=False, server_default='false', default=False)
    check_out_pinned = Column(Boolean, nullable=False, server_default='false', default=False)
```

**스타일 정당화**:
- `stay_group_excluded` 의 패턴 그대로 사용 (`Boolean, nullable=False, server_default='false', default=False`)
- `server_default='false'` 문자열 — SQLAlchemy 가 SQLite/PostgreSQL 양쪽 호환 처리 (기존 `stay_group_excluded` 가 동일 패턴 사용 중)
- `default=False` — Python 측에서 새 객체 생성 시 명시적 False (server_default 와 이중 안전망)
- 주석으로 단계 의도 명시 — 후속 단계 작업자가 즉시 이해 가능
- `manually_extended_until` 옆 배치 — "보호 플래그" 의미 그룹화 (단계 #15 deprecation 시 함께 보기 쉬움)

---

## 3. 동작 동등성 근거

### 3-1. 신규 컬럼이 SELECT/INSERT 결과에 미치는 영향

| 작업 | 변경 전 | 변경 후 | 영향 |
|---|---|---|---|
| 신규 예약 INSERT (caller 가 pin 안 만짐) | `check_in_pinned` 미존재 | `check_in_pinned = False` (default) | 컬럼만 추가, 다른 필드 동일 |
| 기존 예약 SELECT | `check_in_pinned` 미존재 | `check_in_pinned = False` (server_default 백필) | reservation 객체에 속성 1개 추가, 기존 속성 동일 |
| ORM `db.refresh(reservation)` | 동일 | `check_in_pinned` 도 함께 로드 | 추가 컬럼이지만 caller 가 안 읽으면 무관 |
| Pydantic 직렬화 (`_to_response`) | `check_in_pinned` 미포함 | `_to_response` 가 명시 필드만 직렬화 → **미포함** (변경 없음) | response 형태 동일 |

**`_to_response` 확인 필요 케이스**:
- `app/api/reservations.py` 의 `_to_response` 함수가 `Reservation.__dict__` / `model_dump()` 같이 모든 속성을 자동 직렬화하면 frontend 응답에 새 필드가 노출됨
- 명시적 Pydantic schema 기반이라면 영향 없음
- **검증 항목** (§6): `_to_response` 호출 결과에 `check_in_pinned` 가 포함되는지 확인

### 3-2. SQLAlchemy 이벤트 훅 영향

`app/db/tenant_context.py` 의 `before_compile` / `before_flush` 훅:
- `before_compile`: `WHERE tenant_id = X` 자동 추가 — Boolean 컬럼 추가는 WHERE 조건과 무관
- `before_flush`: `INSERT` 시 `tenant_id` 주입 — 신규 컬럼은 별도 처리 없이 server_default 로 채워짐

→ 멀티테넌트 격리 동작 영향 없음.

### 3-3. SQLite vs PostgreSQL 호환성

- SQLite: `sa.Boolean()` → INTEGER (0/1) 로 저장, `server_default=sa.false()` → `DEFAULT 0`
- PostgreSQL: 네이티브 BOOLEAN, `server_default=sa.false()` → `DEFAULT FALSE`
- 양쪽 모두 SQLAlchemy 가 자동 변환

### 3-4. init_db() / 자동 마이그레이션과의 관계

`app/db/database.py` 의 `init_db()` 가 자동 마이그레이션 한다는 CLAUDE.md 기록 있음. 검증 필요:
- alembic 정식 도구를 쓰는지 vs metadata.create_all() 만 쓰는지
- 후자라면 신규 컬럼은 `create_all` 이 새 테이블만 만들고 기존 테이블 ALTER 안 함 → 빈 DB 만 영향
- **검증 항목** (§6): `init_db` 의 ALTER 처리 방식 확인 + 수동 alembic upgrade 가 필요한지 확인

---

## 4. 케이스별 비교

| 입력 / 시나리오 | 단계 #1 (현재) 결과 | 단계 #2~#3 (본 단계) 결과 | 판정 |
|---|---|---|---|
| `pytest backend/tests/*` | 통과 | 통과 (새 컬럼은 default False, 기존 로직 무관) | ✅ |
| 네이버 동기화 — `existing.check_in_date` 덮어쓰기 | 덮어씀 | 동일 — pin 가드는 #4 부터 | ✅ |
| 수동 PUT `update_reservation` | setattr → commit | 동일 — 새 컬럼은 안 만짐 | ✅ |
| `extend_stay` | `manually_extended_until` 세팅 | 동일 | ✅ |
| 기존 예약 SELECT 후 `print(reservation.check_in_pinned)` | AttributeError | `False` | 신규 능력 (silent) |
| 기존 예약 SELECT 후 `_to_response` JSON | `{...}` (pinned 없음) | `{...}` (pinned 없음, Pydantic schema 기반이면) | 검증 항목 |
| `db.commit()` 후 DB 행 | `check_in_pinned` 컬럼 없음 | `check_in_pinned = 0` (SQLite) / `false` (PG) | 컬럼 추가만 |

---

## 5. 영향받지 않음을 확인할 코드 경로

다음 코드는 본 단계에서 단 1 byte도 변경되지 않음:

```
app/api/                                (모든 라우터)
app/services/reservation_mutator.py     (단계 #1 의 스켈레톤, 본 단계 코드 변경 없음)
app/services/naver_sync.py              (단계 #4~#5, #9~#10 에서 변경)
app/services/room_assignment.py
app/services/chip_reconciler.py
app/services/reconcile.py
app/scheduler/                          (모든 스케줄러)
app/db/tenant_context.py
app/db/database.py                      (init_db 호출 흐름은 동일)
```

frontend 측: 변경 없음.

---

## 6. 검증 체크리스트

- [ ] **alembic 파일 syntax**: `python -m py_compile alembic/versions/020_add_pinned_fields.py` 에러 0
- [ ] **revision chain 정확**: `alembic history` 출력에 `020 (head) → 019 → ...` 표시
- [ ] **upgrade 실행**: `alembic upgrade head` 실행 후 SQLite/Postgres 양쪽에서 컬럼 추가 확인
  - SQLite: `sqlite3 sms.db ".schema reservations" | grep pinned` → 두 컬럼 모두 출력
- [ ] **downgrade 실행**: `alembic downgrade -1` 후 컬럼 삭제 확인 후 다시 `upgrade head`
- [ ] **모델 정의 매핑**: `python -c "from app.db.models import Reservation; print(Reservation.check_in_pinned.type, Reservation.check_out_pinned.type)"` → `Boolean Boolean`
- [ ] **default 값 동작**: 신규 예약 INSERT 후 `reservation.check_in_pinned is False` 확인
- [ ] **기존 예약 백필**: 기존 sample 데이터의 `check_in_pinned` 가 False 로 채워짐 확인
- [ ] **`_to_response` 영향 검사**:
  - `grep -n "to_response\|_to_response\|ReservationResponse" app/api/reservations.py` 로 직렬화 위치 찾기
  - 명시 Pydantic schema 기반이면 OK (자동 비포함)
  - `__dict__` / `model_dump()` 자동 직렬화면 frontend 응답에 새 필드 노출 — 본 단계에서는 무해하지만 명시
- [ ] **기존 pytest 회귀**: `cd backend && pytest` 결과 #1 시점과 동일 (pass/fail 개수 일치)
- [ ] **외부 참조 0건**: `check_in_pinned`, `check_out_pinned` 식별자 grep — `models.py` + `020_add_pinned_fields.py` 외 0건
- [ ] **`init_db()` 검증**: `app/db/database.py` 의 init_db 가 alembic 호출하는지 vs `create_all()` 만 하는지 확인. 후자면 alembic upgrade 수동 실행 필요 명시
- [ ] **FIELD_PERMISSIONS 와의 관계 명시**: pin 컬럼은 FIELD_PERMISSIONS 의 키가 아님 (필드 권한 테이블 vs 보호 플래그 — 다른 개념). 검증 스크립트에 영향 없음

---

## 7. 본 단계 이후의 후속 의존성

본 단계 머지 후 진행 가능:
- **#4** (naver_sync `check_in_pinned` 가드 추가) — 본 단계의 컬럼을 읽기만 함 (set 안 함)
- **#5** (naver_sync `check_out_pinned` 가드 추가) — 동일
- **#6~#8** (수동 경로의 pin 자동 세팅) — 본 단계의 컬럼을 set
- **#11** (Mutator apply 구현) — pin 세팅 로직을 흡수할지 #11 사전조사에서 결정

본 단계 단독으로는 의도된 동작 변화 없음 — 컬럼만 추가, set/read 0건.

---

## 8. 미결 검토 항목

- [ ] `_to_response` 가 새 컬럼을 frontend 응답에 노출하는지 확인 후 결정:
  - 노출되면 무해 (Pydantic schema 가 받지 못하면 무시) — 단계 #4~#8 작업하면서 어차피 어디선가 set 되니 결국 노출됨
  - 노출 안 되면 frontend 가 pin 상태를 직접 표시하고 싶을 때 별도 작업 필요
- [ ] `init_db()` 가 자동 마이그레이션 안 한다면 (가능성 높음) 배포 시 수동 `alembic upgrade head` 절차 명시 — 운영 배포 가이드 추가 필요 가능

---

## 9. 머지 후 다음 액션

본 단계 PR 머지 → `docs/plans/mutator-step-04-naver-checkin-guard.md` 작성.
