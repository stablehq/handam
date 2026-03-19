# 멀티 테넌트 지원 구현 계획 (Revision 2)

> **목표**: 현재 단일 펜션(HANDAM)만 운영하는 SMS 예약 시스템에 STABLE을 독립 엔티티로 추가하여,
> 같은 UI/시스템 내에서 두 펜션의 데이터를 완전히 격리하면서 운영할 수 있게 한다.
>
> **Revision 2 변경점**: `before_compile` 방식을 하이브리드 필터링으로 교체, 역할 구조 재설계 (STAFF 메뉴 제한),
> Factory lru_cache 제거 및 호출처 명시, 스케줄러 job별 테넌트 처리, SSE 테넌트 격리, 마이그레이션 안전장치 추가

---

## 1. 현재 vs 변경 비교

### 1.1 Database 계층

| 항목 | 현재 (Before) | 변경 후 (After) |
|------|--------------|----------------|
| 테넌트 개념 | 없음 - 모든 데이터가 하나의 풀 | `tenants` 테이블 + 모든 데이터 테이블에 `tenant_id` 컬럼 |
| 데이터 격리 | 불필요 (단일 펜션) | 하이브리드: relationship 자동필터 + 복잡 쿼리 명시적 필터 |
| 네이버 연동 설정 | `config.py`에 하드코딩 + 글로벌 `_runtime_naver_cookie` | `tenants` 테이블에 펜션별 `naver_business_id`, `naver_cookie` 저장 |
| 유저-펜션 관계 | 없음 (유저는 글로벌) | `user_tenant_roles` 조인 테이블 (유저별 펜션 접근 권한) |

### 1.2 Backend 계층

| 항목 | 현재 (Before) | 변경 후 (After) |
|------|--------------|----------------|
| DB 세션 필터링 | 없음 | 하이브리드: `with_loader_criteria()` + `tenant_query()` 헬퍼 + `before_flush` INSERT 자동주입 |
| 테넌트 컨텍스트 | 없음 | `X-Tenant-Id` 헤더 → FastAPI dependency → ContextVar |
| 역할 검증 | `require_role()` — 글로벌 role만 확인 | `require_role()` — 글로벌 role + `user_tenant_roles` 테넌트별 매핑 동시 확인 |
| STAFF 접근 | 전체 메뉴 접근 | party_checkin 엔드포인트만 접근 가능, 테넌트 전환 불가 |
| Factory | `@lru_cache` 싱글턴 provider | 테넌트별 provider 생성 (`get_sms_provider_for_tenant()`) |
| 네이버 쿠키 | `config.py`의 글로벌 `_runtime_naver_cookie` | `Tenant.naver_cookie` 컬럼, `_runtime_naver_cookie` 제거 |
| 스케줄러 | 전역 단일 실행 | 테넌트별 반복 (모든 활성 테넌트 순회) |

### 1.3 Frontend 계층

| 항목 | 현재 (Before) | 변경 후 (After) |
|------|--------------|----------------|
| 테넌트 선택 | 없음 | 사이드바 상단에 펜션 전환 드롭다운 (STAFF에게는 숨김) |
| 메뉴 표시 | 전체 메뉴 | STAFF: 파티 체크인만 표시 / ADMIN+: 전체 메뉴 |
| API 호출 | 헤더에 토큰만 | 토큰 + `X-Tenant-Id` 헤더 자동 첨부 |

---

## 2. 영향 받는 테이블 목록

### 2.1 테넌트 범위 (tenant_id 추가 필요) -- 18개 테이블

| # | 테이블 | 모델 클래스 |
|---|--------|------------|
| 1 | `reservations` | `Reservation` |
| 2 | `rooms` | `Room` |
| 3 | `buildings` | `Building` |
| 4 | `room_assignments` | `RoomAssignment` |
| 5 | `room_biz_item_links` | `RoomBizItemLink` |
| 6 | `naver_biz_items` | `NaverBizItem` |
| 7 | `message_templates` | `MessageTemplate` |
| 8 | `template_schedules` | `TemplateSchedule` |
| 9 | `reservation_sms_assignments` | `ReservationSmsAssignment` |
| 10 | `messages` | `Message` |
| 11 | `rules` | `Rule` |
| 12 | `documents` | `Document` |
| 13 | `campaign_logs` | `CampaignLog` |
| 14 | `gender_stats` | `GenderStat` |
| 15 | `activity_logs` | `ActivityLog` |
| 16 | `party_checkins` | `PartyCheckin` |
| 17 | `participant_snapshots` | `ParticipantSnapshot` |
| 18 | `reservation_daily_info` | `ReservationDailyInfo` |

### 2.2 공유 테이블 (tenant_id 불필요) -- 1개

| # | 테이블 | 이유 |
|---|--------|------|
| 1 | `users` | 한 유저가 여러 펜션에 접근 가능 |

### 2.3 새로 생성할 테이블 -- 2개

| # | 테이블 | 설명 |
|---|--------|------|
| 1 | `tenants` | 펜션(테넌트) 마스터 |
| 2 | `user_tenant_roles` | 유저-테넌트별 역할 매핑 |

---

## 3. 단계별 구현 계획

---

### Phase 1: DB 스키마 변경 (tenants 테이블 + tenant_id 컬럼)

**무엇을 하는가**: 멀티 테넌트의 기반이 되는 DB 구조를 만든다.

**변경 파일:**
- `backend/app/db/models.py` -- 새 모델 추가 + 기존 모델에 tenant_id 컬럼
- Alembic 마이그레이션 파일 (새로 생성)

#### 3.1.1 `tenants` 테이블 생성

```python
class Tenant(Base):
    """펜션(테넌트) 마스터 테이블"""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # 'handam', 'stable'
    name = Column(String(100), nullable=False)  # '한담', '스테이블'

    # 네이버 연동 설정 (펜션별 독립)
    naver_business_id = Column(String(50), nullable=True)
    naver_cookie = Column(Text, nullable=True)  # 기존 _runtime_naver_cookie 대체
    naver_email = Column(String(200), nullable=True)
    naver_password = Column(String(200), nullable=True)

    # SMS 설정 (같은 Aligo 계정, 다른 발신번호)
    aligo_sender = Column(String(20), nullable=True)  # 펜션별 발신번호

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
```

**`slug` 값**: `handam` (tenant 1), `stable` (tenant 2)

**`naver_cookie` 컬럼 추가 이유**: 기존 `config.py`의 글로벌 `_runtime_naver_cookie`를 제거하고, 테넌트별로 독립 관리한다.

#### 3.1.2 `user_tenant_roles` 테이블 생성

```python
class UserTenantRole(Base):
    """유저별 테넌트 접근 권한"""
    __tablename__ = "user_tenant_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )
```

**설계 결정 -- 역할 분리 원칙:**
- `users.role`은 **글로벌 티어**: `SUPERADMIN`, `ADMIN`, `STAFF`
- `user_tenant_roles`는 **테넌트 매핑만** 담당 (role 컬럼 없음, 어떤 테넌트에 접근 가능한지만 기록)
- SUPERADMIN: 모든 테넌트 자동 접근 (이 테이블에 레코드 불필요)
- ADMIN: 매핑된 테넌트만 접근 가능 (예: HANDAM ADMIN = `users.role=ADMIN` + `user_tenant_roles`에 handam 매핑)
- STAFF: 매핑된 **단일** 테넌트만 접근, party_checkin 엔드포인트만 사용 가능, 테넌트 전환 불가

#### 3.1.3 기존 18개 테이블에 `tenant_id` 컬럼 추가

**TenantMixin 패턴** (반복 코드 방지):

```python
class TenantMixin:
    """모든 테넌트 범위 모델에 적용하는 Mixin"""

    @declared_attr
    def tenant_id(cls):
        return Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
```

사용 예:
```python
class Reservation(TenantMixin, Base):
    __tablename__ = "reservations"
    # ... 기존 컬럼들 유지
```

#### 3.1.4 Unique Constraint 변경

**기존 unique constraint에 tenant_id를 포함해야 하는 목록:**

| 테이블 | 현재 제약조건 | 변경 후 |
|--------|-------------|---------|
| `message_templates` | `key` UNIQUE | `(tenant_id, key)` UNIQUE |
| `naver_biz_items` | `biz_item_id` UNIQUE | `(tenant_id, biz_item_id)` UNIQUE |
| `participant_snapshots` | `date` UNIQUE | `(tenant_id, date)` UNIQUE |
| `buildings` | `name` UNIQUE | `(tenant_id, name)` UNIQUE |
| `reservations` | `external_id` UNIQUE | `(tenant_id, external_id)` UNIQUE |
| `messages` | `message_id` UNIQUE | `(tenant_id, message_id)` UNIQUE |

**유지 (이미 tenant-scoped FK를 통해 격리됨):**

| 테이블 | 제약조건 | 이유 |
|--------|---------|------|
| `reservation_sms_assignments` | `(reservation_id, template_key, date)` | reservation_id가 이미 tenant-scoped |
| `room_biz_item_links` | `(room_id, biz_item_id)` | room_id가 이미 tenant-scoped |
| `room_assignments` | `(reservation_id, date)` | reservation_id가 이미 tenant-scoped |
| `party_checkins` | `(reservation_id, date)` | reservation_id가 이미 tenant-scoped |
| `reservation_daily_info` | `(reservation_id, date)` | reservation_id가 이미 tenant-scoped |

#### 3.1.5 Alembic 마이그레이션

마이그레이션 내용 (순서 중요):

1. `tenants` 테이블 생성
2. 기본 테넌트 2개 삽입: `(1, 'handam', '한담')`, `(2, 'stable', '스테이블')`
3. `config.py`의 기존 네이버 설정을 handam 테넌트에 복사
4. 모든 대상 테이블에 `tenant_id` 컬럼 추가 (`nullable=True`로 먼저)
5. 기존 데이터 전부 `tenant_id = 1` (handam)로 업데이트
6. `tenant_id`를 `nullable=False`로 변경
7. FK 제약 + 인덱스 추가
8. 기존 unique constraint를 `(tenant_id, ...)` 복합으로 변경
9. `user_tenant_roles` 테이블 생성
10. 기존 활성 유저를 handam에 매핑

**downgrade() 구현 (필수):**

```python
def downgrade():
    # 역순으로 제거
    op.drop_table('user_tenant_roles')

    # unique constraint 복원
    for table, old_name, new_name, old_cols in CONSTRAINT_CHANGES:
        op.drop_constraint(new_name, table)
        op.create_unique_constraint(old_name, table, old_cols)

    # tenant_id 컬럼 제거
    for table_name in TENANT_TABLES:
        op.drop_constraint(f'fk_{table_name}_tenant_id', table_name)
        op.drop_index(f'ix_{table_name}_tenant_id', table_name)
        op.drop_column(table_name, 'tenant_id')

    op.drop_table('tenants')
```

**마이그레이션 안전 절차:**

1. Supabase 백업: 마이그레이션 실행 전 `pg_dump` 또는 Supabase 대시보드에서 수동 백업
2. 하위 호환: 전환 기간 동안 `X-Tenant-Id` 헤더가 없으면 기본값 `1` (handam) 사용
3. 롤백 테스트: 스테이징 환경에서 `upgrade` → `downgrade` → `upgrade` 한 사이클 검증 후 프로덕션 적용

#### Phase 1 검증 기준

- [ ] `tenants` 테이블에 handam, stable 레코드 존재
- [ ] 기존 18개 테이블 모든 행에 `tenant_id = 1` 설정됨
- [ ] `tenant_id` 컬럼이 NOT NULL + FK + INDEX
- [ ] `buildings.name`, `reservations.external_id`, `messages.message_id` 등 6개 unique constraint가 `(tenant_id, ...)` 복합으로 변경됨
- [ ] `downgrade()` 실행 후 원래 스키마로 복원되는지 확인
- [ ] `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` 한 사이클 성공

---

### Phase 2: Backend -- 하이브리드 테넌트 필터링 엔진

**무엇을 하는가**: API 요청에서 tenant_id를 추출하고, 하이브리드 방식으로 데이터를 격리한다.

**왜 `before_compile`을 쓰지 않는가**:
- `db.query(func.count())` -- entity가 None이라 필터 적용 불가
- `db.query(RoomAssignment.reservation_id)` 같은 서브쿼리 -- entity가 None일 수 있음
- JOIN 쿼리에서 중복 필터 위험

**하이브리드 전략:**

| 방식 | 적용 대상 | 동작 |
|------|----------|------|
| `with_loader_criteria()` | relationship 기반 자동 로딩 (lazy/eager) | relationship 접근 시 자동 tenant 필터 |
| `tenant_query()` 헬퍼 | 일반 쿼리 (대부분의 API 핸들러) | `db.query(Model).filter(Model.tenant_id == tid)` 래핑 |
| 명시적 `.filter()` | 복잡 쿼리 (aggregate, subquery, dashboard) | 개발자가 직접 `Model.tenant_id == tid` 추가 |
| `before_flush` ContextVar | INSERT | 새 객체에 tenant_id 자동 설정 |

**변경 파일:**
- `backend/app/db/database.py` -- ContextVar 정의 + `before_flush` 이벤트
- `backend/app/db/tenant_filter.py` (신규) -- `tenant_query()` 헬퍼 + `with_loader_criteria` 설정
- `backend/app/api/deps.py` (신규) -- 테넌트 컨텍스트 의존성

#### 3.2.1 ContextVar 정의 + 안전 정책

```python
# backend/app/db/database.py

from contextvars import ContextVar

# 현재 요청의 tenant_id
current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)

# 스케줄러 등에서 의도적으로 필터 우회할 때만 True
bypass_tenant_filter: ContextVar[bool] = ContextVar("bypass_tenant_filter", default=False)
```

**ContextVar 안전 정책:**
- API 컨텍스트에서 `current_tenant_id`가 None이면 → **에러 발생** (필터 없이 전체 데이터 접근 방지)
- 스케줄러에서 전체 테넌트 순회가 필요할 때 → `bypass_tenant_filter.set(True)` 명시적 우회
- 이 구분이 중요한 이유: API에서 ContextVar가 설정 안 된 채 쿼리가 실행되면 데이터 유출 위험

#### 3.2.2 tenant_query 헬퍼

```python
# backend/app/db/tenant_filter.py (신규)

def tenant_query(db: Session, *entities):
    """테넌트 필터가 자동 적용된 쿼리 반환.

    사용법:
        tenant_query(db, Reservation).filter(...)
        tenant_query(db, func.count()).select_from(Reservation).filter(Reservation.tenant_id == tid)
    """
    tid = current_tenant_id.get()
    if tid is None and not bypass_tenant_filter.get():
        raise RuntimeError("tenant_query 호출 시 current_tenant_id가 설정되어야 합니다")

    query = db.query(*entities)

    if tid is not None:
        # entity가 TenantMixin을 가진 모델인 경우에만 필터 적용
        for entity in entities:
            model = getattr(entity, 'class_', entity)  # InstrumentedAttribute 대응
            if hasattr(model, 'tenant_id'):
                query = query.filter(model.tenant_id == tid)

    return query
```

**복잡 쿼리 (aggregate, subquery)는 명시적 필터 사용:**

```python
# dashboard.py, scheduler 등에서:
tid = current_tenant_id.get()
count = db.query(func.count()).select_from(Reservation).filter(
    Reservation.tenant_id == tid
).scalar()
```

#### 3.2.3 with_loader_criteria (relationship 자동 필터)

```python
# TenantMixin에 적용 (SQLAlchemy 1.4+)

from sqlalchemy.orm import with_loader_criteria

# 모든 relationship lazy load 시 tenant 필터 자동 적용
# Session 생성 시 설정:
def get_tenant_scoped_db(tenant_id: int):
    token = current_tenant_id.set(tenant_id)
    db = SessionLocal()
    # relationship 로딩 시 자동 필터
    for model_cls in TENANT_MODELS:
        db.execute(
            with_loader_criteria(model_cls, lambda cls: cls.tenant_id == tenant_id)
        )
    try:
        yield db
    finally:
        db.close()
        current_tenant_id.reset(token)
```

#### 3.2.4 INSERT 자동 주입 (before_flush -- 유지)

```python
@event.listens_for(Session, "before_flush")
def _set_tenant_on_new_objects(session, flush_context, instances):
    """새로 추가되는 객체에 tenant_id 자동 설정"""
    tid = current_tenant_id.get()
    if tid is None:
        return

    for obj in session.new:
        if hasattr(obj, 'tenant_id') and obj.tenant_id is None:
            obj.tenant_id = tid
```

#### 3.2.5 테넌트 컨텍스트 추출 (FastAPI Dependency)

```python
# backend/app/api/deps.py (신규)

async def get_current_tenant_id(
    x_tenant_id: int | None = Header(None, alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> int:
    """요청 헤더에서 tenant_id를 추출하고 유효성 검증.
    하위 호환: 헤더가 없으면 기본값 1 (handam) — 전환 기간 동안만.
    """
    tenant_id = x_tenant_id or 1  # 전환 기간 기본값
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="유효하지 않은 테넌트입니다")
    return tenant.id
```

#### Phase 2 검증 기준

- [ ] `tenant_query(db, Reservation)` 호출 시 현재 tenant의 예약만 반환
- [ ] `tenant_query(db, func.count())` 호출 시 RuntimeError 발생 (entity에 tenant_id 없으므로 명시적 필터 필요)
- [ ] API 컨텍스트에서 ContextVar 미설정 시 에러 발생 (데이터 유출 방지)
- [ ] `bypass_tenant_filter=True` 설정 시 전체 데이터 접근 가능
- [ ] `before_flush`로 새 객체 생성 시 tenant_id 자동 주입됨
- [ ] `X-Tenant-Id` 헤더 없이 API 호출 시 기본값 1 (handam) 적용됨

---

### Phase 3: 역할 구조 재설계 + 테넌트별 권한

**무엇을 하는가**: `require_role()`을 확장하여 글로벌 role + 테넌트 매핑을 동시에 검증하고, STAFF의 접근 범위를 제한한다.

**변경 파일:**
- `backend/app/auth/dependencies.py` -- 테넌트 권한 검증 로직 추가
- `backend/app/api/auth.py` -- 로그인 응답에 테넌트 목록 + 역할 포함

#### 3.3.1 역할 계층 구조

```
SUPERADMIN (전체)
  ├── 모든 테넌트 접근 (user_tenant_roles 매핑 불필요)
  ├── 모든 메뉴 접근
  └── 테넌트 전환 가능

ADMIN (펜션별)
  ├── 매핑된 테넌트만 접근 (user_tenant_roles 필수)
  ├── 모든 메뉴 접근
  └── 매핑된 테넌트 간 전환 가능
  예: HANDAM ADMIN = users.role=ADMIN + user_tenant_roles(tenant=handam)
      STABLE ADMIN = users.role=ADMIN + user_tenant_roles(tenant=stable)

STAFF (단일 펜션, 제한된 메뉴)
  ├── 매핑된 단일 테넌트만 접근 (user_tenant_roles에 1개만)
  ├── party_checkin 엔드포인트만 접근 가능
  ├── 테넌트 전환 UI 숨김
  └── 사이드바에 파티 체크인만 표시
```

#### 3.3.2 require_role() 확장

```python
# backend/app/auth/dependencies.py

def require_role(*roles: UserRole):
    """글로벌 role + 테넌트 매핑을 동시에 검증"""
    async def role_checker(
        current_user: User = Depends(get_current_user),
        tenant_id: int = Depends(get_current_tenant_id),
        db: Session = Depends(get_db),
    ) -> User:
        # 1. 글로벌 role 확인
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        # 2. SUPERADMIN은 테넌트 매핑 확인 불필요
        if current_user.role == UserRole.SUPERADMIN:
            return current_user

        # 3. ADMIN/STAFF는 해당 테넌트에 매핑되어 있어야 함
        mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == tenant_id,
        ).first()

        if not mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")

        return current_user
    return role_checker
```

#### 3.3.3 STAFF 메뉴 제한

**Backend -- 엔드포인트 접근 제어:**

```python
# 기존 require_any_role (SUPERADMIN, ADMIN, STAFF) → party_checkin 라우터에만 적용
# 나머지 라우터는 require_admin_or_above (SUPERADMIN, ADMIN)로 변경

# api/party_checkin.py -- STAFF 접근 허용
@router.get("", dependencies=[Depends(require_any_role)])

# api/reservations.py -- STAFF 접근 차단
@router.get("", dependencies=[Depends(require_admin_or_above)])
```

**Frontend -- 사이드바 메뉴 제한:**

```typescript
// Layout.tsx에서 role 기반 메뉴 필터링
const menuItems = user.role === 'STAFF'
  ? [{ path: '/party-checkin', label: '파티 체크인' }]
  : fullMenuItems  // 전체 메뉴
```

#### 3.3.4 로그인 응답 확장

```python
# 변경 후 로그인 응답
{
  "token": "...",
  "user": {"id": 1, "username": "admin", "role": "ADMIN"},
  "tenants": [
    {"id": 1, "slug": "handam", "name": "한담"}
  ]
}
```

- SUPERADMIN: 모든 활성 테넌트 반환
- ADMIN/STAFF: `user_tenant_roles`에 매핑된 테넌트만 반환

#### Phase 3 검증 기준

- [ ] SUPERADMIN: 모든 테넌트, 모든 엔드포인트 접근 가능
- [ ] HANDAM ADMIN: handam 테넌트만 접근, 모든 메뉴 사용 가능, stable 접근 시 403
- [ ] STAFF: 매핑된 단일 테넌트의 party_checkin만 접근 가능, 다른 엔드포인트 403
- [ ] 로그인 응답에 접근 가능한 테넌트 목록이 올바르게 포함됨
- [ ] `require_role()`이 글로벌 role + 테넌트 매핑 두 가지 모두 검증

---

### Phase 4: Factory 개편 + 호출처 전환

**무엇을 하는가**: `@lru_cache` 싱글턴을 제거하고, 테넌트별 provider 생성 함수로 교체한다.

**변경 파일:**
- `backend/app/factory.py` -- lru_cache 제거 + 테넌트별 함수 추가
- `backend/app/config.py` -- `_runtime_naver_cookie` 제거

#### 3.4.1 Factory 변경

```python
# backend/app/factory.py

# [제거] @lru_cache(maxsize=1) -- 테넌트별로 다른 설정이 필요하므로

def get_sms_provider_for_tenant(tenant: "Tenant") -> SMSProvider:
    """테넌트별 SMS provider (같은 Aligo 계정, 다른 발신번호)"""
    if settings.DEMO_MODE:
        return MockSMSProvider()
    from app.real.sms import RealSMSProvider
    return RealSMSProvider(
        api_key=settings.ALIGO_API_KEY,
        user_id=settings.ALIGO_USER_ID,
        sender=tenant.aligo_sender or settings.ALIGO_SENDER,
        testmode=settings.ALIGO_TESTMODE,
    )

def get_reservation_provider_for_tenant(tenant: "Tenant") -> ReservationProvider:
    """테넌트별 예약 provider"""
    from app.real.reservation import RealReservationProvider
    return RealReservationProvider(
        business_id=tenant.naver_business_id,
        cookie=tenant.naver_cookie or "",
    )

# 기존 함수는 deprecated wrapper로 유지 (전환 기간)
def get_sms_provider() -> SMSProvider:
    """[DEPRECATED] get_sms_provider_for_tenant()을 사용하세요"""
    import warnings
    warnings.warn("get_sms_provider() is deprecated", DeprecationWarning)
    if settings.DEMO_MODE:
        from app.mock.sms import MockSMSProvider
        return MockSMSProvider()
    from app.real.sms import RealSMSProvider
    return RealSMSProvider(
        api_key=settings.ALIGO_API_KEY,
        user_id=settings.ALIGO_USER_ID,
        sender=settings.ALIGO_SENDER,
        testmode=settings.ALIGO_TESTMODE,
    )
```

#### 3.4.2 호출처 전환 목록 (전수)

| # | 파일 | 라인 | 현재 호출 | 변경 |
|---|------|------|----------|------|
| 1 | `scheduler/template_scheduler.py` | 194 | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` -- tenant는 ContextVar에서 조회 |
| 2 | `scheduler/jobs.py` | 11,33 | `get_reservation_provider()` | `get_reservation_provider_for_tenant(tenant)` -- 테넌트 순회 루프 내 |
| 3 | `scheduler/jobs.py` | 11 | `get_sms_provider()` import | 제거 (사용처 없음 확인 후) |
| 4 | `api/webhooks.py` | | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` -- Depends(get_current_tenant)에서 tenant 주입 |
| 5 | `api/messages.py` | | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` |
| 6 | `api/auto_response.py` | | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` |
| 7 | `api/reservations.py` | | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` |
| 8 | `api/rooms.py` | | `get_sms_provider()` | `get_sms_provider_for_tenant(tenant)` |

#### 3.4.3 `_runtime_naver_cookie` 제거

```python
# config.py에서 제거:
# _runtime_naver_cookie: str | None = None
# def get_naver_cookie() ...
# def set_naver_cookie() ...

# api/settings.py에서 변경:
# 기존: set_naver_cookie(cookie) → 글로벌 변수 변경
# 변경: tenant.naver_cookie = cookie; db.commit() → DB에 저장
```

#### Phase 4 검증 기준

- [ ] `factory.py`에서 `@lru_cache` 제거됨
- [ ] 8개 호출처 모두 `_for_tenant()` 함수로 전환됨
- [ ] `config.py`에서 `_runtime_naver_cookie` 관련 코드 3개 함수/변수 제거됨
- [ ] `api/settings.py`의 쿠키 저장이 `Tenant.naver_cookie` DB 컬럼에 저장됨
- [ ] 기존 `get_sms_provider()` 호출 시 DeprecationWarning 발생

---

### Phase 5: API 엔드포인트 전환 + SSE 테넌트 격리

**무엇을 하는가**: 모든 API 엔드포인트를 테넌트 인식으로 전환하고, SSE 이벤트 버스에 테넌트 격리를 추가한다.

**변경 파일 (API -- `Depends(get_db)` → `Depends(get_tenant_scoped_db)`):**

| 파일 | db.query() 호출 수 | 변경 내용 |
|------|-------------------|----------|
| `api/reservations.py` | 20 | tenant_scoped_db + tenant_query |
| `api/rooms.py` | 8 | tenant_scoped_db + tenant_query |
| `api/templates.py` | 8 | tenant_scoped_db + tenant_query |
| `api/template_schedules.py` | 9 | tenant_scoped_db + tenant_query |
| `api/dashboard.py` | 7 | tenant_scoped_db + 명시적 필터 (aggregate 쿼리) |
| `api/buildings.py` | 6 | tenant_scoped_db + tenant_query |
| `api/messages.py` | 4 | tenant_scoped_db + tenant_query |
| `api/activity_logs.py` | 2 | tenant_scoped_db + tenant_query |
| `api/rules.py` | 3 | tenant_scoped_db + tenant_query |
| `api/documents.py` | 2 | tenant_scoped_db + tenant_query |
| `api/party_checkin.py` | 6 | tenant_scoped_db + tenant_query |
| `api/webhooks.py` | 1 | tenant_scoped_db + tenant_query |
| `api/auto_response.py` | 1 | tenant_scoped_db + tenant_query |
| `api/reservations_sync.py` | 1 | tenant 파라미터로 네이버 설정 참조 |
| `api/auth.py` | 6 | `get_db` 유지 (유저는 공유), 테넌트 목록 조회 API 추가 |
| `api/settings.py` | -- | 네이버 쿠키를 Tenant DB 컬럼으로 관리 |

**추가 API 엔드포인트:**

```python
# api/tenants.py (신규)
@router.get("/api/tenants")       # 현재 유저가 접근 가능한 테넌트 목록
@router.get("/api/tenants/{id}")  # 테넌트 상세 정보
@router.post("/api/tenants")      # 테넌트 생성 (superadmin only)
@router.put("/api/tenants/{id}")  # 테넌트 수정 (superadmin only)
```

#### 3.5.1 SSE 이벤트 버스 테넌트 격리

현재 `event_bus.py`는 전체 클라이언트에 이벤트를 브로드캐스트한다. 테넌트별 격리가 필요하다.

**변경 방식: 이벤트 payload에 tenant_id 포함 + 프론트엔드 필터링**

```python
# backend/app/services/event_bus.py 변경

# 구독 시 tenant_id 지정
_queues: dict[int, set[asyncio.Queue]] = {}  # tenant_id → queues

def subscribe(tenant_id: int) -> asyncio.Queue:
    q = asyncio.Queue(maxsize=50)
    if tenant_id not in _queues:
        _queues[tenant_id] = set()
    _queues[tenant_id].add(q)
    return q

def unsubscribe(tenant_id: int, q: asyncio.Queue) -> None:
    if tenant_id in _queues:
        _queues[tenant_id].discard(q)

def publish(event_type: str, data: dict, tenant_id: int) -> None:
    """특정 테넌트의 클라이언트에게만 이벤트 전송"""
    queues = _queues.get(tenant_id, set())
    payload = json.dumps({"event": event_type, "data": data})
    for q in list(queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("SSE queue full, event dropped")
```

**publish 호출처 업데이트:**
- `template_scheduler.py`에서 publish 호출 시 tenant_id 전달
- `api/events.py`에서 subscribe 시 tenant_id 전달

#### Phase 5 검증 기준

- [ ] 모든 API 라우터에서 `get_db` → `get_tenant_scoped_db` 전환 완료 (`auth.py` 제외)
- [ ] 테넌트 A로 생성한 데이터가 테넌트 B에서 조회되지 않음
- [ ] SSE 이벤트가 해당 테넌트의 클라이언트에게만 전송됨
- [ ] dashboard.py의 aggregate 쿼리가 현재 테넌트 데이터만 집계
- [ ] `api/tenants.py` CRUD 엔드포인트 동작 확인

---

### Phase 6: 스케줄러 -- 테넌트별 독립 실행

**무엇을 하는가**: 모든 스케줄러 job이 활성 테넌트를 순회하며 각각 독립 실행되게 한다.

**변경 파일:**
- `backend/app/scheduler/jobs.py` -- 모든 job을 테넌트 순회 방식으로
- `backend/app/scheduler/template_scheduler.py` -- 테넌트 컨텍스트 바인딩
- `backend/app/scheduler/room_auto_assign.py` -- 테넌트 컨텍스트 바인딩
- `backend/app/scheduler/schedule_manager.py` -- 테넌트별 스케줄 로드

#### 3.6.1 각 Job별 테넌트 처리 방침

| Job | 현재 동작 | 변경 후 | 비고 |
|-----|----------|---------|------|
| `sync_naver_reservations_job` | 글로벌 1회 | 테넌트 순회 | naver 설정 없는 테넌트 건너뜀 |
| `daily_room_assign_job` | 글로벌 1회 | **테넌트 순회 + ContextVar 설정** | 각 테넌트별 방 배정 |
| `sync_status_log_job` | 글로벌 1회 | **테넌트 순회** | activity_log에 tenant_id 필요 |
| `load_template_schedules` | 글로벌 1회 | 테넌트 순회 | 테넌트별 스케줄 로드 |

#### 3.6.2 스케줄러 공통 패턴

```python
async def _for_each_tenant(job_fn):
    """모든 활성 테넌트에 대해 job을 실행하는 공통 래퍼"""
    bypass_token = bypass_tenant_filter.set(True)
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    finally:
        db.close()
        bypass_tenant_filter.reset(bypass_token)

    for tenant in tenants:
        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            await job_fn(tenant, db)
        except Exception as e:
            logger.error(f"[{tenant.slug}] Job error: {e}")
            db.rollback()
        finally:
            db.close()
            current_tenant_id.reset(token)
```

#### 3.6.3 daily_room_assign_job 테넌트 순회

```python
async def daily_room_assign_job():
    async def _assign(tenant, db):
        result = daily_assign_rooms(db)  # ContextVar 설정됨, tenant_query 사용 가능
        logger.info(f"[{tenant.slug}] Room assign: {result}")

    await _for_each_tenant(_assign)
```

#### 3.6.4 sync_status_log_job 테넌트 순회

```python
async def sync_status_log_job():
    """activity_log에 tenant_id가 필요하므로 테넌트 순회"""
    async def _log(tenant, db):
        log_activity(db, type="sync_status", title=f"...", created_by="scheduler")
        db.commit()

    await _for_each_tenant(_log)
```

#### 3.6.5 template_scheduler.py 변경

`TemplateSender.__init__`에서 `get_sms_provider()` 대신 `get_sms_provider_for_tenant(tenant)` 사용:

```python
class TemplateSender:
    def __init__(self, db: Session, tenant: Tenant):
        self.db = db
        self.tenant = tenant
        self.sms_provider = get_sms_provider_for_tenant(tenant)
        self.template_renderer = TemplateRenderer(db)
```

#### Phase 6 검증 기준

- [ ] `sync_naver_reservations_job`이 handam/stable 각각의 네이버 설정으로 독립 동기화
- [ ] `daily_room_assign_job`이 각 테넌트의 방만 배정 (교차 배정 없음)
- [ ] `sync_status_log_job`이 각 테넌트에 대해 별도 activity_log 생성
- [ ] 네이버 설정이 없는 테넌트는 sync에서 건너뜀
- [ ] `template_scheduler.py`가 테넌트별 발신번호로 SMS 발송

---

### Phase 7: Frontend -- 테넌트 선택기 & STAFF 제한

**무엇을 하는가**: 사이드바에 펜션 전환 UI를 추가하고, 모든 API 호출에 `X-Tenant-Id` 헤더를 자동 첨부한다. STAFF에게는 제한된 UI를 표시한다.

**변경 파일:**
- `frontend/src/stores/tenant-store.ts` (신규)
- `frontend/src/services/api.ts` -- interceptor에 tenant 헤더 추가
- `frontend/src/components/Layout.tsx` -- 사이드바에 테넌트 선택기 + STAFF 메뉴 제한
- `frontend/src/stores/auth-store.ts` -- 로그인 시 테넌트 목록 로드

#### 3.7.1 Tenant Store (Zustand)

```typescript
interface Tenant {
  id: number
  slug: string
  name: string
}

interface TenantState {
  tenants: Tenant[]
  currentTenantId: number | null
  setTenants: (tenants: Tenant[]) => void
  setCurrentTenant: (id: number) => void
}
```

- `currentTenantId`는 `localStorage`에 `sms-tenant-id`로 저장
- 로그인 직후 응답의 `tenants`로 초기화
- 테넌트가 1개뿐이면 자동 선택

#### 3.7.2 API Interceptor 수정

```typescript
api.interceptors.request.use((config) => {
  const tenantId = localStorage.getItem('sms-tenant-id')
  if (tenantId) {
    config.headers['X-Tenant-Id'] = tenantId
  }
  return config
})
```

#### 3.7.3 사이드바 테넌트 선택기

```
[S] SMS
[v 한담  ] ← ADMIN/SUPERADMIN에게만 표시
  - 한담 (handam) ✓
  - 스테이블 (stable)
─────────────────
운영 관리
  대시보드     ← STAFF에게 숨김
  예약 관리     ← STAFF에게 숨김
  ...
  파티 체크인   ← 모든 역할에게 표시
```

- STAFF: 테넌트 전환기 숨김, 사이드바에 파티 체크인만 표시
- 테넌트 1개인 ADMIN도 드롭다운 숨김 (변경할 필요 없으므로)
- 전환 시 `window.location.reload()` (가장 안전)

#### 3.7.4 Seed 데이터 변경

기존 `pension-a` / `pension-b` → `handam` / `stable`로 모든 참조 업데이트:
- `backend/app/db/seed.py`
- 마이그레이션 스크립트
- 테스트 데이터

#### Phase 7 검증 기준

- [ ] ADMIN이 사이드바에서 한담 ↔ 스테이블 전환 가능
- [ ] 전환 후 모든 데이터가 새 테넌트의 데이터로 리로드됨
- [ ] STAFF에게 테넌트 전환기가 표시되지 않음
- [ ] STAFF 사이드바에 파티 체크인만 표시됨
- [ ] 모든 API 호출에 `X-Tenant-Id` 헤더가 자동 첨부됨
- [ ] seed 데이터에 `pension-a`/`pension-b` 참조가 0건

---

## 4. 데이터 격리 안전장치 상세

### 4.1 자동 필터링 흐름 (요청 1건의 생명주기)

```
1. 프론트엔드 → API 요청
   GET /api/reservations?date=2026-03-19
   Headers: { Authorization: Bearer xxx, X-Tenant-Id: 1 }

2. FastAPI 라우터 진입
   ├─ get_current_user() → 토큰 검증 → User 객체 반환
   ├─ get_current_tenant_id() → X-Tenant-Id 헤더에서 1 추출
   ├─ verify_tenant_access() → require_role()에서 글로벌 role + tenant 매핑 확인
   └─ get_tenant_scoped_db() → ContextVar에 tenant_id=1 저장, Session 생성

3. 쿼리 실행 (하이브리드)
   # 일반 쿼리: tenant_query 헬퍼 사용
   tenant_query(db, Reservation).filter(Reservation.check_in_date == "2026-03-19")
   → SELECT * FROM reservations WHERE tenant_id = 1 AND check_in_date = '2026-03-19'

   # 복잡 쿼리: 명시적 필터
   db.query(func.count()).select_from(Reservation).filter(
       Reservation.tenant_id == tid, Reservation.status == 'confirmed'
   )

4. 결과 반환 → 한담의 예약만 응답
```

### 4.2 실패 방지 (Edge Cases)

| 시나리오 | 대응 |
|---------|------|
| X-Tenant-Id 헤더 누락 | 전환 기간: 기본값 1 (handam) / 전환 후: 422 |
| 유효하지 않은 tenant_id | dependency에서 404 |
| 유저에게 해당 테넌트 권한 없음 | require_role()에서 403 |
| STAFF가 party_checkin 외 접근 | require_admin_or_above에서 403 |
| API에서 ContextVar 미설정 | RuntimeError (데이터 유출 방지) |
| 스케줄러에서 전체 조회 필요 | bypass_tenant_filter=True 명시 |
| aggregate 쿼리 (func.count) | 명시적 `.filter(Model.tenant_id == tid)` 사용 |
| 서브쿼리 | 명시적 `.filter()` 사용 |

---

## 5. 구현 순서 요약

| Phase | 작업 | 예상 영향 범위 | 의존성 |
|-------|------|--------------|--------|
| **1** | DB 스키마 (tenants + tenant_id + constraints) | models.py + 마이그레이션 | 없음 |
| **2** | 하이브리드 필터링 엔진 | database.py + tenant_filter.py + deps.py | Phase 1 |
| **3** | 역할 구조 재설계 + 권한 | auth/dependencies.py + auth API | Phase 1 |
| **4** | Factory 개편 + 호출처 전환 | factory.py + config.py + 8개 호출처 | Phase 1 |
| **5** | API 엔드포인트 전환 + SSE 격리 | api/*.py (16개 파일) + event_bus.py | Phase 2, 3, 4 |
| **6** | 스케줄러 테넌트 순회 | scheduler/*.py (4개 파일) | Phase 2, 4 |
| **7** | 프론트엔드 UI + STAFF 제한 | stores, api.ts, Layout.tsx | Phase 5 |

---

## 6. Open Questions / 결정 필요 사항

- [ ] **한담/스테이블 네이버 Business ID** -- 마이그레이션 시 seed 데이터로 필요
- [ ] **한담/스테이블 Aligo 발신번호** -- 같은 Aligo 계정이지만 발신번호가 각각 뭔지
- [ ] **STAFF가 여러 펜션에 동시 매핑되는 케이스가 있는지** -- 없다고 가정했지만 확인 필요
- [ ] **Activity Log 뷰어**: SUPERADMIN이 전체 테넌트의 활동 로그를 한 화면에서 보고 싶은지
- [ ] **전환 기간 종료 시점**: X-Tenant-Id 기본값(handam) 해제 시기
