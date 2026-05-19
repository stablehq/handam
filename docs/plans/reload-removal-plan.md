# Reload 제거 — 사전조사 + 단계 분해

> 작성일: 2026-05-19
> 분류: 🔵 의도된 UX 개선 (캐시 보존 + form 보존 + 깜빡임 제거)
> 변경 규모: 7개 파일, ~10 lines 변경
> 선행: React Query 통일 (Step #1~#8 + cardEditing fix) 머지됨

---

## 1. 목적

테넌트 전환 시 `window.location.reload()` 제거 → SPA 라우터/form/모달 상태 보존하며 부드럽게 전환.

### 다루는 것

- `tenant-store.ts`: `setCurrentTenantId` setter 추가
- `Layout.tsx`: `handleSelect` 에서 reload 제거 → store update + `queryClient.clear()`
- 5개 페이지: `useTenantStore` 구독 1줄 추가 (cross-tenant 캐시 오염 방지)
  - Dashboard, ActivityLogs, SalesReport, Reservations, RoomSettings

### 다루지 않는 것

- queryKeys.ts (그대로 — `localStorage` 직접 읽음, store update 후 동기 일치 보장)
- axios 인터셉터 (그대로 — 매 요청 `localStorage` 읽음, 일관성 자동)
- 8개 페이지의 useQuery/useMutation 로직 (그대로)
- 백엔드 (변경 0)

---

## 2. 변경 대상 코드 (라인 단위)

### 2-1. `frontend/src/stores/tenant-store.ts` — setter 추가

**Before** (interface + create):
```ts
interface TenantState {
  tenants: Tenant[]
  currentTenantId: string | null
  loadTenants: () => Promise<void>
}

export const useTenantStore = create<TenantState>((set) => ({
  tenants: [],
  currentTenantId: localStorage.getItem(TENANT_KEY),
  loadTenants: async () => { ... },
}))
```

**After**:
```ts
interface TenantState {
  tenants: Tenant[]
  currentTenantId: string | null
  loadTenants: () => Promise<void>
  setCurrentTenantId: (tenantId: string) => void  // 신규
}

export const useTenantStore = create<TenantState>((set) => ({
  tenants: [],
  currentTenantId: localStorage.getItem(TENANT_KEY),
  loadTenants: async () => { ... },
  setCurrentTenantId: (tenantId) => {
    localStorage.setItem(TENANT_KEY, tenantId)  // localStorage 동기 보장
    set({ currentTenantId: tenantId })
  },
}))
```

**근거**: setter 가 store + localStorage 동시 업데이트 → axios 인터셉터(localStorage 읽음) + queryKeys getTenantId(localStorage 읽음) 자동 일치.

### 2-2. `frontend/src/components/Layout.tsx:158-162` — reload 제거

**Before**:
```tsx
function TenantSwitcher({ collapsed = false }: ...) {
  const { tenants, currentTenantId } = useTenantStore()
  ...
  const handleSelect = (tenantId: number) => {
    localStorage.setItem('sms-tenant-id', String(tenantId))
    setOpen(false)
    window.location.reload()
  }
```

**After**:
```tsx
function TenantSwitcher({ collapsed = false }: ...) {
  const { tenants, currentTenantId, setCurrentTenantId } = useTenantStore()
  const qc = useQueryClient()
  ...
  const handleSelect = (tenantId: number) => {
    setCurrentTenantId(String(tenantId))  // store + localStorage 동시
    qc.clear()                              // 모든 React Query 캐시 삭제 → 옛 tenant 데이터 안 남음
    setOpen(false)
    // reload 제거됨
  }
```

**import 추가**: `import { useQueryClient } from '@tanstack/react-query'`

### 2-3. 5개 페이지 — `useTenantStore` dummy 구독

각 페이지 컴포넌트 본문 최상단에 1줄 추가:

```tsx
// 테넌트 전환 시 컴포넌트 리렌더 보장 → queryKey 재생성 → cross-tenant 캐시 오염 방지
useTenantStore(s => s.currentTenantId)
```

**파일**:
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/ActivityLogs.tsx`
- `frontend/src/pages/SalesReport.tsx`
- `frontend/src/pages/Reservations.tsx`
- `frontend/src/pages/RoomSettings.tsx`

**import 추가**: `import { useTenantStore } from '@/stores/tenant-store'`

이미 구독하는 3개 페이지 (RoomAssignment, PartyCheckin, Templates) 는 변경 0.

---

## 3. 동작 동등성 / 의도된 변화 — 시나리오 매트릭스

⚪ = 변화 없음 / 🔵 = 의도된 UX 개선 / 🔴 = 회귀 위험 (해결됨).

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 한담 로그인 → SalesReport → 스테이블 전환 | 페이지 전체 reload → SalesReport 다시 마운트 → 스테이블 데이터 fetch | qc.clear() + store update → 5 페이지 리렌더 → 새 queryKey → 스테이블 데이터 fetch | 🔵 깜빡임 제거 |
| 2 | 사용자 SalesReport 에서 기간 picker 입력 중 → 스테이블 전환 | reload → 입력 사라짐 | 입력 보존 (단 다른 tenant 컨텍스트라 사용자가 혼란 가능) | 🔵 + 주의 (§4-1) |
| 3 | URL `/sales-report` 에서 전환 | reload → URL 보존 (히스토리에 새 entry 없음) | 그대로 | ⚪ |
| 4 | React Query devtools 세션 | reload → devtools 재시작 | 보존 | 🔵 |
| 5 | Sentry 세션 | reload → 새 세션 | 보존 (같은 사용자 흐름 추적) | 🔵 |
| 6 | 새 페이지 진입 (캐시 비어있음) | 매번 fresh fetch (캐시 reload 로 다 날아감) | 동일 (qc.clear 했으니 비어있음) | ⚪ |
| 7 | 같은 페이지 재진입 (30s 이내) | 매번 reload → fresh fetch | 캐시 hit (qc.clear 후엔 비어있지만 그 후 fetch 한 데이터는 staleTime 동안 보존) | 🔵 |
| 8 | 5 페이지 중 한 곳 (예: Dashboard) 에서 전환 | reload | Dashboard 가 useTenantStore 구독 → 리렌더 → 새 queryKey + fresh fetch | ⚪ |
| 9 | Dashboard 구독 누락 시 가정 (이번에 추가 안 함) | reload 가 막아줌 | 옛 queryKey 로 새 tenant 응답 저장 → cross-tenant 오염 | 🔴 (5 페이지 구독 추가로 해결) |
| 10 | tenant 전환 후 즉시 다른 페이지 이동 | reload 후 새 페이지 마운트 → fetch | store 업데이트 후 라우터 이동 → fetch (모두 새 tenant) | ⚪ |
| 11 | 동시 mutation 진행 중 전환 | mutation 진행 중 reload — mutation cancel | qc.clear() — 진행 중 query/mutation 영향 (확인 §4-3) | 🟡 |
| 12 | refetchOnWindowFocus 발화 직후 전환 | reload | qc.clear → 새 queryKey 로 refetch | ⚪ |
| 13 | RoomAssignment 의 useReservationsData 5 useQuery — Optimistic mutation 진행 중 전환 | reload — 데이터 손실 가능 (서버 응답 못 받음) | qc.clear → optimistic update 도 cancel | 🟡 (mutation race) |
| 14 | API 호출 race (전환 직전 보낸 요청 + 전환 후 응답 도착) | reload — 응답 무시됨 | axios 인터셉터 매 요청마다 localStorage 읽음 → 전환 직전 요청은 옛 헤더, 응답도 옛 tenant 데이터 → 옛 queryKey 캐시에 저장? — qc.clear 후 → cache 비어있음 → React Query 가 그 응답으로 새 cache entry 생성? | ⚠️ 위험 (§4-2) |

### 3-1. 잠재 사이드이펙트

**⚠️ 후보 1 (시나리오 2): form 입력 보존이 다른 tenant 컨텍스트와 충돌**
- 사용자가 한담에서 매출 입력 중 → 스테이블 전환 → 입력 보존 → "이건 어느 tenant 매출이지?" 혼란
- 의도된 동작이지만 UX 미세 조정 필요할 수 있음
- 본 step 에선 보존 채택 (사용자 명시적 요구 없으면 입력 유지). 미세 조정은 별도.

**⚠️ 후보 2 (시나리오 14): 전환 직전/직후 API race**
- 사용자가 mutation/query 진행 중 전환 → 응답 도착 시점에 store 는 이미 새 tenant
- 위험: 옛 tenant 요청의 응답이 새 tenant queryKey 에 저장
- React Query 동작: qc.clear() 가 진행 중 query 도 cancel? — 공식 문서 확인 필요
  - `queryClient.clear()` 는 cache 만 삭제. 진행 중 fetch 는 계속.
  - 응답 도착 시 → 현재 active query 에 저장. active query 의 queryKey 가 새 tenant 면 새 cache entry 에 옛 tenant 응답 저장 → 오염!
- **해결**: `qc.clear()` 전에 `qc.cancelQueries()` 호출
  ```ts
  await qc.cancelQueries()  // 진행 중 fetch 모두 cancel
  qc.clear()                 // cache 삭제
  ```
- 단 cancelQueries 가 async — handleSelect 가 async 되어야. setOpen(false) 도 await 후.

**⚠️ 후보 3 (시나리오 11, 13): Optimistic mutation 진행 중 전환**
- onMutate 가 setQueryData (옛 tenant 캐시)
- 전환 → qc.clear() → 캐시 삭제
- mutationFn 도착 → onSuccess setQueryData → 새 cache entry (옛 데이터)
- 또는 onError ctx.previous 로 옛 캐시 복원 → 새 cache 에 옛 데이터 ← 오염
- **해결**: cancelQueries 처럼 active mutation 도 처리 필요? — React Query 의 mutation cancel API 제한적. 일반적으로 mutation 은 끝까지 진행.
- 실용적 해결: 사용자에게 "전환 전 작업 완료 또는 취소 권장" — UI 가이드 없음. 다만 매우 드문 케이스.
- 본 step 에서 cancelQueries() 만 도입. mutation race 는 별도 검토.

**⚠️ 후보 4: setOpen(false) 호출 시점**
- Before: localStorage.setItem 후 setOpen → reload (reload 가 모든 걸 끝냄)
- After: setCurrentTenantId 후 qc.cancelQueries (async) → qc.clear → setOpen
- async/await 추가. 단순.

---

## 4. queryClient.clear() vs invalidateQueries 선택 근거

- **clear()**: 모든 cache entry 삭제. 다음 useQuery 호출 시 fresh fetch.
- **invalidateQueries()**: 모든 query 를 stale 표시. active query 자동 refetch (queryKey 동일).

본 step: **clear() 채택**.

근거:
- 사용자가 transient 하게 한 tenant 데이터 잠시 보일 위험 회피
- invalidateQueries 는 옛 queryKey 그대로 → 컴포넌트 리렌더 안 되면 옛 queryKey 그대로 fetch → 같은 위험
- clear 는 cache 자체 삭제 → 다음 useQuery 가 cache miss → 새 queryKey (컴포넌트 리렌더 후) 로 fetch

---

## 5. 영향받지 않음 경로

```
backend/                                # 변경 0
frontend/src/lib/queryClient.ts         # 동일
frontend/src/lib/queryKeys.ts           # 동일 (localStorage 직접 읽음, store update 후 동기 일치)
frontend/src/services/api.ts            # axios 인터셉터 동일
frontend/src/hooks/useDebouncedValue.ts # 동일
frontend/src/pages/RoomAssignment.tsx   # 이미 useTenantStore 구독 (변경 0)
frontend/src/pages/PartyCheckin.tsx     # 동일 (변경 0)
frontend/src/pages/Templates.tsx        # 동일 (변경 0)
frontend/src/pages/Settings.tsx         # 동일 (변경 0)
frontend/src/main.tsx                   # QueryClientProvider 그대로
```

검증: `git diff main -- frontend/ backend/` = 7개 파일 (tenant-store + Layout + 5 페이지).

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] 7개 파일 외 변경 0
- [ ] 5개 페이지에 `useTenantStore(s => s.currentTenantId)` 1줄 추가 확인
- [ ] 수동 검증 (배포 후):
  - [ ] 한담 → 스테이블 전환 시 깜빡임 0
  - [ ] URL 보존 (`/sales-report` 에서 전환 → `/sales-report` 그대로)
  - [ ] Dashboard 에서 전환 → 통계가 스테이블 데이터로 변경
  - [ ] ActivityLogs 에서 전환 → logs 가 스테이블
  - [ ] SalesReport 에서 전환 → 매출 + 진행자가 스테이블 (cross-tenant 사고 재현 안 됨)
  - [ ] Reservations 에서 전환 → 예약 목록이 스테이블
  - [ ] RoomSettings 에서 전환 → 객실 목록이 스테이블
  - [ ] RoomAssignment / PartyCheckin / Templates 에서 전환 → 정상 (기존 구독)
  - [ ] form 입력 중 전환 → 입력 보존 (단 새 tenant 컨텍스트 인지 필요)
  - [ ] 빠른 mutation 진행 중 전환 — mutation race 없는지 (드문 케이스)

---

## 7. 단계 분해

본 작업은 변경량 작아서 **단일 PR** 권장 (3개 substep 통합):

| Substep | 변경 | 동작 변화 |
|---------|------|----------|
| 1. tenant-store.ts setter | 신규 함수 추가 | ⚪ 호출처 0 |
| 2. 5 페이지 dummy 구독 | 1줄씩 추가 | ⚪ 컴포넌트 리렌더 trigger 만 추가 (현재는 reload 가 처리) |
| 3. Layout reload 제거 | reload → setCurrentTenantId + qc.cancelQueries + qc.clear | 🔵 의도된 변화 발효 |

**롤백**: 단일 PR revert 로 reload 복원. 안전.

---

## 8. 결정 사항

- [x] **clear() 채택** (invalidateQueries 보다 안전)
- [x] **cancelQueries + clear 조합** — 전환 직전 API race 회피
- [x] **5 페이지 dummy 구독** — cross-tenant 캐시 오염 방지
- [x] **form state 보존** — 사용자 요구 시 보존 (의도)
- [x] **단일 PR** (3 substep 통합) — 변경량 작아서 분리 의미 적음
- [ ] **mutation race (시나리오 11/13)** — 별도 검토 (사용자 가이드 또는 mutation cancel 메커니즘)
- [ ] **lint 회귀 방지** — useQuery 사용 컴포넌트의 useTenantStore 구독 의무 — 별도 step (선택)

---

## 9. 머지 후 다음 액션

1. 커밋 + push
2. 자동 배포 → 운영 검증
3. (선택) form state 보존 vs reset UX 결정
4. (선택) lint 회귀 방지 별도 step
