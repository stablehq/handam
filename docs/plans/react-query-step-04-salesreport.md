# 단계 #4 사전조사 — SalesReport 페이지 React Query 마이그레이션

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #4"
> 분류: 🔵 의도된 동작 변화 (캐시 + cross-category invalidation 도입)
> 변경 규모: 1개 파일, 치환 ~80 lines (Step #1 queryKeys 그대로 사용)
> 선행 단계: Step #1~#3 머지됨

---

## 1. 목적

`SalesReport.tsx` 의 fetch + mutation 패턴을 React Query 로 통일. **첫 mutation 도입 step** — Simple mutation 패턴의 본보기.

### 본 단계가 다루는 것

- `salesReportAPI.get({ date_from, date_to })` → `useQuery(queryKeys.salesReport.report(...))`
- `partyHostsAPI.list()` → `useQuery(queryKeys.partyHosts.list())`
- `partyHostsAPI.create()` → `useMutation` + onSuccess: invalidate partyHosts + salesReport
- `partyHostsAPI.delete()` → `useMutation` + 동일
- 기존 누락 fix: partyHost create/delete 후 sales-report 도 invalidate (현재 진행자 리스트 stale 가능)

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| salesReportAPI 변경 (응답 형식) | 없음 |
| partyHostsAPI 변경 | 없음 |
| UI 컴포넌트 (HostSummary 표시 등) | 없음 |
| viewMode / expandedHosts / detailModal 등 client-side UI state | 없음 (useState 유지) |
| 한담의 cross-tenant leak 사고 (이미 fix 됨, 커밋 bc9fdcb) | 별도 |

---

## 2. 변경 대상 코드

### 2-1. import (line 1-15)

**Before**:
```tsx
import { useState, useEffect, useCallback } from 'react';
...
import { salesReportAPI, partyHostsAPI } from '@/services/api';
```

**After**:
```tsx
import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
...
import { salesReportAPI, partyHostsAPI } from '@/services/api';
import { queryKeys } from '@/lib/queryKeys';
```

### 2-2. fetch + mutation block (line 114-181 영역)

**Before** (~70 lines):
```tsx
const [loading, setLoading] = useState(false);
const [data, setData] = useState<ReportData>({ hosts: [], grand_total_revenue: 0, grand_total_participants: 0 });
...
const [hosts, setHosts] = useState<{ id: number; name: string }[]>([]);

const fetchHosts = useCallback(async () => {
  try {
    const { data: res } = await partyHostsAPI.list();
    setHosts(res ?? []);
  } catch {}
}, []);

useEffect(() => { fetchHosts(); }, [fetchHosts]);

const handleAddHost = async () => {
  const name = newHostName.trim();
  if (!name) return;
  try {
    await partyHostsAPI.create({ name });
    toast.success('진행자가 추가되었습니다');
    setNewHostName('');
    fetchHosts();
  } catch (e: any) {
    toast.error(e.response?.data?.detail ?? '진행자 추가에 실패했습니다');
  }
};

const handleDeleteHost = async (id: number) => {
  try {
    await partyHostsAPI.delete(id);
    toast.success('진행자가 삭제되었습니다');
    fetchHosts();
  } catch { toast.error('진행자 삭제에 실패했습니다'); }
};

const fetchData = useCallback(async () => {
  setLoading(true);
  try {
    const { data: res } = await salesReportAPI.get({ date_from: dateFrom, date_to: dateTo } as any);
    setData(res);
    setExpandedHosts(new Set());
    setDetailModal({ open: false, host: '', dd: null });
  } catch {
    toast.error('매출 데이터를 불러오는데 실패했습니다');
  } finally {
    setLoading(false);
  }
}, [dateFrom, dateTo]);

useEffect(() => {
  fetchData();
}, [fetchData]);
```

**After** (~50 lines):
```tsx
const qc = useQueryClient();

// === Queries ===
const reportQuery = useQuery<ReportData>({
  queryKey: queryKeys.salesReport.report(dateFrom, dateTo),
  queryFn: () => salesReportAPI.get({ date_from: dateFrom, date_to: dateTo } as any).then(r => r.data),
  staleTime: 30_000,
});

const hostsQuery = useQuery<{ id: number; name: string }[]>({
  queryKey: queryKeys.partyHosts.list(),
  queryFn: () => partyHostsAPI.list().then(r => r.data ?? []),
  staleTime: 300_000,  // 마스터 데이터 — 5min
});

const data: ReportData = reportQuery.data ?? { hosts: [], grand_total_revenue: 0, grand_total_participants: 0 };
const hosts = hostsQuery.data ?? [];
const loading = reportQuery.isFetching;

// === 기간 변경 시 UI state reset (기존 fetchData 내부 부수효과 보존) ===
useEffect(() => {
  setExpandedHosts(new Set());
  setDetailModal({ open: false, host: '', dd: null });
}, [dateFrom, dateTo]);

// === Error logging — Step #2 패턴 ===
useEffect(() => {
  if (reportQuery.error) console.error('Failed to load sales report:', reportQuery.error);
}, [reportQuery.error]);
useEffect(() => {
  if (hostsQuery.error) console.error('Failed to load party hosts:', hostsQuery.error);
}, [hostsQuery.error]);

// === Mutations ===
const addHostMutation = useMutation({
  mutationFn: (name: string) => partyHostsAPI.create({ name }),
  onSuccess: () => {
    toast.success('진행자가 추가되었습니다');
    setNewHostName('');
    qc.invalidateQueries({ queryKey: queryKeys.partyHosts.list() });
    qc.invalidateQueries({ queryKey: queryKeys.salesReport.all() });  // 매출 표 진행자 리스트 갱신
  },
  onError: (e: any) => toast.error(e?.response?.data?.detail ?? '진행자 추가에 실패했습니다'),
});

const deleteHostMutation = useMutation({
  mutationFn: (id: number) => partyHostsAPI.delete(id),
  onSuccess: () => {
    toast.success('진행자가 삭제되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.partyHosts.list() });
    qc.invalidateQueries({ queryKey: queryKeys.salesReport.all() });
  },
  onError: () => toast.error('진행자 삭제에 실패했습니다'),
});

const handleAddHost = () => {
  const name = newHostName.trim();
  if (!name) return;
  addHostMutation.mutate(name);
};

const handleDeleteHost = (id: number) => deleteHostMutation.mutate(id);
```

### 2-3. 제거 대상

- `[loading, setLoading]`, `[data, setData]`, `[hosts, setHosts]` useState
- `fetchHosts`, `fetchData` useCallback
- 두 useEffect (fetchHosts/fetchData)
- `handleAddHost`, `handleDeleteHost` 의 try/catch + fetchHosts() 수동 호출

### 2-4. JSX (line 195+) — 변경 0

`data.hosts`, `data.grand_total_revenue`, `hosts.map`, `loading`, `handleAddHost`, `handleDeleteHost` 등 모든 참조 그대로.

---

## 3. queryKey 결정

| API | queryKey | staleTime | 근거 |
|-----|----------|----------|------|
| `salesReportAPI.get(dateFrom, dateTo)` | `queryKeys.salesReport.report(dateFrom, dateTo)` | 30s | 기간별 캐시 분리 |
| `partyHostsAPI.list()` | `queryKeys.partyHosts.list()` | 300s | 마스터 데이터 (자주 안 바뀜) |

**Invalidation 범위**:
- partyHost create/delete 후 → `partyHosts.list()` + `salesReport.all()` 둘 다 invalidate
- `salesReport.all() = ['salesReport', tid]` 가 prefix → 모든 기간(`report(from, to)`) 일괄 무효화

---

## 4. 동작 동등성 / 의도된 변화

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 | 두 fetch 병렬, loading skeleton | 동일 | ⚪ |
| 2 | dateFrom/dateTo 변경 | fetchData useEffect → 새 fetch | queryKey 변경 → 자동 fetch | ⚪ |
| 3 | dateFrom/dateTo 변경 시 expandedHosts/detailModal reset | fetchData 내부에서 setState | 별도 useEffect 로 분리 (의미 동등) | ⚪ |
| 4 | 진행자 추가 | partyHostsAPI.create + fetchHosts() (sales-report 안 갱신) | mutation + invalidate partyHosts + salesReport | 🔵 sales-report 표의 host 리스트도 자동 갱신 (회귀 해결) |
| 5 | 진행자 삭제 | 동일 (sales-report 안 갱신) | 동일 (둘 다 갱신) | 🔵 |
| 6 | 진행자 추가 실패 | toast.error | onError → toast | ⚪ |
| 7 | 같은 기간 재방문 (30s 이내) | 매번 fetch | 캐시 hit | 🔵 |
| 8 | 같은 진행자 목록 (5min 이내) | 매번 fetch | 캐시 hit | 🔵 |
| 9 | 탭 전환 후 돌아옴 | useEffect 발화 안 함 | refetchOnWindowFocus 자동 (staleTime 지나면) | 🔵 |
| 10 | salesReport API 실패 | toast + loading false | useQuery 의 error 상태 + data fallback. **toast 누락**! | ⚠️ 보강 필요 |
| 11 | partyHosts API 실패 | silent (catch {}) | console.error (Step #2 패턴) | ⚪ (silent → console, UI 동일) |
| 12 | viewMode/expandedHosts/detailModal/hostModalOpen 변경 | useState 그대로 | 동일 (query 무관) | ⚪ |
| 13 | mutation 진행 중 더블 클릭 | 두 번 호출 가능 (race) | useMutation 의 isPending 으로 가드 가능 (선택) | 🟡 (현재 미가드, 본 step 에선 동작 동등 우선) |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1 (시나리오 10): salesReport fetch 실패 시 toast 누락**
- Before: `catch { toast.error('매출 데이터를 불러오는데 실패했습니다') }`
- After: `useQuery.error` 만 잡힘 — toast 안 뜸
- **해결**: useEffect 로 error 감지 시 toast 한 번 표시
```tsx
useEffect(() => {
  if (reportQuery.error) {
    console.error('Failed to load sales report:', reportQuery.error);
    toast.error('매출 데이터를 불러오는데 실패했습니다');
  }
}, [reportQuery.error]);
```
- **단**: error 가 같은 객체 reference 유지되면 useEffect 안 발화. React Query 는 새 fetch 마다 새 error 객체. → 매 실패마다 toast 1회.
- **결정**: 위 패턴 채택 (Step #2 의 error logging 보다 한 줄 추가).

**⚠️ 후보 2 (시나리오 13): mutation race**
- Before: handleAddHost 가 await 동안 setNewHostName('') 호출 안 됨 (성공 후만) → 사용자 더블 클릭 시 같은 name 두 번 create 시도 가능 (await 보호 약함)
- After: `addHostMutation.isPending` 으로 버튼 disabled 가능
- **결정**: 본 step 에서는 동작 동등 우선 — 별도 UI 개선 PR 으로 분리 (또는 결정 보류)

**⚠️ 후보 3: setNewHostName('') 시점**
- Before: try 안에서 await create → toast → setNewHostName('') → fetchHosts(). 성공 시만 input 비움.
- After: onSuccess 안에서 setNewHostName('') + invalidate. 성공 시만 input 비움 (동등).
- **판정**: 동등.

**⚠️ 후보 4: fetchData 의 setExpandedHosts/setDetailModal 호출 시점**
- Before: 매 fetch 마다 (마운트, dateFrom/dateTo 변경, 그 외 ❌ 다른 트리거 없음)
- After: `useEffect([dateFrom, dateTo])` — dateFrom/dateTo 변경 시만. 마운트 시도 한 번 호출됨 (deps 첫 비교).
- **판정**: 매우 유사. 차이: refetchOnWindowFocus 같은 자동 refetch 시 reset 안 됨. **이게 오히려 좋음** — 사용자가 펼친 host 가 탭 전환 후 그대로.
- 의도된 UX 개선.

---

## 5. 영향받지 않음 경로

```
backend/                                # 변경 0
frontend/src/lib/queryKeys.ts           # Step #1 머지 상태 그대로
frontend/src/services/api.ts            # 동일
frontend/src/hooks/useDebouncedValue.ts # 미사용 (다른 step 의 hook)
frontend/src/pages/ (SalesReport 외)    # 영향 없음
```

검증: `git diff main -- frontend/ backend/` 결과 = SalesReport.tsx 한 파일.

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] diff: SalesReport.tsx 1 파일, ~80 lines 치환
- [ ] 외부 영향 0
- [ ] `useCallback` import 제거 확인
- [ ] 수동 검증 (배포 후):
  - [ ] 첫 로드 → 매출 표 + 진행자 리스트 표시
  - [ ] 기간 변경 → 새 매출 표시, expandedHosts/detailModal reset
  - [ ] 진행자 추가 → 진행자 관리 모달의 리스트 갱신 **+ 매출 표의 진행자 행 자동 추가** (회귀 해결 검증)
  - [ ] 진행자 삭제 → 모달 리스트 + 매출 표 동시 갱신
  - [ ] 같은 기간 재방문 → 캐시 hit (skeleton 안 보임)
  - [ ] API 실패 → toast 표시

---

## 7. 후속 의존성

- **partyHosts queryKey 가 PartyCheckin (Step #8) 와 공유** — PartyCheckin 도 partyHosts.list() 사용 → 본 step 의 mutation invalidate 가 PartyCheckin 의 query 도 갱신
- **salesReport.all() invalidate 패턴 본보기** — 후속 mutation 들이 cross-category invalidate 시 참고

---

## 8. 결정 사항

- [x] **error logging + toast**: useEffect 안에서 console.error + toast 동시 (시나리오 10 보강)
- [x] **partyHost mutation 후 salesReport invalidate**: 추가 (회귀 해결)
- [x] **Simple mutation 패턴** (Optimistic 미적용 — UX 부담 작음)
- [x] **mutation race 가드**: 본 step 범위 밖 (별도 UI 개선)
- [x] **expandedHosts reset 시점**: dateFrom/dateTo 변경 시만 (자동 refetch 시 보존 — UX 개선)

---

## 9. 머지 후 다음 액션

1. 커밋 (push 보류)
2. Step #5 (Reservations) 사전조사 작성 — 가장 복잡한 단일 page step (필터 6개 + 페이지네이션 + 4 mutation)
