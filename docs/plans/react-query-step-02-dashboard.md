# 단계 #2 사전조사 — Dashboard 페이지 React Query 마이그레이션

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #2"
> 분류: 🔵 의도된 동작 변화 (캐시/UX 개선)
> 변경 규모: 1개 파일, 치환 ~30 lines
> 선행 단계: Step #1 머지됨 (커밋 `df97b76`)
> **본보기 step** — 후속 step 들이 본 step 의 패턴 답습

---

## 1. 목적

`Dashboard.tsx` 의 2개 `useEffect + useState + 직접 fetch` 패턴을 `useQuery` 2개로 치환. mutation 없음 (read-only 페이지).

### 본 단계가 다루는 것

- `dashboardAPI.getStats()` → `useQuery(queryKeys.dashboard.stats())`
- `dashboardAPI.getTodaySchedules()` → `useQuery(queryKeys.dashboard.schedules())`
- `setStats`/`setSchedules`/`setLoading` 제거 → React Query state 로 대체
- `loadStats` 함수 제거 → useQuery 가 자동 호출

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| `dashboardAPI` 자체 (백엔드 응답 형식) | 변경 0 |
| `MetricCard` / `GenderWeekly` / `LoadingSkeleton` 컴포넌트 | 변경 0 (props/렌더 동일) |
| `STATUS_LABELS` / `normalizeUtcString` 등 유틸 | 변경 0 |
| 페이지 레이아웃 / 디자인 | 변경 0 |
| Mutation 추가 (Dashboard 는 read-only) | 해당 없음 |
| 다른 페이지 | 별도 step |

---

## 2. 변경 대상 코드

### 2-1. import (line 1-15)

**Before**:
```tsx
import { useEffect, useState } from 'react'
...
import { dashboardAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'
```

**After**:
```tsx
import { useQuery } from '@tanstack/react-query'
...
import { dashboardAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'
import { queryKeys } from '@/lib/queryKeys'
```

**변경 의도**:
- `useEffect`, `useState` 제거 (state 관리 React Query 로 이전)
- `useQuery` 추가
- `queryKeys` 추가 (Step #1 에서 정의한 `dashboard.stats / schedules`)

### 2-2. 컴포넌트 본문 — state + effect 제거 (line 117-139)

**Before**:
```tsx
const Dashboard = () => {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [schedules, setSchedules] = useState<any[]>([])

  useEffect(() => {
    loadStats()
  }, [])

  useEffect(() => {
    dashboardAPI.getTodaySchedules().then(res => setSchedules(res.data)).catch(() => {})
  }, [])

  const loadStats = async () => {
    try {
      const response = await dashboardAPI.getStats()
      setStats(response.data)
    } catch (error) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <LoadingSkeleton />
  }

  if (!stats) {
    return (
      <div className="empty-state">
        <p className="text-body">데이터를 불러올 수 없습니다.</p>
      </div>
    )
  }
```

**After**:
```tsx
const Dashboard = () => {
  const statsQuery = useQuery<any>({
    queryKey: queryKeys.dashboard.stats(),
    queryFn: () => dashboardAPI.getStats().then(res => res.data),
    staleTime: 30_000,
  })

  const schedulesQuery = useQuery<any[]>({
    queryKey: queryKeys.dashboard.schedules(),
    queryFn: () => dashboardAPI.getTodaySchedules().then(res => res.data),
    staleTime: 30_000,
  })

  const stats = statsQuery.data
  const schedules: any[] = schedulesQuery.data ?? []
  const loading = statsQuery.isLoading

  if (loading) {
    return <LoadingSkeleton />
  }

  if (!stats) {
    return (
      <div className="empty-state">
        <p className="text-body">데이터를 불러올 수 없습니다.</p>
      </div>
    )
  }
```

**변경 의도**:
- 3개 useState 제거 → useQuery state 활용
- 2개 useEffect 제거 → useQuery 자동 호출
- `loadStats` 함수 제거 → useQuery 가 책임
- `loading = statsQuery.isLoading` — 기존 의미 보존 (초기 로드 중 indicator)
- `stats = statsQuery.data` — 초기 undefined (기존 null) — `if (!stats)` 가드가 둘 다 잡음
- `schedules ?? []` — undefined 방어 (기존 useState 초기값 [] 와 동일 효과)

### 2-3. JSX (line 155-310) — 변경 0

`stats.totals.today_reservations`, `stats.gender_stats?.daily`, `schedules.map`, `(stats.recent_reservations ?? []).slice(...)` 등 모든 참조 변경 없음.

---

## 3. queryKey 결정 — 라인 단위 근거

| API 호출 | queryKey (Step #1 정의) | staleTime | 근거 |
|----------|------------------------|----------|------|
| `dashboardAPI.getStats()` | `queryKeys.dashboard.stats() = ['dashboard', tid, 'stats']` | 30s | 통계 카드 — 너무 자주 호출 안 하되 작업 후 30s 이내 갱신 충분 |
| `dashboardAPI.getTodaySchedules()` | `queryKeys.dashboard.schedules() = ['dashboard', tid, 'schedules']` | 30s | 오늘 스케줄 — 발송 결과 30s 이내 반영. customSchedule 실행 시 invalidate 받을 수 있어야 (후속 Step #7 에서 broad invalidate) |

**broad invalidation 준비**:
- 두 query 모두 `['dashboard', tid, ...]` prefix → `invalidateQueries({ queryKey: queryKeys.dashboard.all() })` 로 일괄 무효화 가능
- 단 본 step 에서는 Dashboard 가 mutation 안 가지므로 invalidation 호출 0 — 후속 step (예: SalesReport mutation 후 dashboard 도 영향이면) 에서 cross-category invalidate 검토

---

## 4. 동작 동등성 / 의도된 변화

### 4-1. 정적 분석 기반

| 검증 항목 | 검증 방법 | 기대 결과 |
|----------|----------|----------|
| 응답 schema 호환 | `stats.totals.today_reservations`, `stats.campaigns?.today_sent`, `stats.naver_sync?.status` 등 기존 참조 패턴 동일 | ✅ |
| 컴포넌트 props 변경 | `MetricCard`, `GenderWeekly` 호출 부분 변경 0 | ✅ |
| 기존 export 동일 | `export default Dashboard` 변경 0 | ✅ |
| 다른 페이지에서 Dashboard import | grep 결과 0건 (App.tsx 의 라우터만 import) | ✅ |

### 4-2. 시나리오 매트릭스

⚪ = 변화 없음 / 🔵 = 의도된 변화 / ⚠️ = 잠재 사이드이펙트.

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 페이지 로드 (캐시 비어있음) | `<LoadingSkeleton />` 표시 → API 응답 후 본문 | 동일 (statsQuery.isLoading=true 동안 skeleton) | ⚪ |
| 2 | stats API 실패 (네트워크 에러) | console.error + setLoading(false) → `!stats` 분기 → "데이터를 불러올 수 없습니다" | 동일 (statsQuery.data 가 undefined 유지 + isLoading false → `!stats` 분기) | ⚪ |
| 3 | schedules API 실패 | catch(() => {}) — silent, schedules 빈 배열 | 동일 (schedulesQuery.data 가 undefined → `?? []` → 빈 배열 → "등록된 스케줄이 없습니다" 표시) | ⚪ |
| 4 | 페이지 마운트 → unmount → 30s 이내 재마운트 | 매번 API 재호출 (loading skeleton 다시 표시) | **캐시에서 즉시 표시 (skeleton 안 보임)** | 🔵 의도 |
| 5 | 페이지 마운트 → 30s 이후 재마운트 | 매번 API 재호출 | 캐시 stale → background refetch + 캐시 즉시 표시 (skeleton 안 보임, 새 데이터 도착 시 자동 갱신) | 🔵 의도 |
| 6 | 페이지 마운트 → 다른 탭으로 이동 → 돌아옴 | useEffect 가 마운트에만 실행 → 새로고침 안 됨 (창 focus 무관) | `refetchOnWindowFocus: true` (queryClient 기본) → 자동 refetch | 🔵 의도 (UX 개선) |
| 7 | 테넌트 전환 (Layout 의 reload) | reload 후 새 tenant 데이터 fetch | 동일 (reload → queryClient 초기화 → fetch) | ⚪ |
| 8 | 컴포넌트 unmount 직후 (gcTime 5min 이내) | useState 소실 — 메모리 해제 | useQuery 데이터 캐시에 보존 (gcTime) → 재마운트 시 즉시 표시 | 🔵 의도 |
| 9 | 같은 데이터를 다른 페이지가 사용 (현재 없음) | N/A | 캐시 공유 가능 (미래 확장성) | ⚪ |
| 10 | stats 데이터 형식이 백엔드에서 변경 | 기존 코드와 동일 — useQuery 도 단지 fetch + 보관 | 동일 | ⚪ |
| 11 | 로그아웃 → 재로그인 | reload → 모든 state 초기화 | 동일 | ⚪ |
| 12 | 빠른 클릭 (마운트 직후 unmount) | useEffect 실행되었으나 setState 무시됨 (React 경고 없음 — fetch promise 가 resolve 시 컴포넌트 unmounted) | useQuery 가 자동으로 cancelled (cancelQueries 가 진행 — React Query 가 abort 처리) | 🔵 (warning 회피) |

### 4-3. 잠재 사이드이펙트 검토

**⚠️ 후보 1**: `refetchOnWindowFocus: true` (queryClient 기본)
- 사용자가 탭 전환했다가 돌아오면 자동 refetch
- Dashboard 의 stats/schedules 가 매번 새로 fetch → 서버 부하 약간 증가
- **판정**: staleTime 30s 가드 — 30s 이내면 refetch 안 함 (캐시 fresh). 30s 이후만 실제 호출. 의도된 UX 개선.

**⚠️ 후보 2**: `refetchOnMount: true` (queryClient 기본)
- 컴포넌트 재마운트 시 자동 refetch (단 staleTime 가드 적용)
- 30s 이내 재마운트 시 캐시 사용 + background refetch 동시
- **판정**: 기존 useEffect 도 마운트마다 fetch. 같은 동작 + 캐시 즉시 표시 추가.

**⚠️ 후보 3**: `retry: 1` (queryClient 기본)
- API 실패 시 1회 자동 재시도
- 기존 코드는 재시도 0 (1회 호출 후 catch)
- **판정**: 의도된 변화 — 일시적 네트워크 오류 자동 복구. 단 실패 후 한 번 더 호출되므로 백엔드 부하 약간 ↑. 무시 가능.

**⚠️ 후보 4**: 로그/에러 추적
- 기존 `console.error('Failed to load stats:', error)` 제거됨
- React Query 가 자동 로그 안 남김 (devtools 만)
- Sentry 가 잡는지 확인 필요 → `main.tsx:51-57` 의 `Sentry.ErrorBoundary` 는 렌더 에러만 잡음, fetch 실패는 못 잡음
- **판정**: 운영 시 stats fetch 실패가 silent 가 됨. 대응:
  - 옵션 A: 기존 behavior 유지 — `onError` 에 console.error 추가
  - 옵션 B: toast 표시 — 사용자 가시 변화 (의도되지 않음)
  - 옵션 C: silent — 어차피 `!stats` 분기로 사용자 인지
  - **결정: 옵션 A (console.error 유지)** — 기존 동작 동일하게.

**⚠️ 후보 5**: 컴포넌트가 useState 의존하는 다른 곳 없는지
- grep 결과: `stats`, `schedules` 는 Dashboard 안에서만 사용. 외부 0건
- **판정**: 영향 없음

**⚠️ 후보 6**: 첫 번째 useEffect 의 `loadStats()` 내부 setLoading(false) 의 finally 시점
- 기존: stats 성공이든 실패든 setLoading(false) → 항상 로딩 끝
- After: `statsQuery.isLoading` 은 첫 fetch 응답 받으면 자동 false (성공/실패 모두)
- **판정**: 동등

---

## 5. 영향받지 않음을 확인할 코드 경로

다음 영역은 본 단계에서 **1 byte 도 변경되지 않으며 동작 변화 없음**:

```
backend/                                # 백엔드 변경 0 (frontend 전용)
frontend/src/lib/queryClient.ts         # 설정 동일
frontend/src/lib/queryKeys.ts           # Step #1 머지된 상태 그대로
frontend/src/services/api.ts            # dashboardAPI 동일
frontend/src/stores/                    # tenant-store, auth-store 동일
frontend/src/components/                # MetricCard 외부 (없음), Layout 등 동일
frontend/src/pages/RoomAssignment.tsx   # 영향 없음
frontend/src/pages/RoomAssignment/      # 영향 없음
frontend/src/pages/ (Dashboard 외)      # 영향 없음
frontend/src/App.tsx                    # 라우터 동일
```

검증: `git diff main -- frontend/ backend/` 결과 = Dashboard.tsx 한 파일.

---

## 6. 검증 체크리스트

PR 작성 시 모두 ✅:

- [ ] **TypeScript**: `cd frontend && npx tsc --noEmit` 에러 0
- [ ] **lint**: `cd frontend && npm run lint` 변경 전과 동일
- [ ] **build**: `cd frontend && npm run build` 성공
- [ ] **diff 정확성**: `git diff main -- frontend/` 결과 = Dashboard.tsx 1 파일, ~30 lines 치환
- [ ] **외부 영향 0**: `git diff main -- frontend/src/lib/ frontend/src/services/ frontend/src/stores/ frontend/src/components/ backend/` 결과 = 0
- [ ] **사용 안 하는 import 제거**: `useEffect`, `useState` import 제거 확인
- [ ] **수동 검증** (배포 후):
  - [ ] Dashboard 로드 시 LoadingSkeleton 표시 → 본문 정상
  - [ ] 페이지 이동 → 돌아오기 (30s 이내) → skeleton 안 보이고 즉시 표시
  - [ ] 탭 전환 → 돌아오기 → 데이터 갱신 (`refetchOnWindowFocus`)
  - [ ] 한담/스테이블 전환 → 페이지 reload → 새 tenant 데이터
  - [ ] 백엔드 일시 중단 시 LoadingSkeleton 무한? — staleTime 후 실패 시 `!stats` 분기 (기존과 동일)
- [ ] **Console.error 유지** (잠재 사이드이펙트 §4-3 후보 4 대응): `onError: (error) => console.error('Failed to load stats:', error)` 추가

---

## 7. 후속 의존성

본 단계가 머지된 후:

- **본보기 step 완료** — Step #3~#8 가 본 패턴을 답습
- **dashboard 카테고리 활성화** — 다른 페이지에서 dashboard mutation (현재 없음) 시 `invalidateQueries({ queryKey: queryKeys.dashboard.all() })` 호출 가능
- **추가 후속 의존성 없음** — Dashboard 는 단순 read-only

---

## 8. 결정 사항 (본 step 사전조사에서 결정)

- [x] `staleTime: 30_000` (30s) — 두 query 동일. dashboard 는 자주 변하는 데이터지만 매 마운트마다 fetch 는 과함.
- [x] `gcTime`: queryClient 기본 (5min) 사용 — 별도 override 없음.
- [x] `onError`: `console.error` 유지 — 기존 silent 동작 보존.
- [x] Optimistic update: N/A (mutation 없음)
- [x] Broad invalidation `dashboard.all()` 함수는 정의됐지만 본 step 에서 호출 0 — 미래 mutation 추가 시 사용.

### 결정 보류 (후속 step 에서 검토)

- [ ] **다른 페이지의 mutation 후 dashboard invalidate 여부** — 예: 예약 추가 → Dashboard 의 "오늘 예약" 카운트 갱신? 현재 reload 가 처리하지만, 통일 후 reload 제거되면 cross-category invalidate 필요. Step #5 (Reservations) 사전조사에서 검토.

---

## 9. 머지 후 다음 액션

1. 본 PR (Step #2) 머지 — push 는 모든 step 완료 후 모아서 진행 (사용자 정책)
2. Step #3 (ActivityLogs) 사전조사 작성
3. 본 step 의 패턴을 후속 step 의 본보기로 활용
