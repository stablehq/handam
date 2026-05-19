# 단계 #1 사전조사 — TENANT_MODELS 등록 리스트에 누락 모델 2개 추가

> 부모 계획: [tenant-model-registry-fix-plan.md](./tenant-model-registry-fix-plan.md) §"Step 01"
> 분류: 🔵 의도된 동작 변화 (보안 회귀 해결)
> 변경 규모: 1개 파일, 추가 2 lines

---

## 1. 목적

`backend/app/db/models.py:609-614` 의 자동 필터 등록 리스트에 `OnsiteFemaleInvite`, `DailyReviewCount` 두 모델을 추가하여 `before_compile` 이벤트가 두 모델의 SELECT 쿼리에 `WHERE tenant_id = X` 를 자동으로 주입하도록 한다.

### 본 단계가 다루는 것 (= 의도된 변화)

- `db.query(OnsiteFemaleInvite)` 와 `db.query(DailyReviewCount)` 에 자동 tenant 필터 적용
- 결과: 한담 user 가 SalesReport 조회 시 stable 의 OnsiteFemaleInvite / DailyReviewCount 가 응답에 섞이지 않음
- 부수 효과: `onsite_female_invite.py` 의 GET/PUT/DELETE / `daily_review.py` 의 GET/PUT 도 자동으로 tenant 격리 (현재는 ID 만 알면 cross-tenant 조작 가능)

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| 회귀 방지 자동 검증 test | Step 02 |
| `tenant_context.py` 의 `before_compile` 이벤트 로직 자체 | 변경 불필요 (정상 동작 확인됨) |
| 데이터 마이그레이션 (기존 행의 tenant_id 정리) | 불필요 (DB 검증 결과 NULL 0행, cross-tenant 0행) |
| cross-tenant 조작 운영 로그 추적 | 별도 사후 점검 작업 |
| `_set_tenant_on_new_objects` (INSERT) 로직 | 변경 불필요 (이미 두 모델에 적용 중) |

---

## 2. 변경 대상 코드

### 2-1. `backend/app/db/models.py:609-615`

**Before** (현재 코드, 운영 main 상태):

```python
# ---------------------------------------------------------------------------
# Register tenant models for automatic SELECT filtering
# ---------------------------------------------------------------------------
from app.db.tenant_context import register_tenant_model as _register  # noqa: E402

for _model in [
    Reservation, MessageTemplate, ReservationSmsAssignment,
    RoomBizItemLink, Building, RoomGroup, Room, RoomAssignment,
    NaverBizItem, TemplateSchedule, ActivityLog, PartyCheckin, ReservationDailyInfo,
    ParticipantSnapshot, OnsiteSale, DailyHost, OnsiteAuction, PartyHost,
]:
    _register(_model)
```

**After** (변경 후):

```python
# ---------------------------------------------------------------------------
# Register tenant models for automatic SELECT filtering
# ---------------------------------------------------------------------------
from app.db.tenant_context import register_tenant_model as _register  # noqa: E402

for _model in [
    Reservation, MessageTemplate, ReservationSmsAssignment,
    RoomBizItemLink, Building, RoomGroup, Room, RoomAssignment,
    NaverBizItem, TemplateSchedule, ActivityLog, PartyCheckin, ReservationDailyInfo,
    ParticipantSnapshot, OnsiteSale, DailyHost, OnsiteAuction, PartyHost,
    DailyReviewCount, OnsiteFemaleInvite,
]:
    _register(_model)
```

**변경 의도**: 두 모델을 `TENANT_MODELS` 집합에 추가하여 `before_compile` 자동 필터가 SELECT 시 `WHERE tenant_id` 절을 주입하도록 함.

**추가 위치 결정 근거**:
- 알파벳 순이 아니라 **두 모델의 정의 순서** (`DailyReviewCount` line 572 → `OnsiteFemaleInvite` line 587) 와 맞춤
- 기존 리스트도 일관된 정의 순서 (Reservation 38 → ... → PartyHost 557) 를 따르므로 컨벤션 유지

---

## 3. 모델 실측 (TenantMixin 상속 + 등록 일치 검증)

`backend/app/db/models.py` 전수 grep 결과:

### 3-1. TenantMixin 상속 클래스 (20개)

| # | 모델 | 파일 라인 | 등록 여부 (현재) | 등록 여부 (After) |
|---|------|----------|----------------|-------------------|
| 1 | Reservation | 38 | ✅ | ✅ |
| 2 | MessageTemplate | 124 | ✅ | ✅ |
| 3 | ReservationSmsAssignment | 164 | ✅ | ✅ |
| 4 | RoomBizItemLink | 190 | ✅ | ✅ |
| 5 | Building | 216 | ✅ | ✅ |
| 6 | RoomGroup | 236 | ✅ | ✅ |
| 7 | Room | 254 | ✅ | ✅ |
| 8 | RoomAssignment | 283 | ✅ | ✅ |
| 9 | NaverBizItem | 307 | ✅ | ✅ |
| 10 | TemplateSchedule | 331 | ✅ | ✅ |
| 11 | ActivityLog | 389 | ✅ | ✅ |
| 12 | PartyCheckin | 406 | ✅ | ✅ |
| 13 | ReservationDailyInfo | 422 | ✅ | ✅ |
| 14 | ParticipantSnapshot | 458 | ✅ | ✅ |
| 15 | OnsiteSale | 513 | ✅ | ✅ |
| 16 | DailyHost | 526 | ✅ | ✅ |
| 17 | OnsiteAuction | 540 | ✅ | ✅ |
| 18 | PartyHost | 558 | ✅ | ✅ |
| 19 | **DailyReviewCount** | **572** | **❌** | **✅ (본 PR)** |
| 20 | **OnsiteFemaleInvite** | **587** | **❌** | **✅ (본 PR)** |

**확인**: After 시점에 누락 모델 0개.

### 3-2. 두 모델의 격리 의도 검증

두 모델 모두 `tenant_id` 를 포함한 UniqueConstraint 가 정의되어 있음 → **원래부터 tenant 격리가 의도된 모델**:

```python
# models.py:572-583
class DailyReviewCount(TenantMixin, Base):
    __tablename__ = "daily_review_counts"
    ...
    __table_args__ = (
        UniqueConstraint("tenant_id", "date", name="uq_daily_review_tenant_date"),
    )

# models.py:587-599
class OnsiteFemaleInvite(TenantMixin, Base):
    __tablename__ = "onsite_female_invites"
    ...
    __table_args__ = (
        UniqueConstraint("tenant_id", "date", "host_username", name="uq_onsite_female_invite_tenant_date_host"),
    )
```

→ 등록 누락은 **명백한 실수** (모델 정의 후 등록 리스트 갱신 누락).

---

## 4. 영향 받는 코드 경로 — 라인 단위

### 4-1. `OnsiteFemaleInvite` SELECT 호출처 (전수)

| 파일:라인 | 호출 | Before 동작 | After 동작 |
|-----------|------|------------|------------|
| `backend/app/api/sales_report.py:102-104` | `db.query(OnsiteFemaleInvite).filter(date 범위).all()` | 모든 tenant 의 invite 반환 (🔴 leak) | tenant 의 invite 만 반환 (✅) |
| `backend/app/api/onsite_female_invite.py:42-44` | `db.query(OnsiteFemaleInvite).filter(date == ...).order_by(host_username)` (list) | 모든 tenant 의 같은 date 행 반환 (🔴) | tenant 만 (✅) |
| `backend/app/api/onsite_female_invite.py:62-65` | `db.query(...).filter(date == req.date, host_username == req.host_username)` (upsert 충돌 체크) | cross-tenant 충돌도 감지 → 잘못된 race 차단 가능 | tenant 내부만 체크 (✅, 의도 맞음) |
| `backend/app/api/onsite_female_invite.py:95` | `db.query(...).filter(id == invite_id).first()` (update fetch) | **임의 ID 로 cross-tenant 조작 가능 (🔴 보안 결함)** | tenant 내부 행만 (✅) |
| `backend/app/api/onsite_female_invite.py:106-110` | `db.query(...).filter(date, host_username, id != invite_id)` (rename 충돌 체크) | cross-tenant 충돌 감지 → 거짓 양성 | tenant 내부만 (✅) |
| `backend/app/api/onsite_female_invite.py:142` | `db.query(...).filter(id == invite_id).first()` (delete fetch) | **임의 ID 로 cross-tenant 삭제 가능 (🔴 보안 결함)** | tenant 내부만 (✅) |

### 4-2. `DailyReviewCount` SELECT 호출처 (전수)

| 파일:라인 | 호출 | Before 동작 | After 동작 |
|-----------|------|------------|------------|
| `backend/app/api/sales_report.py:96-98` | `db.query(DailyReviewCount).filter(date 범위).all()` | 모든 tenant 의 review 반환 (🔴 leak) | tenant 만 (✅) |
| `backend/app/api/daily_review.py:33` | `db.query(DailyReviewCount).filter(date == date).first()` (get) | 같은 date 가 여러 tenant 에 있으면 **임의의 한 행 반환** (DB 순서 의존, 비결정적) | tenant 만 (✅) |
| `backend/app/api/daily_review.py:47-48` | `db.query(DailyReviewCount).filter(date == req.date)` (upsert) | cross-tenant 충돌 감지 가능 | tenant 내부만 (✅) |

### 4-3. INSERT 경로 — 변경 없음

| 파일:라인 | 호출 | Before / After 동일 |
|-----------|------|--------------------|
| `onsite_female_invite.py:76` | `OnsiteFemaleInvite(date=..., host_username=..., count=...)` | `_set_tenant_on_new_objects` (tenant_context.py:51) 가 `hasattr(obj, 'tenant_id')` 만 보고 자동 주입. 등록 여부 무관. **본 PR 적용 후에도 동일.** |
| `daily_review.py:58` | `DailyReviewCount(date=..., count=...)` | 동일 |

**DB 검증** (운영 Supabase, 2026-05-19):
- `daily_hosts`, `onsite_female_invites`, `party_hosts`, `onsite_sales`, `onsite_auctions` 모두 `tenant_id IS NULL` 행 = **0건**
- → INSERT 시 tenant_id 정상 주입 확인. 데이터 마이그레이션 불필요.

---

## 5. 동작 동등성 / 의도된 변화 — 시나리오 매트릭스

⚪ = 변화 없음 / 🔵 = 의도된 변화 (보안 회귀 해결) / ⚠️ = 잠재 사이드이펙트.

| 시나리오 | Before | After | 판정 |
|----------|--------|-------|------|
| 한담 user, SalesReport 5월 조회 | stable 진행자 4명 + 여자초대수 노출 | 한담 데이터만 (현재 0건 → "(미지정)" 또는 빈 hosts) | 🔵 |
| stable user, SalesReport 5월 조회 | stable 데이터 정상 (자동 필터 없어도 결과 일치 — 같은 tenant 내부) | stable 데이터 정상 (필터 적용 후에도 동일) | ⚪ |
| 한담 user, OnsiteFemaleInvite list (`GET /api/onsite-female-invites?date=...`) | 같은 date 의 모든 tenant 행 반환 | 한담 행만 | 🔵 |
| stable user, OnsiteFemaleInvite list | 모든 tenant 행 반환 (사실상 stable 만 있으면 결과 같음) | stable 만 | 🔵 (실질 차이 적음) |
| 한담 user, OnsiteFemaleInvite UPDATE — `PUT /{invite_id}` 로 **stable 의 invite ID** 전송 | row fetch 성공 → host_username/count 변경 가능 (🔴 cross-tenant 변조) | row fetch 결과 None → 404 응답 | 🔵 (보안 결함 해결) |
| 한담 user, OnsiteFemaleInvite DELETE — stable invite ID 전송 | row fetch 성공 → 삭제 (🔴 cross-tenant 삭제) | 404 | 🔵 (보안 결함 해결) |
| 한담 user, OnsiteFemaleInvite POST (생성) — 본인 tenant 에 새 invite | `_set_tenant_on_new_objects` 가 tenant_id=1 자동 주입 + UniqueConstraint 통과 | 동일 | ⚪ |
| 한담 user, DailyReviewCount GET (`GET /api/daily-review?date=2026-05-15`) | 같은 date 에 stable 데이터도 있으면 임의 행 반환 (비결정적, 🔴) | 한담 행만 | 🔵 |
| 한담 user, DailyReviewCount PUT (upsert) | upsert 충돌 체크 시 cross-tenant 행도 감지 → 거짓 update 가능 | 한담 내부만 | 🔵 |
| ContextVar 없는 백그라운드 작업 (스케줄러 등) 이 두 모델 query | `tid is None` → fail-closed RuntimeError (`tenant_context.py:90-99`) | 동일 | ⚪ (단, 본 모델은 현재 스케줄러에서 쿼리되지 않음 — 4-1/4-2 grep 결과 사용처는 API 라우터 6개뿐) |
| `bypass_tenant_filter` 사용 시 | bypass=True → 필터 skip, cross-tenant OK | 동일 | ⚪ |
| 두 모델 외 다른 18개 등록 모델의 SELECT | 자동 필터 정상 | 자동 필터 정상 (변화 없음) | ⚪ |

### 5-1. 잠재 사이드이펙트 검토

**⚠️ 후보 1**: `onsite_female_invite.py:64-65` 의 upsert 충돌 체크가 cross-tenant 행을 감지하던 동작이 사라짐.

```python
existing = db.query(OnsiteFemaleInvite).filter(
    OnsiteFemaleInvite.date == req.date,
    OnsiteFemaleInvite.host_username == req.host_username,
).first()
```

- Before: 같은 date+host 가 다른 tenant 에 있으면 `existing` 으로 잡힘 → `existing.tenant_id != current_tenant` 인데 update 진행 (cross-tenant 변조)
- After: 본인 tenant 내부만 검색 → 본인 tenant 에 없으면 새 row 생성 (정상)
- **판정**: After 가 정상. 단 UniqueConstraint `("tenant_id", "date", "host_username")` 가 있으므로 동일 tenant 내 중복은 DB 레벨에서도 차단. **데이터 무결성 OK**.

**⚠️ 후보 2**: `daily_review.py:33` 의 `.first()` 가 같은 date 의 임의 tenant 행을 반환하던 동작이 사라짐.

- Before: 한담 user 가 `GET /api/daily-review?date=2026-05-15` 호출 시 stable 의 review 가 반환될 수 있었음 (DB row order 의존)
- After: 한담 row 만. 없으면 None → 404
- **판정**: After 가 정상. Before 가 비결정적 버그였음.

**⚠️ 후보 3**: ContextVar 없는 진입점에서 두 모델 query → fail-closed RuntimeError 발생

- 영향 받는 경로 grep 결과: 두 모델의 모든 사용처는 `get_tenant_scoped_db` (`sales_report.py:70`, `onsite_female_invite.py` 4 endpoint, `daily_review.py` 2 endpoint) 만 사용 → ContextVar 항상 세팅됨
- 스케줄러 / 마이그레이션 / CLI 등에서 쿼리하는 곳 없음 (grep `OnsiteFemaleInvite|DailyReviewCount` in `backend/app/scheduler/`, `backend/app/db/seed.py` 결과 0건)
- **판정**: 영향 없음

**⚠️ 후보 4**: 응답 데이터 변화로 인한 프론트 측 에러

- SalesReport: `data.hosts` 가 빈 배열이 되어도 `data.hosts.length === 0` 분기 처리 있음 (`SalesReport.tsx:258`) → 정상 표시
- 다른 API: list/get/update/delete 모두 표준 응답 — 변화 없음 (단지 cross-tenant 행을 못 보게 됨)
- **판정**: 프론트 코드 변경 불필요

---

## 6. 영향받지 않음을 확인할 코드 경로

다음 영역은 본 단계에서 **1 byte 도 변경되지 않으며 동작 변화 없음**:

```
backend/app/db/tenant_context.py     # before_compile / before_flush 로직 동일
backend/app/db/database.py           # 세션 생성 동일
backend/app/api/deps.py              # get_tenant_scoped_db 동일
backend/app/api/                     # 외 모든 라우터 (두 모델 쿼리 없음)
backend/app/services/                # 두 모델 쿼리 없음
backend/app/scheduler/               # 두 모델 쿼리 없음
frontend/                            # 응답 schema 변화 없음 (단지 cross-tenant 행 제외)
alembic/versions/                    # 마이그레이션 불필요
```

검증: `grep -rnE "OnsiteFemaleInvite|DailyReviewCount" backend/app/ frontend/src/ --exclude-dir=__pycache__` 결과 = 본 §4 의 호출처 목록과 정확히 일치 (그 외 0건).

---

## 7. 검증 체크리스트

PR 작성 시 모두 ✅:

- [ ] **syntax**: `python -m py_compile backend/app/db/models.py` 에러 0
- [ ] **import 가능**: `python -c "from app.db.models import OnsiteFemaleInvite, DailyReviewCount; from app.db.tenant_context import TENANT_MODELS; assert OnsiteFemaleInvite in TENANT_MODELS and DailyReviewCount in TENANT_MODELS"` 성공
- [ ] **diff 정확성**: `git diff main -- backend/app/db/models.py` 결과 = 2 lines 추가만 (다른 변경 0)
- [ ] **외부 영향 0**: `git diff main -- backend/app/api/ backend/app/services/ frontend/` 결과 = 0
- [ ] **기존 pytest 회귀**: `cd backend && pytest` 결과 = 변경 전과 동일 (실패 0, 추가 0)
- [ ] **수동 회귀 검증** (배포 후):
  - [ ] 한담 로그인 → SalesReport 5월 조회 → stable 진행자 4명 사라짐
  - [ ] 한담 로그인 → OnsiteFemaleInvite list (어떤 date) → stable 행 안 보임
  - [ ] stable 로그인 → SalesReport / OnsiteFemaleInvite → stable 데이터 정상 표시 (회귀 없음)
- [ ] **(선택) cross-tenant 조작 시도 차단 검증**: 한담 토큰으로 stable invite ID 에 PUT/DELETE → 404 응답

---

## 8. 후속 의존성

- **Step 02** (`tenant-model-registry-step-02-regression-guard.md`): TenantMixin 상속 모델이 등록 리스트에 자동 포함됨을 검증하는 test. 본 PR 머지 후 작성.
- **사후 점검** (별도 작업, 본 PR 범위 밖):
  - 운영 로그 / ActivityLog 에서 한담 user 가 stable invite 를 수정/삭제했던 흔적 있는지 조회
  - 있다면 데이터 복구 또는 사용자 공지 검토

---

## 9. 결정 보류 항목 (Step 02 사전조사로 위임)

- [ ] 회귀 방지 검증 방식 — runtime `__subclasses__()` 검사 vs 정적 grep vs `register_tenant_model` 데코레이터 강제
- [ ] test 위치 — `backend/tests/unit/` vs `backend/tests/security/` (신규 디렉터리)
- [ ] CI 통합 — `pytest` 실행에만 의존 vs 별도 lint 단계

---

## 10. 머지 후 다음 액션

1. 본 PR 머지 → 운영 자동 배포 (GitHub Actions: deploy.yml) 대기 (≈10분)
2. 헬스체크 통과 확인 (자동 롤백 미발생)
3. §7 수동 회귀 검증 3건 수행 (사용자 요청)
4. Step 02 사전조사 문서 작성 시작
