# React Query 통일 — 설계안

> 작성일: 2026-05-19
> 상태: 사용자 검토 대기
> 트리거: 2026-05-19 SalesReport cross-tenant leak 사고 진단 중 발견된 "옛 방식 페이지 다수 + reload 의존" 패턴
> 후속 단계 분해: [react-query-migration-plan.md](./react-query-migration-plan.md) (Phase 0e 산출물)

---

## 1. 배경

### 1-1. 사고 진단 중 부수 발견

2026-05-19 SalesReport 의 진행자명이 다른 테넌트 데이터로 표시되는 사고를 진단하던 중, 5개 페이지가 `useEffect + useState + 직접 fetch` 옛 패턴을 사용하고 있고 `useTenantStore` 를 구독하지 않음을 발견.

처음 가설: "테넌트 전환 시 자동 refetch 가 안 일어남 → 회귀". 그러나 실제 분석 결과:

- 진단 결과 사고 원인은 별개 (`OnsiteFemaleInvite` 등록 누락, 별도 fix 완료 — 커밋 `bc9fdcb`)
- 옛 패턴 페이지들도 `Layout.tsx:158-162` 의 `window.location.reload()` 강제 새로고침 덕분에 **사실상 정상 동작**
- 즉 "회귀" 가 아니라 "UX 가 거친 패턴"

### 1-2. 본 작업의 진짜 가치

회귀 해결이 아니라 **UX + 성능 + 일관성 개선**:

| 항목 | 현재 | 통일 후 |
|------|------|--------|
| 테넌트 전환 | 페이지 깜빡 + 모든 데이터 새 로드 (≈1초 멍) | 캐시 활용 + 부드러운 전환 가능 (단계적으로 reload 제거) |
| 페이지 재방문 | 매번 서버 호출 | staleTime 내엔 캐시 즉시 표시 (체감 0초) |
| Mutation 후 화면 갱신 | 수동 새로고침 또는 직접 refetch 호출 | `invalidateQueries` 1줄 → 관련 모든 화면 자동 갱신 |
| 코드 일관성 | 페이지마다 fetch 패턴 다름 | 동일 훅 패턴 (학습/유지 비용 ↓) |
| Optimistic UI | 불가 (수동 구현 필요) | 표준 패턴으로 가능 |

---

## 2. 현재 상태 (라인 단위 분석 완료)

### 2-1. 인프라 (`frontend/src/lib/`, `services/`, `stores/`)

| 파일 | 라인 | 핵심 |
|------|------|------|
| `lib/queryClient.ts` | 17 | staleTime 30s 기본, gcTime 5min, retry 1, refetchOnWindowFocus true, refetchOnMount true, mutation retry 0 |
| `lib/queryKeys.ts` | 20 | `getTenantId()` 가 호출 시점에 `localStorage.getItem('sms-tenant-id')` → queryKey 에 tenantId 자동 포함. 현재 4 카테고리만 (`reservations`, `rooms`, `templates`, `settings`) |
| `services/api.ts:23-36` | — | axios 인터셉터 — `Authorization` + `X-Tenant-Id` 헤더 자동 주입 |
| `stores/tenant-store.ts` | 60 | `currentTenantId: string \| null` (초기 = localStorage). **setter 없음** — 변경은 `localStorage.setItem` + `reload()` |
| `components/Layout.tsx:158-162` | — | 테넌트 드롭다운 선택 시 `localStorage.setItem` + `window.location.reload()` |
| `main.tsx:51-57` | — | `<QueryClientProvider client={queryClient}>` Provider 정상 설정. ReactQueryDevtools 포함 |

### 2-2. React Query 모범사례 페이지 (이미 잘 작동, 변경 없음)

| 페이지 | 모범사례 훅 위치 |
|--------|------------------|
| `RoomAssignment.tsx` | `RoomAssignment/hooks/useReservationsData.ts` (313줄) + `useStayGroup.ts` 등 다수 훅 |
| `Settings.tsx` | 마운트/버튼 클릭 시 명시 재조회 (간단 패턴) |

### 2-3. 옛 방식 페이지 (마이그레이션 대상 7개)

| 페이지 | 라인 | useState | API endpoint | Mutation | 복잡도 | useTenantStore | useQuery |
|--------|------|----------|-------------|----------|--------|----------------|----------|
| **Dashboard** | 314 | 4 | 2 GET | 없음 | 🟢 단순 | ❌ | ❌ |
| **ActivityLogs** | 690 | 13 | 2 GET + 검색 debounce | 없음 | 🟡 중간 | ❌ | ❌ |
| **SalesReport** | 581 | 11 | 3 (sales-report GET + partyHosts CRUD) | 3개 | 🟡 중간 | ❌ | ❌ |
| **PartyCheckin** | 980 | 31 | 8 (partyCheckin/onsiteSales/dailyHost/onsiteAuction/partyHosts/dailyReview/onsiteFemaleInvite/reservations) | 다수 | 🟠 무거움 | ✅ (hasUnstable 만) | ❌ |
| **Reservations** | 822 | 17 | 5 (getAll/syncNaver/update/create/delete) + 페이지네이션 + 필터 6개 | 4개 | 🟠 무거움 | ❌ | ❌ |
| **Templates** | 2522 | 64 | 다수 (templates/schedules/buildings/reservations CRUD) | 다수 | 🔴 매우 무거움 | ✅ (hasUnstable 만) | ❌ |
| **RoomSettings** | 1427 | 27 | 다수 (rooms/buildings/biz_items/grades CRUD + reorder) + 4 모달 | 다수 | 🔴 매우 무거움 | ❌ | ❌ |

**공통 사실**: 7개 모두 `useEffect + useState + 직접 await api.xxx()` 패턴. `useQuery`/`useMutation` 미사용. (PartyCheckin / Templates 의 `useTenantStore` 사용은 `hasUnstable` 추출용 — 데이터 fetch 트리거에는 관여 안 함)

---

## 3. 표준 패턴 (Phase 0a 에서 추출, RoomAssignment 모범사례 기반)

### 3-1. useQuery 표준

```ts
const fooQuery = useQuery<FooType[]>({
  queryKey: queryKeys.<category>.<method>(args),   // tenantId 자동 포함
  queryFn: () => fooAPI.list(params).then(r => r.data),
  staleTime: 30_000,                                // 카테고리별 차별 (§3-4 참조)
});
const foo: FooType[] = fooQuery.data ?? [];         // safe default unwrap
const loading = fooQuery.isFetching;                // 기존 setLoading 호환
```

### 3-2. Mutation — Simple 패턴 (기본)

단순 CRUD (UX 가 즉시 반응할 필요 없는 경우):

```ts
const fooMutation = useMutation({
  mutationFn: (vars) => fooAPI.create(vars),
  onSuccess: () => {
    toast.success('생성 완료');
    qc.invalidateQueries({ queryKey: queryKeys.foo.list() });
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail || '생성 실패'),
});
```

### 3-3. Mutation — Optimistic 패턴 (UX 중요한 경우만)

드래그/실시간 상태 토글 등 즉시 반응 필요한 경우:

```ts
const fooMutation = useMutation({
  mutationFn: ...,
  onMutate: async (vars) => {
    await qc.cancelQueries({ queryKey: ... });        // 진행 query 취소
    const previous = qc.getQueryData(...);             // 백업
    qc.setQueryData(..., (prev) => updateFn);          // 즉시 UI
    return { previous };
  },
  onError: (_, __, ctx) => {
    if (ctx?.previous) qc.setQueryData(..., ctx.previous);
    toast.error('실패 — 원복됨');
  },
  onSettled: () => qc.invalidateQueries({ queryKey: ... }),  // 서버 sync
});
```

### 3-4. staleTime 규약

| 카테고리 | staleTime | 근거 |
|---------|-----------|------|
| 자주 바뀌는 데이터 (예약, 칩, 메시지, 활동 로그) | **30s** | 사용자 작업 직후 fresh 보장 |
| 마스터 데이터 (객실, 건물, 템플릿 메타) | **300s (5min)** | 거의 안 바뀜, 캐시 적극 활용 |
| 사용자 입력 즉시 반영 데이터 (대시보드 통계) | **30s** | 작업 후 빨리 갱신 |
| 시간 의존 데이터 (오늘 일정) | **0s 또는 60s** | 정확성 우선 |

### 3-5. Invalidation 규약

| 시나리오 | 범위 | 예시 |
|---------|------|------|
| Narrow (가능하면 우선) | 변경된 정확한 query key만 | `qc.invalidateQueries({ queryKey: queryKeys.reservations.list(date) })` |
| Broad (관련 페이지가 여러 곳일 때) | category 전체 | `qc.invalidateQueries({ queryKey: queryKeys.reservations.all() })` |
| Cross-category (한 mutation 이 여러 카테고리 영향) | 여러 카테고리 명시적 invalidate | 객실 변경 → `rooms.list()` + `reservations.all()` |

### 3-6. queryKey 규약

**현재** (`queryKeys.ts:5-20`):
```ts
export const queryKeys = {
  reservations: { list: (date), all: () },
  rooms: { list: (), groups: () },
  templates: { labels: () },
  settings: { highlightColors: () },
}
```

**확장 후 추가될 카테고리** (Phase 0e 단계 #1 인프라):
```ts
{
  dashboard: { schedules: (), stats: () },
  activityLogs: { list: (filters), stats: () },
  salesReport: { report: (dateFrom, dateTo) },
  partyHosts: { list: () },
  partyCheckin: { guests: (date, section?), sales: (date), host: (date), auction: (date), review: (date), invites: (date) },
  reservations: { ...기존, list: (filters), search: (query) },
  rooms: { ...기존, list: (includeInactive), bizItems: () },
  buildings: { list: () },
  templates: { ...기존, list: (), schedules: (), variables: () },
}
```

**원칙**:
- 모든 key 함수가 `getTenantId()` 자동 포함 (현재 패턴 유지)
- 파라미터가 있으면 key 마지막에 포함 (`list: (date) => ['reservations', tid, date]`)
- `all()` 함수 — broad invalidation 용

---

## 4. 원칙 (mutator 식)

1. **기존 의도된 동작 보존** — 어떤 페이지도 마이그레이션으로 인해 사용자 가시 동작이 바뀌지 않아야 함 (단, "테넌트 전환 시 페이지 깜빡임" 같은 UX 개선은 의도된 변화로 허용 — 단계 내 명시)
2. **각 페이지는 별도 PR + 별도 사전조사 문서** — `react-query-step-NN-<page>.md` 형식
3. **각 사전조사 문서에 Before/After 라인 단위 + 동작 동등성 근거 + 코너케이스 매트릭스 명시**
4. **각 단계는 직전 단계와 독립** — 단계 #N 롤백해도 시스템 동작 (단, 인프라 step #1 은 모든 후속에 깔림 — 의존성 명시)
5. **백엔드 코드 변경 0** — 본 작업 범위는 frontend 전용. 백엔드 변경이 필요한 회귀 발견 시 별도 작업으로 분리

---

## 5. 의도된 동작 변화 (= 해결 대상)

| # | 시나리오 | 현재 동작 | 통일 후 동작 | 분류 |
|---|---------|----------|------------|------|
| 1 | 같은 페이지 재방문 (30초 이내) | 매번 서버 호출 | 캐시에서 즉시 표시 | 🔵 성능 개선 |
| 2 | Mutation 후 관련 화면 갱신 | 수동 새로고침 또는 직접 refetch 호출 | `invalidate` 1줄 → 자동 갱신 | 🔵 UX 개선 |
| 3 | 페이지마다 다른 fetch 패턴 | 학습 비용 + 유지 비용 | 동일 훅 패턴 | 🔵 일관성 |
| 4 | 옛 방식 페이지의 useEffect deps 회귀 | reload 덕분에 동작 (but 위태로움) | queryKey 자동 의존 (회귀 영구 차단) | 🔵 안정성 |

### 의도되지 *않은* 동작 변화 (회피 대상)

| 시나리오 | 회피 방법 |
|---------|----------|
| 응답 schema 변경으로 인한 화면 깨짐 | API 호출 자체는 그대로 유지 (단지 useState→useQuery 래핑만) |
| 캐시 stale 로 인한 잘못된 데이터 표시 | staleTime 규약 (§3-4) 엄격 적용 + mutation 후 invalidation 누락 0건 |
| 로딩 인디케이터 사라짐 | `loading = isFetching` 매핑 (기존 `setLoading(true/false)` 와 의미 동일) |
| 에러 처리 변경 | 기존 `try/catch + toast` → `onError` 콜백으로 1:1 이전 |

---

## 6. 미결 검토 항목

다음 항목은 본 설계안 시점에 결정 보류, 각 step 사전조사에서 결정:

### 6-1. UX 결정 (사용자 확인 필요할 수 있음)

- [ ] **테넌트 전환 reload 제거 여부** — 통일 후 reload 없이 부드러운 전환 가능. 단 `setQueryClient` 강제 invalidate + tenant-store setter 추가 필요. 본 마이그레이션 범위에 포함 vs 후속 별도 PR? **본 설계안은 후속으로 미룸** — 페이지 통일 후 별도 PR 권장 (위험 분리)
- [ ] **Optimistic update 적용 범위** — Simple vs Optimistic mutation 결정. 본 설계안 기본: Simple (작업 단순). Optimistic 은 RoomAssignment 와 같은 드래그 UI 에만 적용.

### 6-2. 기술 결정 (각 step 사전조사에서 결정)

- [ ] **filters/pagination 의 queryKey 구조** — Reservations 의 필터 6개 + page → queryKey 폭발 우려. 객체 vs 배열 vs 단순 concat 결정.
- [ ] **검색 debounce 구현** — `useDebouncedValue` hook 사용 vs `useEffect + setTimeout` 패턴. ActivityLogs / Reservations 에서.
- [ ] **모달 데이터 fetch 시점** — `enabled: modalOpen` 옵션 사용 vs 모달 닫혀도 background fetch. RoomSettings / Templates.
- [ ] **DnD reorder optimistic** — RoomSettings 의 객실 reorder mutation. 즉시 반영 필요.
- [ ] **Cross-category invalidation** — 객실 변경 mutation 이 RoomAssignment 의 `queryKeys.rooms.list()` 까지 invalidate 해야 함. 누락 시 다른 페이지에서 stale.

### 6-3. 범위 결정

- [ ] **7개 페이지 외 더 있는지** — `frontend/src/pages/` 전수 점검 (이번 작업에서 빠뜨린 페이지 있는지)
- [ ] **CI lint 추가 여부** — 새 페이지가 옛 패턴(`useEffect+useState+await api`)으로 회귀 못 하게 lint rule. 본 설계안: 후속 별도 PR (`step-08-ci-lint.md`).

---

## 7. 비범위 (본 작업이 다루지 *않는* 것)

| 항목 | 사유 |
|------|------|
| 백엔드 API 변경 | frontend 전용 작업 |
| API 응답 schema 변경 | 호환성 위해 그대로 |
| 인증/권한 로직 | 별개 |
| Sentry / 로깅 패턴 | 별개 |
| 컴포넌트 디자인 변경 | 별개 |
| 테넌트 전환 reload 제거 | 후속 별도 PR (위험 분리) |
| 옛 회귀 사고 (cross-tenant leak) | 별도 fix 완료 (커밋 `bc9fdcb`) |

---

## 8. 작업량 추정

| 페이지 | 사전조사 | 코드 + 검증 | 합계 |
|--------|---------|------------|------|
| 인프라 (queryKeys 보강) | 30분 | 30분 | 1시간 |
| Dashboard | 30분 | 30분 | 1시간 |
| ActivityLogs | 1시간 | 1시간 | 2시간 |
| SalesReport | 1.5시간 | 1.5시간 | 3시간 |
| Reservations | 2시간 | 2시간 | 4시간 |
| RoomSettings (분할 가능) | 3시간 | 4시간 | 7시간 |
| Templates | 3시간 | 3시간 | 6시간 |
| PartyCheckin | 2시간 | 3시간 | 5시간 |
| **합계** | | | **29시간 ≈ 3.5~4일** |

**가장 무거운 페이지 3개 (RoomSettings, Templates, PartyCheckin) = 전체 작업량의 62%**. 분할 마이그레이션 고려 (단계 분해 §0e 에서 결정).

---

## 9. 다음 액션

1. 본 설계안 검토 합의
2. 단계 분해 계획 (`react-query-migration-plan.md`) 작성 — Phase 0e
3. Step #1 (인프라 queryKeys 보강) 사전조사 작성
4. 코드 변경 → 머지 → 다음 step
