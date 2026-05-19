# Tenant Model Registry — 누락 등록 fix + 회귀 방지 계획

> 작성일: 2026-05-19
> 상태: 사전조사 검토 대기
> 트리거: 운영에서 현장매출 페이지에 cross-tenant 진행자명 노출 사고 발견 (2026-05-19)
> 관련 사고 진단: 본 문서 §"사고 요약" 참조

---

## 사고 요약

운영 환경 (한담누리 tenant, `id=1`) 에서 현장매출 조회 페이지 (`/api/sales-report`) 응답에 **스테이블 tenant (`id=2`) 의 진행자명 4명 + 그들의 여자초대수**가 그대로 노출됨.

### 사용자 확인 화면 (한담 로그인, 5월 기간):
```
진행자    여자초대수    파티지표 / 매출지표 (모두 0)
국영수    9명
메테호    8명
에겐성호  6명
제이슨    7명
```

### DB 쿼리 결과 (운영 Supabase, 2026-05-19 직접 확인):
- `tenant_id=2 (stable)` 의 `OnsiteFemaleInvite.total_invites`:
  - 국영수=9, 메테호=8, 제이슨=7, 에겐성호=6 — **화면 값과 1:1 일치**
- `tenant_id=1 (handam)` 의 `OnsiteFemaleInvite`: 0건
- `daily_hosts`, `onsite_sales`, `onsite_auctions`, `party_hosts` 등은 모두 정상 격리 (cross-tenant 0건)

### 근본 원인

`backend/app/db/models.py:609-614` 의 자동 필터 등록 리스트에 **`OnsiteFemaleInvite` 와 `DailyReviewCount` 가 누락**:

```python
for _model in [
    Reservation, MessageTemplate, ReservationSmsAssignment,
    RoomBizItemLink, Building, RoomGroup, Room, RoomAssignment,
    NaverBizItem, TemplateSchedule, ActivityLog, PartyCheckin, ReservationDailyInfo,
    ParticipantSnapshot, OnsiteSale, DailyHost, OnsiteAuction, PartyHost,
    # ← OnsiteFemaleInvite 누락
    # ← DailyReviewCount 누락
]:
    _register(_model)
```

두 모델은 `TenantMixin` 상속(`models.py:572,587`) + `UniqueConstraint("tenant_id", ...)` 정의 → **격리 의도는 명확**, 단지 등록이 빠짐.

`tenant_context.py:67-94` 의 `before_compile` 이벤트가 `TENANT_MODELS` 집합에 등록된 모델만 자동 `WHERE tenant_id = X` 필터 적용 → 미등록 모델의 SELECT 는 **모든 tenant 데이터 그대로 반환**.

INSERT 는 `_set_tenant_on_new_objects` (`tenant_context.py:51`) 가 `hasattr(obj, 'tenant_id')` 만 체크하므로 두 모델 모두 정상 주입 (DB 데이터 검증 완료, NULL 0행).

---

## 원칙

1. **기존 의도된 동작 보존** — `tenant_id` 자체는 정상 저장돼 있으므로 데이터 마이그레이션 불필요.
2. **단일 fix 의 최소 변경** — 1줄(2개 모델 추가)로 자동 필터 적용.
3. **회귀 영구 차단** — 같은 패턴(TenantMixin 추가 + 등록 누락) 재발 방지 자동 검증.
4. **각 단계는 별도 PR + 별도 사전조사 문서**.

---

## 단계 분해 (2개)

⚪ = 동작 변화 없음 / 🔵 = 의도된 동작 변화 (보안 회귀 해결) / ⚫ = 정리·리팩토링.

### Step 01 — 누락 모델 2개 등록 🔵

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|------|-----------|-------------|
| 1 | `models.py:613` 의 등록 리스트에 `OnsiteFemaleInvite`, `DailyReviewCount` 추가 | `backend/app/db/models.py` | 추가 2 lines |

**의도된 동작 변화**:
- `db.query(OnsiteFemaleInvite)` 와 `db.query(DailyReviewCount)` 가 자동으로 `WHERE tenant_id = X` 적용
- 영향 endpoint: `/api/sales-report`, `/api/onsite-female-invites/*` (4 endpoint), `/api/daily-review/*` (2 endpoint)
- 결과: cross-tenant leak 차단 + cross-tenant 조작 (한담 user 가 stable 의 invite ID 알면 수정/삭제 가능했음) 차단

**사전조사 문서**: `tenant-model-registry-step-01-add-missing-models.md`

### Step 02 — 회귀 방지 lint/test ⚪

| # | 작업 | 변경 파일 | 코드 변경량 |
|---|------|-----------|-------------|
| 2 | TenantMixin 상속 클래스 ↔ TENANT_MODELS 집합 일치 자동 검증 test | `backend/tests/unit/test_tenant_model_registry.py` (신규) | 추가 ~30 lines |

**동작 동등성**: 새 test 만 추가. 기존 코드 변경 0.

**검증 내용**: `TenantMixin` 의 모든 서브클래스(`__subclasses__()` 또는 grep 기반)가 `TENANT_MODELS` 집합에 포함됨을 단정. 누락 시 test 실패.

**사전조사 문서**: `tenant-model-registry-step-02-regression-guard.md` (Step 01 머지 후 작성)

---

## 단계간 의존성

```
Step 01 (즉시 fix, 보안 패치)
   │
   └─► Step 02 (회귀 방지)
```

Step 02 는 Step 01 없어도 단독으로 의미 있지만, Step 01 이 보안 사고 대응이므로 **우선순위 #1**. Step 02 는 후속.

---

## 다음 액션

1. 본 분해안 검토 합의
2. Step 01 사전조사 문서 (`tenant-model-registry-step-01-add-missing-models.md`) 작성 및 검토
3. Step 01 코드 변경 PR → main 머지 → 운영 배포
4. (배포 후) 한담 user 가 SalesReport 5월 조회 시 stable 진행자 표시 사라짐 수동 검증
5. Step 02 사전조사 + 작업

---

## 미결 검토 항목

- [ ] Step 01 머지 후 운영 배포 → 사용자 화면 검증 시점·방법 합의
- [ ] Step 02 의 검증 방식 — `__subclasses__()` (runtime 검증) vs grep 기반 (정적 검증) vs `register_tenant_model` 데코레이터 자동화 (코드 패턴 변경) — Step 02 사전조사에서 결정
- [ ] cross-tenant 조작 (UPDATE/DELETE) 가 실제로 발생했는지 운영 로그 확인 — ActivityLog 또는 diag 로그
