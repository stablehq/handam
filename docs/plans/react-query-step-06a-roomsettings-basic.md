# 단계 #6a 사전조사 — RoomSettings 기본 (rooms / buildings / bizItems 로드 + Room CRUD + reorder)

> 부모 계획: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #6a"
> 분류: 🔵 의도된 동작 변화 (캐시 + cross-invalidate + reorder optimistic)
> 변경 규모: 1개 파일, 치환 ~100 lines
> 선행 단계: Step #1~#5 머지됨

---

## 1. 목적

RoomSettings 의 3 데이터 로드 + Room CRUD + reorder 를 React Query 로 통일. **모달 4종 (biz_item / 건물 / priority / room grade) 의 마이그레이션은 Step #6b**, 단 모달 함수들이 호출하는 `loadRooms()` / `loadBuildings()` / `loadBizItems()` 의 호출처는 본 step 에서 `invalidateQueries` 로 변경 (query 통일).

### 본 단계가 다루는 것

- `roomsAPI.getAll({ include_inactive: true })` → `useQuery(queryKeys.rooms.listWithInactive())`
- `roomsAPI.getBizItems()` → `useQuery(queryKeys.rooms.bizItems())`
- `buildingsAPI.getAll()` → `useQuery(queryKeys.buildings.list())`
- Room create/update/delete → `useMutation` × 2 (saveMutation 통합 + deleteMutation)
- Reorder (DnD) → `useMutation` + **optimistic** (UX 중요)
- 모달 함수들의 `loadRooms()` / `loadBuildings()` / `loadBizItems()` 호출처를 `qc.invalidateQueries(...)` 로 일괄 변경
- RoomAssignment 의 `queryKeys.rooms.list()` 와 cross-invalidate

### 본 단계가 다루지 *않는* 것

| 항목 | 다루는 단계 |
|------|------------|
| biz_item settings modal 본체 (load + save + sync) | Step #6b |
| 건물 manage modal 본체 (handleBuildingSaveAll) | Step #6b |
| priority modal (handlePrioritySave) | Step #6b |
| room grade modal | Step #6b |
| 위 모달들의 useState (bizItemSettingsList, buildingRows, priorityData, roomGradeEdits 등) | Step #6b |

---

## 2. 변경 대상 코드

### 2-1. import + state + init useEffect

**Before**:
```tsx
import { useEffect, useState, useCallback, DragEvent } from 'react';
...
const [rooms, setRooms] = useState<Room[]>([]);
const [loading, setLoading] = useState(false);
const [saving, setSaving] = useState(false);
const [bizItems, setBizItems] = useState<NaverBizItem[]>([]);
const [buildings, setBuildings] = useState<Building[]>([]);
const [buildingsLoading, setBuildingsLoading] = useState(false);
...
useEffect(() => {
  loadRooms();
  loadBizItems();
  loadBuildings();
}, []);

const loadRooms = async () => { setLoading(true); try { const res = await roomsAPI.getAll({ include_inactive: true }); setRooms(res.data); } catch { toast.error('객실 목록 로드 실패'); } finally { setLoading(false); } };
const loadBizItems = async () => { try { const res = await roomsAPI.getBizItems(); setBizItems(res.data); } catch {} };
const loadBuildings = async () => { setBuildingsLoading(true); try { const res = await buildingsAPI.getAll(); setBuildings(res.data); } catch { toast.error('건물 목록 로드 실패'); } finally { setBuildingsLoading(false); } };
```

**After**:
```tsx
import { useEffect, useState, useCallback, DragEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
...
import { queryKeys } from '@/lib/queryKeys';
...
const qc = useQueryClient();

const roomsQuery = useQuery<Room[]>({
  queryKey: queryKeys.rooms.listWithInactive(),
  queryFn: () => roomsAPI.getAll({ include_inactive: true }).then(r => r.data),
  staleTime: 300_000,
});
const rooms = roomsQuery.data ?? [];
const loading = roomsQuery.isFetching;

const bizItemsQuery = useQuery<NaverBizItem[]>({
  queryKey: queryKeys.rooms.bizItems(),
  queryFn: () => roomsAPI.getBizItems().then(r => r.data),
  staleTime: 300_000,
});
const bizItems = bizItemsQuery.data ?? [];

const buildingsQuery = useQuery<Building[]>({
  queryKey: queryKeys.buildings.list(),
  queryFn: () => buildingsAPI.getAll().then(r => r.data),
  staleTime: 300_000,
});
const buildings = buildingsQuery.data ?? [];
const buildingsLoading = buildingsQuery.isFetching;

useEffect(() => {
  if (roomsQuery.error) { console.error('rooms load:', roomsQuery.error); toast.error('객실 목록 로드 실패'); }
}, [roomsQuery.error]);
useEffect(() => {
  if (buildingsQuery.error) { console.error('buildings load:', buildingsQuery.error); toast.error('건물 목록 로드 실패'); }
}, [buildingsQuery.error]);
// bizItems 는 silently fail 유지 (옵션) — console 만
useEffect(() => {
  if (bizItemsQuery.error) console.error('bizItems load:', bizItemsQuery.error);
}, [bizItemsQuery.error]);

// 모달 함수들이 호출하는 helper — Step #6b 머지 시 제거
const loadRooms = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
const loadBuildings = () => qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
const loadBizItems = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
```

### 2-2. handleSave (Room create/update)

**Before** (line 360+, ~30 lines):
```tsx
const handleSave = async () => {
  ... validation ...
  setSaving(true);
  try {
    const payload = {...};
    if (editingId !== null) {
      const res = await roomsAPI.update(editingId, payload);
      toast.success('수정 완료');
      if (res?.data?.warning) toast.warning(res.data.warning, { duration: 10000 });
    } else {
      await roomsAPI.create(payload);
      toast.success('추가 완료');
    }
    setDialogOpen(false);
    loadRooms();
    loadBuildings();
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || '저장 실패');
  } finally {
    setSaving(false);
  }
};
```

**After**:
```tsx
const saveRoomMutation = useMutation({
  mutationFn: ({ id, payload }: { id: number | null; payload: any }) =>
    id != null ? roomsAPI.update(id, payload) : roomsAPI.create(payload),
  onSuccess: (res, vars) => {
    toast.success(vars.id != null ? '수정 완료' : '추가 완료');
    if (vars.id != null && res?.data?.warning) toast.warning(res.data.warning, { duration: 10000 });
    setDialogOpen(false);
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });    // RoomAssignment + RoomSettings 둘 다
    qc.invalidateQueries({ queryKey: queryKeys.buildings.list() }); // 객실 수 변동
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
});

const handleSave = () => {
  ... validation 유지 ...
  const payload = {...};
  saveRoomMutation.mutate({ id: editingId, payload });
};

const saving = saveRoomMutation.isPending;
```

### 2-3. confirmDelete (Room delete)

**Before**:
```tsx
const confirmDelete = async () => {
  if (!deleteTarget) return;
  try {
    await roomsAPI.delete(deleteTarget.id);
    toast.success('삭제 완료');
    loadRooms();
    loadBuildings();
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || '삭제 실패');
  } finally {
    setDeleteTarget(null);
  }
};
```

**After**:
```tsx
const deleteRoomMutation = useMutation({
  mutationFn: (id: number) => roomsAPI.delete(id),
  onSuccess: () => {
    toast.success('삭제 완료');
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail || '삭제 실패'),
  onSettled: () => setDeleteTarget(null),
});

const confirmDelete = () => {
  if (!deleteTarget) return;
  deleteRoomMutation.mutate(deleteTarget.id);
};
```

### 2-4. onDrop (Reorder) — **Optimistic**

**Before**:
```tsx
const onDrop = async (e: DragEvent, targetIndex: number) => {
  ...
  const newRooms = [...rooms];
  const [moved] = newRooms.splice(sourceIndex, 1);
  newRooms.splice(targetIndex, 0, moved);
  setRooms(newRooms);   // optimistic-like (직접 setState)

  try {
    await roomsAPI.reorder(newRooms.map((room) => room.id));
    toast.success('정렬 순서 변경 완료');
    loadRooms();
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || '정렬 변경 실패');
    loadRooms();  // 서버 truth 복원
  }
};
```

**After** (React Query optimistic 패턴):
```tsx
const reorderRoomsMutation = useMutation({
  mutationFn: (newOrder: number[]) => roomsAPI.reorder(newOrder),
  onMutate: async (newOrder) => {
    await qc.cancelQueries({ queryKey: queryKeys.rooms.listWithInactive() });
    const previous = qc.getQueryData<Room[]>(queryKeys.rooms.listWithInactive());
    // optimistic: rooms 배열을 newOrder 순서로 재정렬
    qc.setQueryData<Room[]>(queryKeys.rooms.listWithInactive(), (prev) => {
      if (!prev) return prev;
      const map = new Map(prev.map(r => [r.id, r]));
      return newOrder.map(id => map.get(id)).filter(Boolean) as Room[];
    });
    return { previous };
  },
  onError: (err: any, _vars, ctx) => {
    if (ctx?.previous) qc.setQueryData(queryKeys.rooms.listWithInactive(), ctx.previous);
    toast.error(err?.response?.data?.detail || '정렬 변경 실패');
  },
  onSuccess: () => toast.success('정렬 순서 변경 완료'),
  onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.rooms.all() }),
});

const onDrop = (e: DragEvent, targetIndex: number) => {
  e.preventDefault();
  setDraggingIndex(null);
  const sourceIndex = parseInt(e.dataTransfer.getData('text/plain'), 10);
  if (sourceIndex === targetIndex) return;

  const newRooms = [...rooms];
  const [moved] = newRooms.splice(sourceIndex, 1);
  newRooms.splice(targetIndex, 0, moved);
  reorderRoomsMutation.mutate(newRooms.map(r => r.id));
};
```

### 2-5. 모달 함수들의 loadRooms/loadBuildings/loadBizItems 호출

Step #6b 에서 모달 본체 마이그레이션 예정. 본 step 에서는 helper 만 제공 (위 §2-1 참조):
```tsx
const loadRooms = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
const loadBuildings = () => qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
const loadBizItems = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
```

→ 모달 함수 본체 (handleBuildingSaveAll, handlePrioritySave 등) 의 `loadRooms()` 호출은 그대로 작동 (helper 가 invalidate 함). **Step #6b 머지 시 helper 제거 + 호출처 직접 invalidate**.

### 2-6. 제거 대상

- `[rooms, setRooms]`, `[loading, setLoading]`, `[saving, setSaving]`, `[bizItems, setBizItems]`, `[buildings, setBuildings]`, `[buildingsLoading, setBuildingsLoading]` useState
- `loadRooms` / `loadBizItems` / `loadBuildings` 의 async 함수 본체 (helper 로 대체)
- 초기 init useEffect (`useEffect(() => { loadRooms(); loadBizItems(); loadBuildings(); }, [])`)

---

## 3. queryKey 결정

| API | queryKey | staleTime | 근거 |
|-----|----------|----------|------|
| `roomsAPI.getAll({ include_inactive: true })` | `queryKeys.rooms.listWithInactive()` | 300s | 마스터 데이터 |
| `roomsAPI.getBizItems()` | `queryKeys.rooms.bizItems()` | 300s | 마스터 데이터 |
| `buildingsAPI.getAll()` | `queryKeys.buildings.list()` | 300s | 마스터 데이터 |

**Invalidation 표준**:
- Room CRUD 후: `rooms.all()` + `buildings.list()` → RoomAssignment 의 `rooms.list()` 도 prefix 매칭 (RoomAssignment 변경 0)
- Reorder 후: `rooms.all()`

---

## 4. 동작 동등성 / 의도된 변화

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 | 3 fetch 병렬 | 동일 (3 useQuery 병렬) | ⚪ |
| 2 | 페이지 재방문 (5min 이내) | 매번 fetch | 캐시 hit | 🔵 |
| 3 | Room 추가 | create + loadRooms + loadBuildings | mutation + invalidate rooms.all + buildings.list | 🔵 (RoomAssignment 도 자동 갱신) |
| 4 | Room 수정 (warning 응답) | toast.warning 표시 | mutation onSuccess 에서 vars.id != null && res.data.warning 체크 | ⚪ |
| 5 | Room 삭제 | delete + loadRooms + loadBuildings + setDeleteTarget(null) | mutation + invalidate + onSettled setDeleteTarget(null) | ⚪ |
| 6 | Reorder (성공) | setRooms (optimistic) + reorder + loadRooms | mutation onMutate (optimistic) + onSettled invalidate | ⚪ (의미 동등) |
| 7 | Reorder (실패) | toast.error + loadRooms (서버 truth) | onError ctx.previous 로 원복 + toast | ⚪ (회복 동등) |
| 8 | DnD 빠른 연속 (drop, drop, drop) | 각각 await 직렬 — 마지막 결과만 반영 | mutation cancelQueries — 진행 중 cancel, 새 mutation 만 실행. **단 mutation 자체는 별도** | 🟡 (race 약간 개선 — but 보장 위해 throttle 권장. 본 step 범위 밖) |
| 9 | 모달에서 building 수정 후 loadRooms() 호출 | 실제 로드 | helper 로 invalidate → query 자동 refetch | ⚪ |
| 10 | bizItems 로드 실패 | silent (setBizItems 안 함, bizItems=[]) | useQuery error → useEffect console.error, data=[] | ⚪ (silent → console, UI 동등) |
| 11 | API 실패 (rooms/buildings) | toast.error | useEffect error → console.error + toast | ⚪ |
| 12 | 다른 페이지에서 RoomSettings 진입 | useEffect init fetch | useQuery 자동 fetch (staleTime 가드) | ⚪ |
| 13 | 페이지 탭 전환 후 돌아옴 | useEffect 미실행 | refetchOnWindowFocus (staleTime 지나면) | 🔵 |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1: Optimistic reorder 의 cancelQueries**
- onMutate 가 cancelQueries 호출 → 진행 중 refetch 취소. 일반 fetch (useQuery refetch) 가 진행 중이었을 가능성 — 사용자가 reorder 중 데이터 새로고침 트리거 시.
- React Query 동작: cancelQueries 는 진행 중 query 만 cancel. mutation 자체는 진행.
- **판정**: 의도된 동작 (race 방지).

**⚠️ 후보 2: helper invalidate 와 모달 호출**
- Step #6a 머지 후 step #6b 머지 전 상태: 모달이 `loadRooms()` 호출 → helper 가 invalidate → useQuery 자동 refetch. 동작 OK.
- Step #6b 머지 시 helper 제거 + 모달의 `loadRooms()` 호출도 직접 invalidate 로 변경.
- **판정**: 단계 분리 안전.

**⚠️ 후보 3: warning toast 시점**
- Before: update 시 res.data.warning 있으면 toast.warning. create 시는 없음 (코드상).
- After: onSuccess 안에서 `vars.id != null && res?.data?.warning` 체크.
- **판정**: 동등.

**⚠️ 후보 4: RoomAssignment 의 rooms.list() vs RoomSettings 의 rooms.listWithInactive()**
- 둘 다 `['rooms', tid, ...]` 시작
- `rooms.all() = ['rooms', tid]` invalidate → 두 query 다 잡힘
- RoomAssignment 변경 0, 자동 동기화
- **판정**: 의도된 cross-invalidate. 위험 없음.

**⚠️ 후보 5: setDeleteTarget(null) 시점**
- Before: try/finally 의 finally 에서. 즉 성공/실패 무관 항상 모달 닫음.
- After: mutation onSettled 에서. 동일 (성공/실패 모두 호출).
- **판정**: 동등.

---

## 5. 영향받지 않음 경로

```
backend/                                # 변경 0
frontend/src/lib/queryKeys.ts           # 그대로 (Step #1 정의 사용)
frontend/src/services/api.ts            # 동일
frontend/src/pages/RoomAssignment.tsx   # 코드 변경 0 (cross-invalidate 만)
frontend/src/pages/RoomAssignment/      # 동일
frontend/src/pages/ (RoomSettings 외)   # 영향 없음
```

검증: `git diff main -- frontend/src/pages/ backend/` 결과 = RoomSettings.tsx 한 파일.

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] diff: RoomSettings.tsx 1 파일, ~100 lines 치환
- [ ] 외부 영향 0 (RoomAssignment 변경 0)
- [ ] 모달 함수들 동작 보존 (helper invalidate 로)
- [ ] 수동 검증:
  - [ ] 페이지 로드 → 3 목록 표시
  - [ ] 객실 추가/수정/삭제 → 자동 갱신 (RoomAssignment 도 다음 진입 시 갱신)
  - [ ] DnD reorder → 즉시 UI 반영, 서버 호출 성공 시 토스트, 실패 시 원복
  - [ ] biz_item modal / building modal 등 (Step #6b 마이그레이션 전) — 정상 동작 (helper invalidate)
  - [ ] warning 메시지 (객실 수정 시) — 표시 확인

---

## 7. 후속 의존성

- **Step #6b** — biz_item / 건물 / priority / room grade 모달 본체 마이그레이션. 본 step 의 `loadRooms` 등 helper 제거 + 직접 invalidate.
- **RoomAssignment 자동 갱신 효과** — 본 step 머지 직후 작동 (다음 RoomAssignment 마운트 시 새 객실 목록).

---

## 8. 결정 사항

- [x] **DnD reorder Optimistic** — UX 중요 (RoomAssignment 의 모범사례 패턴)
- [x] **모달 함수의 loadRooms/loadBuildings/loadBizItems → helper invalidate**: Step #6a 시점에 호환성 유지 (Step #6b 에서 제거)
- [x] **cross-invalidate rooms.all() + buildings.list()** — Room CRUD 시 둘 다
- [x] **bizItems error**: silent (console.error 만) — 기존 동작 보존
- [ ] **priorityModal 의 handlePrioritySave 도 함께 마이그레이션?** — 본 step 범위 밖 (Step #6b)
- [ ] **DnD throttle/debounce**: 본 step 범위 밖

---

## 9. 머지 후 다음 액션

1. 커밋 (push 보류)
2. Step #6b (RoomSettings 모달 4종) 사전조사
