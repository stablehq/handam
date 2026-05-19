# 단계 #1 사전조사 — queryKeys.ts 카테고리 보강 (인프라)

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #1"
> 부모 설계: [react-query-migration-design.md](./react-query-migration-design.md)
> 분류: ⚪ 동작 변화 없음 (선언만 추가, 사용처 0)
> 변경 규모: 1개 파일, 추가 ~50 lines

---

## 1. 목적

`frontend/src/lib/queryKeys.ts` 에 7개 신규 카테고리 + 기존 카테고리 확장 함수 추가. 본 step 시점에는 어떤 페이지도 신규 키를 사용하지 않음. 후속 Step #2~#8 의 useQuery / useMutation 호출처가 참조할 key factory 를 사전 확정.

### 본 단계가 다루는 것 (= 인프라 보강)

- 7개 신규 카테고리 정의: `dashboard`, `activityLogs`, `salesReport`, `partyHosts`, `templateSchedules`, `buildings`, `partyCheckin`
- 기존 카테고리 확장 함수 추가: `reservations.filtered`, `rooms.listWithInactive`, `rooms.bizItems`, `templates.list`, `templates.variables`, `templates.all`
- 각 카테고리에 `all()` 함수 (broad invalidation 용) 일괄 추가
- 모든 신규 key 가 `getTenantId()` 자동 포함

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| 페이지에서 신규 key 사용 (useQuery 호출) | Step #2~#8 (각 페이지별) |
| 기존 4개 카테고리 (`reservations`, `rooms`, `templates`, `settings`) 의 함수 시그니처 변경 | 없음 (호환성 유지) |
| 기존 key 사용처 (RoomAssignment 등) 코드 변경 | 없음 |
| staleTime / gcTime 변경 | 없음 (queryClient.ts 그대로) |
| axios 인터셉터 / tenant-store 변경 | 없음 |

---

## 2. 변경 대상 코드

### 2-1. `frontend/src/lib/queryKeys.ts` 전체

**Before** (현재 20줄):

```ts
function getTenantId(): string {
  return localStorage.getItem('sms-tenant-id') || 'unknown';
}

export const queryKeys = {
  reservations: {
    list: (date: string) => ['reservations', getTenantId(), date] as const,
    all: () => ['reservations', getTenantId()] as const, // for broad invalidation
  },
  rooms: {
    list: () => ['rooms', getTenantId()] as const,
    groups: () => ['roomGroups', getTenantId()] as const,
  },
  templates: {
    labels: () => ['templates', 'labels', getTenantId()] as const,
  },
  settings: {
    highlightColors: () => ['settings', 'highlightColors', getTenantId()] as const,
  },
} as const;
```

**After** (예상 ~70 lines):

```ts
function getTenantId(): string {
  return localStorage.getItem('sms-tenant-id') || 'unknown';
}

/**
 * Reservations 페이지 필터 객체 — list 와 별도 key 로 캐시 분리.
 * 필터/페이지 조합마다 다른 key → React Query 자동 캐시 격리.
 */
export interface ReservationFilters {
  page: number;
  pageSize?: number;
  status?: string;
  source?: string;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
}

/**
 * ActivityLogs 페이지 필터 객체.
 */
export interface ActivityLogFilters {
  type?: string;
  status?: string;
  date?: string;
  q?: string;
}

export const queryKeys = {
  // ========= 기존 =========
  reservations: {
    list: (date: string) => ['reservations', getTenantId(), date] as const,
    all: () => ['reservations', getTenantId()] as const,
    filtered: (filters: ReservationFilters) =>
      ['reservations', getTenantId(), 'filtered', filters] as const,
  },
  rooms: {
    list: () => ['rooms', getTenantId()] as const,
    groups: () => ['roomGroups', getTenantId()] as const,
    listWithInactive: () => ['rooms', getTenantId(), 'withInactive'] as const,
    bizItems: () => ['rooms', getTenantId(), 'bizItems'] as const,
    all: () => ['rooms', getTenantId()] as const,
  },
  templates: {
    labels: () => ['templates', 'labels', getTenantId()] as const,
    list: () => ['templates', getTenantId(), 'list'] as const,
    variables: () => ['templates', getTenantId(), 'variables'] as const,
    all: () => ['templates', getTenantId()] as const,
  },
  settings: {
    highlightColors: () => ['settings', 'highlightColors', getTenantId()] as const,
  },

  // ========= 신규 =========
  dashboard: {
    schedules: () => ['dashboard', getTenantId(), 'schedules'] as const,
    stats: () => ['dashboard', getTenantId(), 'stats'] as const,
    all: () => ['dashboard', getTenantId()] as const,
  },
  activityLogs: {
    list: (filters: ActivityLogFilters) =>
      ['activityLogs', getTenantId(), 'list', filters] as const,
    stats: () => ['activityLogs', getTenantId(), 'stats'] as const,
    all: () => ['activityLogs', getTenantId()] as const,
  },
  salesReport: {
    report: (dateFrom: string, dateTo: string) =>
      ['salesReport', getTenantId(), dateFrom, dateTo] as const,
    all: () => ['salesReport', getTenantId()] as const,
  },
  partyHosts: {
    list: () => ['partyHosts', getTenantId()] as const,
  },
  templateSchedules: {
    list: () => ['templateSchedules', getTenantId(), 'list'] as const,
    customTypes: () => ['templateSchedules', 'customTypes'] as const, // tenant-agnostic
    all: () => ['templateSchedules', getTenantId()] as const,
  },
  buildings: {
    list: () => ['buildings', getTenantId()] as const,
  },
  partyCheckin: {
    guests: (date: string, section: 'stable' | 'unstable') =>
      ['partyCheckin', getTenantId(), 'guests', date, section] as const,
    sales: (date: string) => ['partyCheckin', getTenantId(), 'sales', date] as const,
    host: (date: string) => ['partyCheckin', getTenantId(), 'host', date] as const,
    auction: (date: string) => ['partyCheckin', getTenantId(), 'auction', date] as const,
    review: (date: string) => ['partyCheckin', getTenantId(), 'review', date] as const,
    invites: (date: string) => ['partyCheckin', getTenantId(), 'invites', date] as const,
    all: () => ['partyCheckin', getTenantId()] as const,
  },
} as const;
```

**변경 의도**:
- 신규 7개 카테고리 + 기존 3개 카테고리 확장 함수 6개 추가
- 모든 key 가 `getTenantId()` 자동 포함 (cross-tenant 캐시 격리)
- 각 카테고리에 `all()` 추가 — broad invalidation 표준화
- 필터 객체는 별도 TypeScript interface 로 추출 (`ReservationFilters`, `ActivityLogFilters`) — 호출처 타입 안전성

---

## 3. 설계 결정 — 라인 단위 근거

### 3-1. 기존 key 시그니처 변경 없음 (호환성)

`reservations.list(date)`, `rooms.list()`, `rooms.groups()`, `templates.labels()`, `settings.highlightColors()` 모두 그대로. 사용처 (`RoomAssignment.tsx`, `useReservationsData.ts`, `useStayGroup.ts`) 변경 0.

**검증**: `grep -rnE "queryKeys\.(reservations\.list|rooms\.list|rooms\.groups|templates\.labels|settings\.highlightColors)" frontend/src/`
- 기존 호출 시그니처 그대로 동작 (함수 추가만, 기존 함수 변경 없음).

### 3-2. 신규 key 패턴 — `[category, tid, ...params]`

기존 key 가 일관성 약함 (`reservations.list` = `[cat, tid, param]` vs `templates.labels` = `[cat, 'labels', tid]`). 신규는 통일된 패턴 `[category, tid, ...subkey, ...params]` 적용.

**근거**:
- React Query partial match: `invalidateQueries({ queryKey: ['reservations'] })` 가 `['reservations', tid, ...]` 모두 잡음 → broad invalidation 자연스러움
- 카테고리가 prefix 면 cross-tenant 캐시도 같이 invalidate 됨 — 사용자는 한 tenant 만 보니까 영향 없음

### 3-3. 필터 객체를 key 에 포함

`reservations.filtered({ page, status, search, ... })` — React Query 는 deep equality 로 key 비교. 객체 reference 가 달라도 내용 같으면 같은 key.

**근거**:
- 필터 6개 + page 를 따로 key 에 넣으면 시그니처 폭발
- 객체 하나로 묶으면 호출 깔끔 + 타입 명시 (interface)
- staleTime 30s 이내 같은 필터 재방문 시 캐시 hit

**잠재 위험**: 객체 내 키 순서 다를 수 있음 → React Query 가 stable 하게 처리하는지 검증 필요. → 공식 문서: queryKey 객체는 stringify 시 key 순서 정규화 → 문제 없음.

### 3-4. `templateSchedules.customTypes()` 만 tenantId 미포함

```ts
customTypes: () => ['templateSchedules', 'customTypes'] as const, // tenant-agnostic
```

**근거**: customTypes 는 시스템 전체 상수 (surcharge_standard, party3_today_mms, room_upgrade_*) — tenant 별 데이터 아님. 한 번 fetch 후 전 tenant 공유.

**검증**: `backend/app/api/template_schedules.py` 의 `get_custom_types` 엔드포인트가 tenant 무관 응답하는지 확인 (Step #7 사전조사에서 정밀 검증). 현재 step 에서는 선언만 → 사용 안 함.

### 3-5. PartyCheckin `guests(date, section)` — section 도 key 에 포함

stable / unstable 두 호출이 다른 데이터 반환 (`PartyCheckin.tsx:225-226`):
```ts
partyCheckinAPI.getList(date, 'stable'),
hasUnstable ? partyCheckinAPI.getList(date, 'unstable') : ...
```

→ section 도 key 에 포함해야 캐시 격리.

### 3-6. `all()` 함수의 prefix 매칭 활용

`queryKeys.reservations.all() = ['reservations', tid]` 와 `queryKeys.reservations.list(date) = ['reservations', tid, date]` 가 같은 prefix → `invalidateQueries({ queryKey: queryKeys.reservations.all() })` 가 둘 다 invalidate.

→ Step #5 (Reservations) 에서 mutation 후 `reservations.all()` 호출로 모든 페이지/필터 일괄 무효화 가능.

---

## 4. 동작 동등성 근거

본 단계의 변경: **신규 함수 선언 추가, 어디서도 호출 안 함**.

### 4-1. 정적 분석 기반 동등성

| 검증 항목 | 검증 방법 | 기대 결과 |
|----------|----------|----------|
| 기존 호출처 영향 | `grep -rnE "queryKeys\." frontend/src/ --include="*.ts" --include="*.tsx" \| wc -l` 변경 전후 비교 | 동일 (사용 안 늘어남) |
| 신규 key 사용 0 | `grep -rnE "queryKeys\.(dashboard\|activityLogs\|salesReport\|partyHosts\|templateSchedules\|buildings\|partyCheckin)" frontend/src/ \| wc -l` | 0 |
| TypeScript 타입 오류 | `cd frontend && npx tsc --noEmit` | 에러 0 (신규 interface 추가만) |
| Lint | `cd frontend && npm run lint` | 변경 전과 동일 |

### 4-2. 런타임 동등성

- `queryKeys` 객체 export 가 늘어나지만, 어떤 컴포넌트도 신규 키를 import/호출 안 함
- React Query 의 query cache 에 새 key 가 생성되지 않음 (호출처 없으니)
- 모든 페이지의 useEffect / useState / fetch 흐름 동일

### 4-3. 케이스별 비교

| 시나리오 | Before | After | 판정 |
|---------|--------|-------|------|
| RoomAssignment 페이지 로드 | `useReservationsData` 5개 useQuery 정상 동작 | 동일 (사용 함수 변경 없음) | ✅ |
| Dashboard 페이지 로드 | useEffect+useState 패턴 | 동일 (아직 useQuery 안 씀) | ✅ |
| 테넌트 전환 | reload → 모든 컴포넌트 재시작 | 동일 | ✅ |
| `vite build` | 성공 | 성공 (신규 export 만 추가) | ✅ |
| 번들 크기 | 기준선 | +~1KB (50줄 추가, 트리쉐이킹으로 사용 안 한 것만 최소화) | ⚪ |

---

## 5. 영향받지 않음을 확인할 코드 경로

다음 영역은 본 단계에서 **1 byte 도 변경되지 않으며 동작 변화 없음**:

```
frontend/src/lib/queryClient.ts         # staleTime/gcTime 설정 동일
frontend/src/services/api.ts            # axios 인터셉터 동일
frontend/src/stores/tenant-store.ts     # currentTenantId 동작 동일
frontend/src/components/Layout.tsx      # 테넌트 전환 reload 동일
frontend/src/main.tsx                   # QueryClientProvider 설정 동일
frontend/src/pages/                     # 모든 페이지 (RoomAssignment 포함) 코드 변경 0
frontend/src/pages/RoomAssignment/      # 모든 훅 (useReservationsData 등) 변경 0
backend/                                # 변경 0 (frontend 전용)
```

검증: `git diff main -- frontend/src/ backend/` 결과 = queryKeys.ts 한 파일 + ~50 lines 추가.

---

## 6. 검증 체크리스트

PR 작성 시 모두 ✅:

- [ ] **TypeScript syntax/타입**: `cd frontend && npx tsc --noEmit` 에러 0
- [ ] **lint**: `cd frontend && npm run lint` 변경 전과 동일
- [ ] **build**: `cd frontend && npm run build` 성공
- [ ] **diff 정확성**: `git diff main -- frontend/` 결과 = queryKeys.ts 한 파일만, ~50 lines 추가
- [ ] **외부 영향 0**: `git diff main -- frontend/src/pages/ frontend/src/services/ frontend/src/stores/ frontend/src/components/ backend/` 결과 = 0
- [ ] **기존 호출처 시그니처 호환**: 기존 5개 함수 (`reservations.list/all`, `rooms.list/groups`, `templates.labels`, `settings.highlightColors`) 시그니처 + return 형식 동일
- [ ] **신규 key 사용 0**: `grep -rnE "queryKeys\.(dashboard|activityLogs|salesReport|partyHosts|templateSchedules|buildings|partyCheckin)" frontend/src/` 결과 0건

---

## 7. 잠재 사이드이펙트 검토

### 7-1. TypeScript `as const` literal type

`as const` 어설션이 readonly tuple 로 narrow type 만듦. React Query 의 `queryKey` 타입 (`readonly unknown[]`) 과 호환.

- **검증**: 기존 코드가 이미 `as const` 패턴 사용 중 → 신규도 동일 패턴이라 자동 호환.

### 7-2. React Query partial match 동작

`invalidateQueries({ queryKey: ['reservations'] })` 가 prefix 매칭으로 동작:
- 기존 `templates.labels = ['templates', 'labels', tid]` 패턴 (subkey 가 tid 앞)
- 신규 `templates.list = ['templates', tid, 'list']` 패턴 (tid 가 subkey 앞)

→ 만약 `invalidateQueries({ queryKey: ['templates'] })` 호출하면 두 패턴 모두 무효화. 의도된 동작 (templates 카테고리 전체 invalidate).

→ 만약 `invalidateQueries({ queryKey: ['templates', 'labels'] })` 호출하면 기존만 잡힘. **그러나 본 step 시점에 이 호출 안 함** — 후속 step 에서 정확한 key 사용.

**판정**: 본 step 단독으로는 영향 없음.

### 7-3. 번들 크기

50 lines 추가 = ~1.5KB raw, gzip 후 ~0.5KB. 무시 가능.

### 7-4. dev server hot reload

queryKeys.ts 가 사용되는 모든 컴포넌트가 HMR 재평가됨. 단, 본 step 의 변경은 신규 export 추가뿐 → 기존 호출처는 import 만 같으면 동일 동작.

---

## 8. 후속 의존성

본 단계가 머지된 후 진행 가능한 후속 단계:

- **Step #2 (Dashboard)**: `queryKeys.dashboard.schedules()`, `queryKeys.dashboard.stats()` 사용
- **Step #3 (ActivityLogs)**: `queryKeys.activityLogs.list(filters)`, `queryKeys.activityLogs.stats()`
- **Step #4 (SalesReport)**: `queryKeys.salesReport.report(dateFrom, dateTo)`, `queryKeys.partyHosts.list()`
- **Step #5 (Reservations)**: `queryKeys.reservations.filtered(filters)`, 기존 `reservations.all()` 활용
- **Step #6a/b (RoomSettings)**: `queryKeys.rooms.listWithInactive()`, `queryKeys.rooms.bizItems()`, `queryKeys.buildings.list()`
- **Step #7 (Templates)**: `queryKeys.templates.list()`, `queryKeys.templates.variables()`, `queryKeys.templateSchedules.*`
- **Step #8 (PartyCheckin)**: `queryKeys.partyCheckin.*` 6개

본 step 단독으로는 의도된 동작 변화 없음. 모든 UX 개선은 후속 step 에서 발생.

---

## 9. 머지 후 다음 액션

1. 본 PR (Step #1) 머지 → 운영 자동 배포 (단, 사용자 가시 동작 변화 0 — 안전)
2. Step #2 (Dashboard) 사전조사 (`react-query-step-02-dashboard.md`) 작성
3. Step #2 검토 → 코드 → 머지 (본보기 step)
4. Step #3~#8 순차 진행
