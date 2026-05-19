# 단계 #3 사전조사 — ActivityLogs 페이지 React Query 마이그레이션

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #3"
> 분류: 🔵 의도된 동작 변화 (캐시/UX + 검색 debounce 단순화)
> 변경 규모: 2개 파일 (page + queryKeys 보강), 치환 ~70 lines + 신규 hook 1개
> 선행 단계: Step #1, #2 머지됨

---

## 1. 목적

`ActivityLogs.tsx` 의 다음 구조를 React Query 로 통일:
- `loadStats` (useCallback + useEffect)
- `loadLogs` (useCallback + useEffect, 필터/검색 deps)
- 검색 debounce (useState + useEffect + setTimeout)
- 페이지네이션 (page 도 queryKey 에 포함)

### 본 단계가 다루는 것

- `activityLogsAPI.getStats()` → `useQuery(queryKeys.activityLogs.stats())`
- `activityLogsAPI.getAll(params)` → `useQuery(queryKeys.activityLogs.list({...filters, page}))`
- 검색 debounce → 신규 `useDebouncedValue(value, ms)` hook
- pagination state (`page`, `hasMore`) → `page` 만 useState 유지, `hasMore` 는 query.data 에서 파생
- `Step #1` 의 `ActivityLogFilters` 에 `page` 추가 (보강)

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| `activityLogsAPI` 변경 (백엔드 응답) | 변경 0 |
| 페이지 UI/디자인 (StatCard / Table 등) | 변경 0 |
| Activity logs mutation (이 페이지는 read-only) | 해당 없음 |
| 다른 페이지 영향 | 별도 step (activityLogs 는 다른 페이지에서 안 씀) |

---

## 2. 변경 대상 코드

### 2-1. 신규 파일: `frontend/src/hooks/useDebouncedValue.ts`

**Before**: 부재.

**After** (전체):

```ts
import { useEffect, useState } from 'react';

/**
 * 입력값을 지정 시간만큼 지연시켜 반환. 빠른 타이핑 중 fetch thrash 회피.
 *
 * 사용 예:
 *   const debouncedSearch = useDebouncedValue(searchQuery, 300);
 *   useQuery({ queryKey: [..., debouncedSearch], ... });
 */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);

  return debounced;
}
```

**근거**: ActivityLogs 의 기존 `setTimeout + setDebouncedSearch + clearTimeout` 패턴을 hook 으로 추출. 후속 step (Reservations 의 searchQuery debounce, Templates 등) 에서도 재사용 가능.

### 2-2. `frontend/src/lib/queryKeys.ts` — ActivityLogFilters 보강

**Before** (Step #1 머지된 상태):
```ts
export interface ActivityLogFilters {
  type?: string;
  status?: string;
  date?: string;
  q?: string;
}
```

**After**:
```ts
export interface ActivityLogFilters {
  type?: string;
  status?: string;
  date?: string;
  q?: string;
  page?: number;       // 신규 — pagination 도 캐시 key 에 포함
  pageSize?: number;   // 신규 — PAGE_SIZE 변경 가능성 대비 (기본 20)
}
```

**변경 의도**: 페이지마다 별도 캐시 → 페이지 전환 시 React Query 자동 fetch + 같은 페이지 재방문 시 캐시 hit.

### 2-3. `frontend/src/pages/ActivityLogs.tsx` — import + 본문

**Before** (line 1-24):
```tsx
import React, { useEffect, useState, useCallback } from 'react'
...
import { activityLogsAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'
```

**After**:
```tsx
import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
...
import { activityLogsAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'
import { queryKeys } from '@/lib/queryKeys'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
```

### 2-4. `ActivityLogs.tsx` — state + fetch 부분 (line 117-204)

**Before** (88 lines):
```tsx
const ActivityLogs = () => {
  const [logs, setLogs] = useState<ActivityLog[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [stats, setStats] = useState<ActivityStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)

  // Filters
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterDate, setFilterDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // Pagination
  const [page, setPage] = useState(0)
  const [hasMore, setHasMore] = useState(true)

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const res = await activityLogsAPI.getStats()
      const d = res.data
      const s = d.stats || {}
      setStats({
        total_today: d.total_activities ?? 0,
        room_assign_today: s.room_assign?.count ?? 0,
        sms_sent_today: (s.sms_send?.count ?? 0) + (s.sms_manual?.count ?? 0),
        naver_sync_today: s.naver_sync?.count ?? 0,
      })
    } catch {
      setStats({ total_today: 0, room_assign_today: 0, sms_sent_today: 0, naver_sync_today: 0 })
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadLogs = useCallback(
    async (pageNum: number) => {
      setLoading(true)
      try {
        const params: Record<string, any> = {
          skip: pageNum * PAGE_SIZE,
          limit: PAGE_SIZE + 1,
        }
        if (filterType) params.type = filterType
        if (filterStatus) params.status = filterStatus
        if (filterDate) params.date = filterDate
        if (debouncedSearch.trim()) params.search = debouncedSearch.trim()

        const res = await activityLogsAPI.getAll(params)
        const data: ActivityLog[] = res.data ?? []
        setHasMore(data.length > PAGE_SIZE)
        setLogs(data.slice(0, PAGE_SIZE))
      } catch {
        setLogs([])
        setHasMore(false)
      } finally {
        setLoading(false)
      }
    },
    [filterType, filterStatus, filterDate, debouncedSearch],
  )

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

  useEffect(() => {
    setPage(0)
    loadLogs(0)
  }, [filterType, filterStatus, filterDate, loadLogs])

  const handlePageChange = (next: number) => {
    setPage(next)
    loadLogs(next)
  }
```

**After** (~40 lines):
```tsx
const DEFAULT_STATS: ActivityStats = {
  total_today: 0,
  room_assign_today: 0,
  sms_sent_today: 0,
  naver_sync_today: 0,
}

const ActivityLogs = () => {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // Filters
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterDate, setFilterDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const debouncedSearch = useDebouncedValue(searchQuery, 300)

  // Pagination — page 만 state, hasMore 는 query data 에서 파생
  const [page, setPage] = useState(0)

  // 필터 변경 시 page 자동 0 reset (Before 의 useEffect 가 처리하던 책임)
  // — 별도 useEffect 가 아닌, page reset 을 onChange handler 에서 처리하면 더 명시적이지만,
  //   기존과 동일하게 effect-style 유지를 위해 derived useEffect 1개 유지.
  useEffect(() => {
    setPage(0)
  }, [filterType, filterStatus, filterDate, debouncedSearch])

  const statsQuery = useQuery<ActivityStats>({
    queryKey: queryKeys.activityLogs.stats(),
    queryFn: async () => {
      const res = await activityLogsAPI.getStats()
      const d = res.data
      const s = d.stats || {}
      return {
        total_today: d.total_activities ?? 0,
        room_assign_today: s.room_assign?.count ?? 0,
        sms_sent_today: (s.sms_send?.count ?? 0) + (s.sms_manual?.count ?? 0),
        naver_sync_today: s.naver_sync?.count ?? 0,
      }
    },
    staleTime: 30_000,
  })

  const logsQuery = useQuery<ActivityLog[]>({
    queryKey: queryKeys.activityLogs.list({
      type: filterType || undefined,
      status: filterStatus || undefined,
      date: filterDate || undefined,
      q: debouncedSearch.trim() || undefined,
      page,
      pageSize: PAGE_SIZE,
    }),
    queryFn: async () => {
      const params: Record<string, any> = {
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE + 1,
      }
      if (filterType) params.type = filterType
      if (filterStatus) params.status = filterStatus
      if (filterDate) params.date = filterDate
      if (debouncedSearch.trim()) params.search = debouncedSearch.trim()
      const res = await activityLogsAPI.getAll(params)
      return res.data ?? []
    },
    staleTime: 30_000,
  })

  const stats = statsQuery.data ?? DEFAULT_STATS
  const statsLoading = statsQuery.isLoading
  const rawLogs = logsQuery.data ?? []
  const hasMore = rawLogs.length > PAGE_SIZE
  const logs = rawLogs.slice(0, PAGE_SIZE)
  const loading = logsQuery.isFetching  // 페이지 변경 / 필터 변경 시 indicator 유지

  // 사전조사 §4-3: error logging 패턴은 step #2 와 동일
  useEffect(() => {
    if (statsQuery.error) console.error('Failed to load activity stats:', statsQuery.error)
  }, [statsQuery.error])
  useEffect(() => {
    if (logsQuery.error) console.error('Failed to load activity logs:', logsQuery.error)
  }, [logsQuery.error])

  const handlePageChange = (next: number) => {
    setPage(next)
    // queryKey 의 page 변경 → React Query 자동 refetch
  }
```

**변경 의도**:
- `loadStats`/`loadLogs` useCallback 함수 제거 (queryFn 으로 흡수)
- 4개 useState 제거 (logs, stats, loading, statsLoading, debouncedSearch, hasMore)
- debounce useEffect → useDebouncedValue hook
- 필터 변경 시 page reset useEffect 는 1개 유지 (기존 책임 보존)
- `loading = isFetching` — Page 변경 시 깜빡임 유지 (기존 동작)
- `hasMore = rawLogs.length > PAGE_SIZE` — 파생값

### 2-5. JSX (line 205+) — 변경 0

`stats.total_today`, `logs.map`, `hasMore`, `loading`, `expandedId` 등 모든 참조 그대로.

---

## 3. queryKey 결정 — 라인 단위 근거

| API 호출 | queryKey | staleTime | 근거 |
|----------|----------|----------|------|
| `activityLogsAPI.getStats()` | `queryKeys.activityLogs.stats() = ['activityLogs', tid, 'stats']` | 30s | 통계 카드 |
| `activityLogsAPI.getAll(params)` | `queryKeys.activityLogs.list({type, status, date, q, page, pageSize}) = ['activityLogs', tid, 'list', {...}]` | 30s | 필터/페이지 조합마다 별도 캐시 |

**필터 객체 정규화**:
- 빈 문자열 (`filterType === ''`) 은 `undefined` 로 → queryKey 비교 시 일관성. 그래야 "필터 없음" 상태가 한 가지로 표현됨.
- React Query 의 deep equality 가 객체 key 정렬 정규화 → 순서 차이 안전.

**캐시 크기 제어**:
- 필터 7개 (type, status, date, q, page, pageSize) × 페이지 N 개 = 잠재 캐시 항목 다수
- gcTime 5min (queryClient 기본) → 5분 후 unused 캐시 GC
- staleTime 30s → fresh data 유지

---

## 4. 동작 동등성 / 의도된 변화 — 시나리오 매트릭스

⚪ / 🔵 / ⚠️ 분류.

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 (캐시 비어있음) | 두 fetch 병렬, statsLoading + loading skeleton | 동일 (두 useQuery 병렬 isLoading) | ⚪ |
| 2 | stats API 실패 | catch → `setStats({...0})` (default), statsLoading false | `statsQuery.error` → `stats = DEFAULT_STATS ?? data`. **현재 코드**: `statsQuery.data ?? DEFAULT_STATS` 가 fallback. 단 catch 안에서 setStats 한 거랑 default fallback 은 다름 — useQuery 의 error 상태에서 data 는 undefined → `?? DEFAULT_STATS` 동작 | ⚪ (의미 동등) |
| 3 | logs API 실패 | catch → setLogs([]) | `logsQuery.data === undefined → rawLogs = []` | ⚪ |
| 4 | 필터 type 변경 | useEffect 발화 → setPage(0) + loadLogs(0) | useEffect 발화 → setPage(0) → queryKey 의 page 변경 → 자동 refetch | ⚪ (책임 유지) |
| 5 | 검색어 키스트로크 (q 입력) | 300ms 후 debouncedSearch 갱신 → loadLogs 재생성 → useEffect 발화 → setPage(0) + loadLogs(0) | useDebouncedValue 300ms 후 갱신 → useEffect 발화 → setPage(0) → queryKey 변경 → refetch | ⚪ |
| 6 | 검색어 입력 중 (300ms 이내) | debounce 진행 중, 화면 그대로 (이전 결과 표시) | 동일 | ⚪ |
| 7 | 같은 필터 + 같은 page 재방문 (30s 이내) | useEffect 다시 발화 (loadLogs 동일 deps 라 발화 안 함, 단 컴포넌트 mount 시는 발화) | **캐시 hit, 즉시 표시 + background refetch (staleTime 지났으면)** | 🔵 의도 |
| 8 | 페이지 다음/이전 | handlePageChange → setPage + loadLogs(next) | handlePageChange → setPage → queryKey 변경 → refetch | ⚪ |
| 9 | 같은 페이지 재방문 (이전 페이지에서 돌아옴) | 매번 fetch | 캐시 hit | 🔵 의도 |
| 10 | 탭 전환 후 돌아옴 (refetchOnWindowFocus) | useEffect 발화 안 함 (focus 무관) | 자동 refetch (staleTime 지나면) | 🔵 의도 |
| 11 | 컴포넌트 unmount → 3분 후 재마운트 | 매번 fetch | gcTime 5min 이내 캐시 즉시 표시 | 🔵 의도 |
| 12 | 테넌트 전환 (Layout reload) | reload → 새 tenant fetch | reload → queryClient 초기화 → 새 tenant fetch | ⚪ |
| 13 | 필터 + 검색 동시 변경 | 두 useEffect 가 각각 발화 — 마지막에 loadLogs(0) 한 번 (loadLogs deps 변경되면 effect 한 번만) | useDebouncedValue 가 300ms 후 갱신 + 필터 즉시 변경 → setPage(0) effect 한 번 → queryKey 두 번 변경 가능 | ⚪~🟡 (debounce 동작 동등하지만 effect 발화 횟수 약간 다름 — 사용자 가시 영향 0) |
| 14 | 페이지 마운트 직후 unmount (빠른 이동) | useEffect cleanup 호출, 진행 중 fetch 결과 무시 (setState 가 unmounted 컴포넌트에 호출 — React warning) | React Query 가 cancelQueries 자동 처리 | 🔵 (warning 회피) |
| 15 | hasMore 동작 | data.length > PAGE_SIZE → setHasMore | `rawLogs.length > PAGE_SIZE` 파생 | ⚪ |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1**: 필터 변경 시 page reset effect (line 196)
- Before: `useEffect([filterType, filterStatus, filterDate, loadLogs])` — loadLogs 의 deps 에 debouncedSearch 포함 → debouncedSearch 변경 시 loadLogs 재생성 → effect 발화
- After: `useEffect([filterType, filterStatus, filterDate, debouncedSearch])` — 같은 트리거. 단 명시적 deps.
- **판정**: 동등.

**⚠️ 후보 2**: handlePageChange 가 loadLogs(next) 명시 호출
- Before: setPage 와 loadLogs 두 번 호출 (state setter + 직접 fetch)
- After: setPage 만. queryKey 의 page 변경 → 자동 refetch.
- **위험**: setPage 가 비동기 (다음 렌더에 반영) → queryKey 도 다음 렌더에 변경 → fetch 도 다음 렌더에 시작. Before 는 같은 tick 에 fetch. 약간의 race? **React 의 state batching 으로 같은 frame 처리되므로 사실상 동일.**
- **판정**: 무영향.

**⚠️ 후보 3**: useEffect setPage(0) — 필터 변경 시
- Before: effect 안에서 setPage(0) + loadLogs(0). 두 setState 가 batch.
- After: effect 안에서 setPage(0) 만. queryKey 변경 → query 자동 refetch. 단 page=0 으로의 setPage 와 debouncedSearch 변경이 모두 일어나면 queryKey 한 번에 변경됨 (React batching) — 한 번의 fetch.
- **판정**: 같은 fetch 횟수.

**⚠️ 후보 4**: 빠른 페이지 클릭 (다음, 다음, 다음 빠르게)
- Before: 각 클릭마다 loadLogs(next) 호출 — 3번 호출. 이전 호출의 결과가 늦게 와서 stale data 표시 가능.
- After: setPage → queryKey 변경 → React Query 가 진행 중 fetch cancel + 새 page fetch. 결과 일관성 보장.
- **판정**: After 가 더 안전.

**⚠️ 후보 5**: gcTime 으로 인한 캐시 메모리
- 필터 7개 조합 × 페이지 N 개 = 캐시 폭발 가능 (이론상)
- 실제: 사용자가 동시에 5~10개 조합 정도 방문. gcTime 5min 후 unused GC.
- **판정**: 메모리 영향 무시 가능. 단 사용자가 매우 다양한 필터 빠르게 시도하면 일시적 메모리 증가 — 무시.

---

## 5. 영향받지 않음을 확인할 코드 경로

```
backend/                                # 백엔드 변경 0
frontend/src/lib/queryClient.ts         # 동일
frontend/src/services/api.ts            # activityLogsAPI 동일
frontend/src/stores/                    # 동일
frontend/src/components/                # 동일
frontend/src/pages/RoomAssignment*      # 영향 없음 (다른 카테고리)
frontend/src/pages/Dashboard.tsx        # 영향 없음
frontend/src/pages/Reservations.tsx     # 영향 없음 (Step #5)
frontend/src/pages/(기타)                # 영향 없음
frontend/src/App.tsx                    # 라우터 동일
```

검증: `git diff main -- frontend/src/pages/ backend/` 결과 = ActivityLogs.tsx 한 파일.

추가 변경 파일:
- `frontend/src/lib/queryKeys.ts` (page/pageSize 추가, 2 lines)
- `frontend/src/hooks/useDebouncedValue.ts` (신규, ~15 lines)

---

## 6. 검증 체크리스트

- [ ] **TypeScript**: `cd frontend && npx tsc --noEmit` 에러 0
- [ ] **lint**: 변경 전과 동일
- [ ] **build**: `npm run build` 성공
- [ ] **diff 정확성**: ActivityLogs.tsx + queryKeys.ts (2 lines) + useDebouncedValue.ts (신규)
- [ ] **외부 영향 0**: 다른 페이지 / 백엔드 변경 0
- [ ] **import 정리**: `useCallback` 제거, `useEffect` 일부 유지 (page reset + error log)
- [ ] **수동 검증** (배포 후):
  - [ ] 페이지 로드 → 통계 카드 + logs 표시
  - [ ] 필터 type/status/date 변경 → page 0 reset + refetch
  - [ ] 검색어 입력 → 300ms 후 refetch (입력 중 fetch 없음)
  - [ ] 페이지 다음/이전 → fetch
  - [ ] 이전에 본 페이지 재방문 → 즉시 표시 (캐시 hit)
  - [ ] 빈 결과 / API 실패 → empty state / 0 stats

---

## 7. 후속 의존성

- **useDebouncedValue hook 재사용** — Reservations (Step #5), 잠재적으로 Templates / PartyCheckin 에서 검색 patterns 도입 시 활용
- **ActivityLogFilters 에 page 추가** — Step #1 의 보강. 후속 step 에서 사용처 0개 (ActivityLogs 전용)

---

## 8. 결정 사항 / 보류

- [x] **error logging**: Step #2 와 동일 패턴 (useEffect 로 감쌈)
- [x] **loading = isFetching**: 페이지 전환 시도 깜빡임 유지 (기존 동작)
- [x] **page reset useEffect**: 1개 유지 (책임 분리 위해)
- [x] **stats fallback**: `?? DEFAULT_STATS` — error 시 0 표시 (기존 catch 동작 동등)
- [ ] **Reservations 의 검색어 debounce**: Step #5 에서 동일 hook 사용 (확정)

---

## 9. 머지 후 다음 액션

1. 본 PR 커밋 (push 보류, 사용자 정책)
2. Step #4 (SalesReport) 사전조사 작성
