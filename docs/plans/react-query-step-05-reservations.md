# 단계 #5 사전조사 — Reservations 페이지 React Query 마이그레이션

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #5"
> 분류: 🔵 의도된 동작 변화 (캐시 + cross-invalidate + 검색 debounce 도입)
> 변경 규모: 1개 파일, 치환 ~150 lines
> 선행 단계: Step #1~#4 머지됨

---

## 1. 목적

Reservations.tsx 의 fetch + 4 mutation (sync/create/update/delete) + 필터 6개 + 페이지네이션을 React Query 로 통일. **가장 복잡한 단일 페이지 step** — Reservations 의 변경은 RoomAssignment 도 영향 (cross-invalidate).

### 본 단계가 다루는 것

- `reservationsAPI.getAll(params)` → `useQuery(queryKeys.reservations.filtered({...}))`
- `reservationsAPI.syncNaver()` → `useMutation` (broad invalidate)
- `reservationsAPI.create()` / `update()` → `useMutation` (broad invalidate)
- `reservationsAPI.delete()` → `useMutation` (broad invalidate)
- 검색어 debounce 도입 (`useDebouncedValue` Step #3 hook 재사용)
- 필터 변경 시 page 1 reset (기존 useRef 패턴 → 단순 useEffect)
- RoomAssignment 의 `reservations.list(date)` 와 cross-invalidate (prefix 매칭)

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| reservationsAPI 변경 (응답/payload schema) | 없음 |
| Form 모달 UI (FormState 등) | 없음 (form 입력 useState 그대로) |
| `editingId`, `deleteId`, `modalOpen` 등 UI state | 없음 |
| RoomAssignment 영향 | cross-invalidate 만 — RoomAssignment 코드 변경 0 |

---

## 2. 변경 대상 코드

### 2-1. import

**Before**:
```tsx
import { useState, useEffect, useRef } from 'react';
...
import { reservationsAPI, type ReservationCreatePayload } from '@/services/api';
```

**After**:
```tsx
import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
...
import { reservationsAPI, type ReservationCreatePayload } from '@/services/api';
import { queryKeys } from '@/lib/queryKeys';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
```

### 2-2. fetch + filter effect 부분

**Before** (~50 lines):
```tsx
const [currentPage, setCurrentPage] = useState(1);
const [totalCount, setTotalCount] = useState(0);
const PAGE_SIZE = 50;

async function fetchReservations(page = currentPage) {
  setLoading(true);
  try {
    const params = { skip: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE };
    if (filterDateFrom) (params as any).date_from = filterDateFrom;
    if (filterDateTo) (params as any).date_to = filterDateTo;
    if (filterStatus.length > 0) params.status = filterStatus.join(',');
    if (filterSource.length > 0) params.source = filterSource.join(',');
    if (searchQuery.trim()) params.search = searchQuery.trim();
    const res = await reservationsAPI.getAll(params);
    const data = res.data;
    setReservations(data.items ?? data ?? []);
    setTotalCount(data.total ?? 0);
  } catch {
    toast.error('예약 목록을 불러오지 못했습니다.');
  } finally {
    setLoading(false);
  }
}

// Reset to page 1 when filters change (no fetch here — page effect handles it)
const prevFiltersRef = useRef({...});
useEffect(() => {
  const prev = prevFiltersRef.current;
  const changed = ...;
  prevFiltersRef.current = {...};
  if (changed) setCurrentPage(1);
}, [filterDateFrom, filterDateTo, filterStatus, filterSource, searchQuery]);

useEffect(() => {
  fetchReservations(currentPage);
}, [currentPage, filterDateFrom, filterDateTo, filterStatus, filterSource, searchQuery]);

const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
```

**After** (~50 lines):
```tsx
const qc = useQueryClient();
const PAGE_SIZE = 50;

const [currentPage, setCurrentPage] = useState(1);
const debouncedSearch = useDebouncedValue(searchQuery, 300);

// 필터/검색 변경 시 page 1 reset (기존 useRef 패턴 단순화)
useEffect(() => {
  setCurrentPage(1);
}, [filterDateFrom, filterDateTo, filterStatus, filterSource, debouncedSearch]);

const reservationsQuery = useQuery({
  queryKey: queryKeys.reservations.filtered({
    page: currentPage,
    pageSize: PAGE_SIZE,
    status: filterStatus.length > 0 ? filterStatus.join(',') : undefined,
    source: filterSource.length > 0 ? filterSource.join(',') : undefined,
    search: debouncedSearch.trim() || undefined,
    dateFrom: filterDateFrom || undefined,
    dateTo: filterDateTo || undefined,
  }),
  queryFn: async () => {
    const params: Record<string, any> = {
      skip: (currentPage - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
    };
    if (filterDateFrom) params.date_from = filterDateFrom;
    if (filterDateTo) params.date_to = filterDateTo;
    if (filterStatus.length > 0) params.status = filterStatus.join(',');
    if (filterSource.length > 0) params.source = filterSource.join(',');
    if (debouncedSearch.trim()) params.search = debouncedSearch.trim();
    const res = await reservationsAPI.getAll(params);
    const data = res.data;
    return {
      items: (data.items ?? data ?? []) as Reservation[],
      total: data.total ?? 0,
    };
  },
  staleTime: 30_000,
});

const reservations = reservationsQuery.data?.items ?? [];
const totalCount = reservationsQuery.data?.total ?? 0;
const loading = reservationsQuery.isFetching;
const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

useEffect(() => {
  if (reservationsQuery.error) {
    console.error('Failed to load reservations:', reservationsQuery.error);
    toast.error('예약 목록을 불러오지 못했습니다.');
  }
}, [reservationsQuery.error]);

// === Mutations ===
// 모든 mutation 후 reservations 전체 invalidate (RoomAssignment 의 .list(date) 도 prefix 매칭으로 같이)
const invalidateAllReservations = () =>
  qc.invalidateQueries({ queryKey: queryKeys.reservations.all() });

const syncMutation = useMutation({
  mutationFn: () => reservationsAPI.syncNaver(),
  onSuccess: (res) => {
    const added = res.data?.added ?? 0;
    const updated = res.data?.updated ?? 0;
    toast.success(`네이버 동기화 완료 — ${added}건 추가, ${updated}건 갱신`);
    invalidateAllReservations();
  },
  onError: () => toast.error('네이버 동기화에 실패했습니다.'),
});

const saveMutation = useMutation({
  mutationFn: ({ id, payload }: { id: number | null; payload: ReservationCreatePayload }) =>
    id != null ? reservationsAPI.update(id, payload) : reservationsAPI.create(payload),
  onSuccess: (_, vars) => {
    toast.success(vars.id != null ? '예약이 수정되었습니다.' : '예약이 등록되었습니다.');
    setModalOpen(false);
    invalidateAllReservations();
  },
  onError: () => toast.error('저장에 실패했습니다.'),
});

const deleteMutation = useMutation({
  mutationFn: (id: number) => reservationsAPI.delete(id),
  onSuccess: () => {
    toast.success('예약이 삭제되었습니다.');
    setDeleteId(null);
    invalidateAllReservations();
  },
  onError: () => toast.error('삭제에 실패했습니다.'),
});

const syncing = syncMutation.isPending;
const saving = saveMutation.isPending;
const deleting = deleteMutation.isPending;
```

### 2-3. handler 단순화

**Before**:
```tsx
async function handleSync() { setSyncing(true); try { ... fetchReservations(); } catch { ... } finally { ... } }
async function handleSave() { ... setSaving(true); try { ... await create/update ... fetchReservations(); } catch { ... } finally { ... } }
async function handleDelete() { ... setDeleting(true); try { ... await delete ... fetchReservations(); } catch { ... } finally { ... } }
```

**After**:
```tsx
function handleSync() { syncMutation.mutate(); }
function handleSave() {
  // validation 유지
  if (!form.customer_name.trim()) { toast.error('예약자 이름을 입력하세요.'); return; }
  if (!form.phone.trim())          { toast.error('전화번호를 입력하세요.');    return; }
  if (!form.reservation_date)      { toast.error('예약 날짜를 선택하세요.');   return; }
  // payload 생성 그대로
  const payload: ReservationCreatePayload = {...};
  saveMutation.mutate({ id: editingId, payload });
}
function handleDelete() {
  if (deleteId == null) return;
  deleteMutation.mutate(deleteId);
}
```

### 2-4. 제거 대상

- `setReservations`, `setLoading`, `setSyncing`, `setSaving`, `setDeleting`, `setTotalCount` 4개 useState
- `[reservations, setReservations]` useState (line 158 추정 — 함께 read 필요)
- `fetchReservations` 함수
- `prevFiltersRef` + 필터 변경 감지 useEffect (단순 useEffect 로 대체)
- 두 번째 useEffect (fetchReservations 자동 호출 — useQuery 가 책임)
- `useRef` import 제거

### 2-5. JSX (line 365+) — 변경 0

`reservations.map`, `loading`, `syncing`, `saving`, `deleting`, `currentPage`, `totalPages`, `totalCount`, `handleSync`, `handleSave`, `handleDelete` 등 모든 참조 그대로.

---

## 3. queryKey 결정

| API | queryKey | staleTime | 근거 |
|-----|----------|----------|------|
| `reservationsAPI.getAll(params)` | `queryKeys.reservations.filtered({page, pageSize, filters})` | 30s | 필터/페이지 조합별 캐시 |

**Invalidation 표준**:
- 모든 mutation 후 `queryKeys.reservations.all() = ['reservations', tid]` 호출 → prefix 매칭으로 `filtered({...})` + `list(date)` (RoomAssignment) 둘 다 잡힘
- 한 mutation 으로 **Reservations 페이지 + RoomAssignment 페이지** 모두 동기화

---

## 4. 동작 동등성 / 의도된 변화

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 | fetchReservations 호출, loading | useQuery 자동 호출, isFetching | ⚪ |
| 2 | 페이지 다음 | setCurrentPage → useEffect → fetchReservations | setCurrentPage → queryKey 변경 → 자동 refetch | ⚪ |
| 3 | 같은 페이지 재방문 (30s 이내) | 매번 fetch | 캐시 hit | 🔵 |
| 4 | 필터 status 변경 | prevFiltersRef + setCurrentPage(1) + useEffect refetch | 단순 useEffect setCurrentPage(1) + queryKey 변경 | ⚪ |
| 5 | 검색어 타이핑 | 매 키스트로크마다 fetch | 300ms debounce 후 fetch | 🔵 (의도 — fetch thrash 회피) |
| 6 | 네이버 동기화 | handleSync + fetchReservations | syncMutation + invalidate all → RoomAssignment 도 자동 갱신 | 🔵 (Reservations + RoomAssignment 동시 갱신) |
| 7 | 예약 추가 | create + fetchReservations (현 페이지만) | mutation + invalidate all → 모든 필터/페이지 + RoomAssignment 갱신 | 🔵 |
| 8 | 예약 수정 | update + fetchReservations | 동일 | 🔵 |
| 9 | 예약 삭제 | delete + fetchReservations | mutation + invalidate all | 🔵 |
| 10 | 빠른 페이지 클릭 (다음, 다음, 다음) | 3번 fetchReservations — race 가능 | queryKey 변경 시 React Query 자동 cancel | 🔵 (race 방지) |
| 11 | API 실패 (fetch) | toast.error + setLoading(false) | useEffect error toast (Step #4 패턴) | ⚪ |
| 12 | API 실패 (mutation) | catch toast.error | onError toast | ⚪ |
| 13 | 탭 전환 후 돌아옴 | useEffect 발화 안 함 | refetchOnWindowFocus (staleTime 지나면) | 🔵 |
| 14 | filterStatus 가 새 배열 (reference 변경) | 매 렌더마다 useEffect 발화 — fetch thrash 위험 | queryKey 객체 deep compare → 내용 같으면 무시 | 🔵 (불필요한 fetch 회피) |
| 15 | useRef prevFilters 패턴 제거 | 정확한 "변경됨" 감지 | 단순 useEffect — 매번 setCurrentPage(1) 호출 (값 같으면 no-op) | ⚪ (React batching 동등) |
| 16 | mutation 중 사용자 더블 클릭 (예: 빠른 저장) | saveMutation 안 가드 (await 만) | `saving = saveMutation.isPending` — 버튼 disabled 동작 동등 | ⚪ |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1 (시나리오 5): 검색어 debounce 도입**
- 동작 변화: 입력 즉시 fetch → 300ms 후 fetch
- 사용자 체감: 입력 중 결과 표시가 약간 지연됨 (300ms)
- 일반적으로 UX 개선 — 표준 패턴 (ActivityLogs Step #3 와 동일)
- **결정**: 도입 (의도된 변화)

**⚠️ 후보 2 (시나리오 14): filterStatus / filterSource 배열 reference 변경**
- Before: 매 렌더마다 새 배열 ref → useEffect 매 발화 → fetchReservations 매 호출. 단 `prevFiltersRef` 가 reference 비교라 changed=false → setCurrentPage 안 함. 그러나 fetchReservations useEffect 는 deps 에 [filterStatus, ...] 있으니 매 발화 → fetch.
- **확인 필요**: 실제로 filterStatus 가 매 렌더마다 새 ref 인지. setFilterStatus 호출 안 하면 ref 유지. setFilterStatus 호출 시 (필터 변경) 만 새 ref → useEffect 발화 (정상).
- After: queryKey 안에 `filterStatus.length > 0 ? filterStatus.join(',') : undefined` 문자열로 직렬화 → ref 무관, 값 비교. queryKey 객체 deep equality 로 안전.
- **판정**: After 가 안전. 의도된 개선.

**⚠️ 후보 3 (시나리오 15): 단순 useEffect setCurrentPage(1)**
- Before: prevFiltersRef 로 정확히 "변경됨" 감지 후 setCurrentPage(1) — 같은 값 setState 안 함
- After: 매 deps 변경 시 setCurrentPage(1) 호출 — currentPage 가 이미 1이면 React 가 no-op (state 동일 — 리렌더 안 일어남)
- **판정**: React 의 setState 동일값 가드로 동등.

**⚠️ 후보 4: invalidateQueries 의 RoomAssignment 영향**
- RoomAssignment 의 useReservationsData.ts:50,60 가 `queryKeys.reservations.list(dateStr)` + `list(nextDateStr)` 사용
- 본 step 의 mutation 후 `reservations.all()` invalidate → prefix 매칭으로 `list(date)` 도 무효화
- RoomAssignment 가 활성 (사용자가 그 페이지에 있음) 이면 즉시 refetch. 아니면 다음 마운트 시 refetch.
- **판정**: 의도된 동작 — Reservations 에서 예약 수정 → RoomAssignment 자동 동기화. 회귀가 아니라 개선.

**⚠️ 후보 5: setModalOpen(false), setDeleteId(null) 시점**
- Before: try 안에서 await 후 (성공 시) close
- After: onSuccess 에서 close
- 동등.

**⚠️ 후보 6: handleSave 의 form validation 위치**
- Before: setSaving(true) 호출 전 validation. validation 실패 시 setSaving 안 호출.
- After: mutation.mutate 호출 전 validation. validation 실패 시 mutation 시작 안 함.
- 동등.

**⚠️ 후보 7: openEdit 함수 (form 초기화 + setModalOpen(true))**
- query 와 무관 — useState form 유지.
- **판정**: 영향 없음.

---

## 5. 영향받지 않음 경로

```
backend/                                # 변경 0
frontend/src/lib/queryKeys.ts           # 그대로 (Step #1 정의 사용)
frontend/src/lib/queryClient.ts         # 동일
frontend/src/services/api.ts            # reservationsAPI 동일
frontend/src/hooks/useDebouncedValue.ts # Step #3 머지 상태 그대로
frontend/src/pages/RoomAssignment.tsx   # 코드 변경 0 (cross-invalidate 만)
frontend/src/pages/RoomAssignment/      # 동일
frontend/src/pages/ (Reservations 외)   # 영향 없음
```

검증: `git diff main -- frontend/src/pages/ backend/` 결과 = Reservations.tsx 한 파일.

**RoomAssignment cross-invalidate 검증**:
- `useReservationsData.ts:51,61` queryKey: `queryKeys.reservations.list(dateStr)` = `['reservations', tid, date]`
- 본 step 의 `reservations.all()` = `['reservations', tid]` invalidate → prefix 매칭으로 `list(date)` 도 무효화
- React Query 동작 검증: `invalidateQueries({queryKey: ['reservations', 1]})` 가 `['reservations', 1, '2026-05-19']` 와 매칭됨 (공식 문서)

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] diff: Reservations.tsx 1 파일, ~150 lines 치환
- [ ] 외부 영향 0 (RoomAssignment 변경 0)
- [ ] `useRef`, `useCallback` import 제거
- [ ] 수동 검증 (배포 후):
  - [ ] 페이지 로드 → 예약 목록 표시
  - [ ] 필터 변경 → page 1 reset + 새 결과
  - [ ] 검색어 입력 → 300ms 후 fetch
  - [ ] 페이지 다음/이전 → fetch
  - [ ] 예약 추가 → 현재 페이지 자동 갱신 + RoomAssignment 페이지 가서 보면 새 예약 표시
  - [ ] 예약 수정 → 자동 갱신 (Reservations + RoomAssignment)
  - [ ] 예약 삭제 → 자동 갱신
  - [ ] 네이버 동기화 → 자동 갱신 (양쪽 페이지)
  - [ ] 이전 페이지 재방문 → 캐시 hit

---

## 7. 후속 의존성

- **cross-invalidate 본보기** — RoomSettings (Step #6a) 의 rooms mutation 도 같은 방식 (RoomAssignment 의 rooms.list() invalidate)
- **debounce 패턴 재사용** — Templates / PartyCheckin 검색 도입 시

---

## 8. 결정 사항

- [x] **검색 debounce 도입** (300ms) — UX 개선
- [x] **invalidateAllReservations() helper** — 4개 mutation 동일 invalidate 패턴
- [x] **`filterStatus.join(',')` 직렬화** — array reference 문제 회피
- [x] **prevFiltersRef 제거** — 단순 useEffect (React 의 setState 동일값 가드 활용)
- [x] **mutation.isPending → saving/syncing/deleting** — 기존 useState 동등
- [x] **form validation 위치 보존** (mutate 호출 전)
- [ ] **Optimistic update**: 예약 삭제 (delete 후 페이지에서 즉시 사라지는 UX) — 본 step 범위 밖. 별도 검토 (현재 invalidate 만으로도 충분)

---

## 9. 머지 후 다음 액션

1. 커밋 (push 보류)
2. Step #6a (RoomSettings 기본) 사전조사 — RoomAssignment 와 cross-cache 공유 (rooms.list)
