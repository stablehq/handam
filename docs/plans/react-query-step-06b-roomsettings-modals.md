# 단계 #6b 사전조사 — RoomSettings 모달 4종 마이그레이션

> 부모: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #6b"
> 분류: 🔵 의도된 변화 (mutation invalidate 표준화) + ⚫ 정리 (helper 제거)
> 변경 규모: 1개 파일, 치환 ~120 lines
> 선행: Step #6a 머지됨 (커밋 `ccd365f`)

---

## 1. 목적

Step #6a 의 후속 — 4개 모달 mutation 본체를 useMutation 으로 변경 + biz_item settings list 를 useQuery (`enabled: bizItemModalOpen`) 로 전환. Step #6a 에서 호환 위해 둔 helper (`loadRooms`, `loadBuildings`, `loadBizItems`) 제거.

**대상 모달 4종**:
1. **biz_item settings** (list + edit + save + sync) — 가장 복잡
2. **building manage** (Promise.allSettled 3단계 — delete/create/update)
3. **priority** (Promise.all rooms.update)
4. **room grade** (updateRoomGrades)

### 다루지 않는 것
- 모달 UI/디자인 — 변경 0
- 모달 안 useState (편집 중 임시 데이터) — 그대로
- Step #6b 외 페이지 — 변경 0

---

## 2. 변경 대상 코드 (요약 — 4개 mutation + 1 useQuery)

### 2-1. biz_item settings → useQuery (enabled) + 2 mutation

**Before**:
```tsx
const [bizItemSettingsList, setBizItemSettingsList] = useState<...>([]);
const [bizItemSaving, setBizItemSaving] = useState(false);
const [bizItemSyncing, setBizItemSyncing] = useState(false);

const loadBizItemSettings = useCallback(async () => {
  try { const res = await roomsAPI.getBizItems(); setBizItemSettingsList(res.data || []); setBizItemEdits({}); }
  catch { toast.error('상품 목록을 불러오지 못했습니다.'); }
}, []);

useEffect(() => { if (bizItemModalOpen) loadBizItemSettings(); }, [bizItemModalOpen, loadBizItemSettings]);

const handleBizItemSave = async () => {
  ...
  setBizItemSaving(true);
  try { await roomsAPI.updateBizItems(changes); toast.success(...); await loadBizItemSettings(); }
  catch { toast.error(...); } finally { setBizItemSaving(false); }
};

const handleBizItemSync = async () => {
  setBizItemSyncing(true);
  try { await roomsAPI.syncBizItems(); toast.success(...); await loadBizItemSettings(); }
  catch { toast.error(...); } finally { setBizItemSyncing(false); }
};
```

**After**:
```tsx
const bizItemSettingsQuery = useQuery<...[]>({
  queryKey: queryKeys.rooms.bizItems(),  // Step #6a 의 listing query 와 같은 key (캐시 공유)
  queryFn: () => roomsAPI.getBizItems().then(r => r.data || []),
  staleTime: 300_000,
  enabled: bizItemModalOpen,  // 모달 열림 시만 active (단 캐시 hit 면 즉시 표시)
});
const bizItemSettingsList = bizItemSettingsQuery.data ?? [];

// 모달 열릴 때마다 edits 초기화 (기존 동작 보존)
useEffect(() => {
  if (bizItemModalOpen) setBizItemEdits({});
}, [bizItemModalOpen]);

const saveBizItemMutation = useMutation({
  mutationFn: (changes: any[]) => roomsAPI.updateBizItems(changes),
  onSuccess: () => {
    toast.success('상품 설정이 저장되었습니다.');
    qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });  // room 의 biz_item_links_detail 도 갱신
  },
  onError: () => toast.error('상품 설정 저장에 실패했습니다.'),
});
const bizItemSaving = saveBizItemMutation.isPending;

const syncBizItemMutation = useMutation({
  mutationFn: () => roomsAPI.syncBizItems(),
  onSuccess: () => {
    toast.success('네이버 상품 동기화 완료');
    qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
  },
  onError: () => toast.error('네이버 상품 동기화에 실패했습니다.'),
});
const bizItemSyncing = syncBizItemMutation.isPending;

const handleBizItemSave = () => {
  const changes = Object.entries(bizItemEdits).map(([biz_item_id, edits]) => ({
    biz_item_id,
    ...edits,
    default_party_type: edits.default_party_type === '' ? null : edits.default_party_type,
  }));
  if (changes.length === 0) { setBizItemModalOpen(false); return; }
  saveBizItemMutation.mutate(changes);
};

const handleBizItemSync = () => syncBizItemMutation.mutate();
```

### 2-2. building manage → 1 mutation (Promise.allSettled 본체 유지)

**Before**:
```tsx
const [savingBuildings, setSavingBuildings] = useState(false);

const handleBuildingSaveAll = async () => {
  ... validation ...
  setSavingBuildings(true);
  try {
    // Stage 1~3 Promise.allSettled (삭제/생성/수정)
    ...
    if (failures.length > 0) { toast.error(...); window.__diagAction = ...; }
    else { toast.success(...); setBuildingManageOpen(false); }
    loadBuildings(); loadRooms();
  } catch (err) { toast.error(...); }
  finally { setSavingBuildings(false); }
};
```

**After**:
```tsx
const saveBuildingsMutation = useMutation({
  mutationFn: async (rows: BuildingEditRow[]) => {
    // Stage 1~3 동일 로직 — Promise.allSettled 본체 함수로 이동
    const deletedIds = rows.filter((r) => r._deleted && r.id !== null).map((r) => r.id!);
    const newRows = rows.filter((r) => r.id === null && !r._deleted);
    const updateRows = rows.filter((r) => {
      if (r.id === null || r._deleted) return false;
      const original = buildings.find((b) => b.id === r.id);
      return !!original && (original.name !== r.name.trim() || (original.description || '') !== r.description.trim());
    });
    const failures: string[] = [];
    if (deletedIds.length > 0) {
      const results = await Promise.allSettled(deletedIds.map(id => buildingsAPI.delete(id)));
      results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`삭제[id=${deletedIds[i]}]`); });
    }
    if (newRows.length > 0) {
      const results = await Promise.allSettled(newRows.map(row => buildingsAPI.create({ name: row.name.trim(), description: row.description.trim() })));
      results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`생성[${newRows[i].name}]`); });
    }
    if (updateRows.length > 0) {
      const results = await Promise.allSettled(updateRows.map(row => buildingsAPI.update(row.id!, { name: row.name.trim(), description: row.description.trim() })));
      results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`수정[${updateRows[i].name}]`); });
    }
    return failures;
  },
  onSuccess: (failures) => {
    if (failures.length > 0) {
      toast.error(`${failures.length}건 저장 실패: ${failures.join(', ')}. 다시 시도해주세요.`);
      window.__diagAction = `building_save_partial_failure_${failures.length}`;
    } else {
      toast.success('건물 저장 완료');
      setBuildingManageOpen(false);
    }
    qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
});
const savingBuildings = saveBuildingsMutation.isPending;

const handleBuildingSaveAll = () => {
  const visibleRows = buildingRows.filter((r) => !r._deleted);
  if (visibleRows.some((r) => !r.name.trim())) { toast.error('건물 이름을 입력하세요'); return; }
  saveBuildingsMutation.mutate(buildingRows);
};
```

### 2-3. priority → 1 mutation

**Before**:
```tsx
const [savingPriority, setSavingPriority] = useState(false);

const handlePrioritySave = async () => {
  setSavingPriority(true);
  try { ... await Promise.all(...) ...; toast.success(...); setPriorityOpen(false); loadRooms(); }
  catch { toast.error(...); } finally { setSavingPriority(false); }
};
```

**After**:
```tsx
const savePriorityMutation = useMutation({
  mutationFn: async (data: typeof priorityData) => {
    const roomLinks: Record<number, { biz_item_id: string; male_priority: number; female_priority: number }[]> = {};
    for (const [bizItemId, roomMap] of Object.entries(data)) {
      for (const [roomIdStr, prio] of Object.entries(roomMap)) {
        const roomId = Number(roomIdStr);
        if (!roomLinks[roomId]) roomLinks[roomId] = [];
        roomLinks[roomId].push({ biz_item_id: bizItemId, male_priority: prio.male_priority, female_priority: prio.female_priority });
      }
    }
    await Promise.all(Object.entries(roomLinks).map(([roomIdStr, links]) =>
      roomsAPI.update(Number(roomIdStr), { biz_item_links: links })
    ));
  },
  onSuccess: () => {
    toast.success('배정 순서 저장 완료');
    setPriorityOpen(false);
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
});
const savingPriority = savePriorityMutation.isPending;

const handlePrioritySave = () => savePriorityMutation.mutate(priorityData);
```

### 2-4. room grade → 1 mutation

**Before**:
```tsx
const [roomGradeSaving, setRoomGradeSaving] = useState(false);

const handleRoomGradeSave = async () => {
  const items = ...;  // diff 계산
  if (items.length === 0) { setRoomGradeModalOpen(false); return; }
  setRoomGradeSaving(true);
  try { await roomsAPI.updateRoomGrades(items); toast.success(...); await loadRooms(); setRoomGradeModalOpen(false); }
  catch { toast.error(...); } finally { setRoomGradeSaving(false); }
};
```

**After**:
```tsx
const saveRoomGradeMutation = useMutation({
  mutationFn: (items: { id: number; grade: number }[]) => roomsAPI.updateRoomGrades(items),
  onSuccess: () => {
    toast.success('객실 등급이 저장되었습니다.');
    setRoomGradeModalOpen(false);
    qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
  },
  onError: (err: any) => toast.error(err?.response?.data?.detail ?? '객실 등급 저장에 실패했습니다.'),
});
const roomGradeSaving = saveRoomGradeMutation.isPending;

const handleRoomGradeSave = () => {
  const items = Object.entries(roomGradeEdits)
    .map(([id, grade]) => ({ id: Number(id), grade }))
    .filter(({ id, grade }) => {
      const orig = rooms.find(r => r.id === id);
      return orig && orig.grade !== grade;
    });
  if (items.length === 0) { setRoomGradeModalOpen(false); return; }
  saveRoomGradeMutation.mutate(items);
};
```

### 2-5. Step #6a 의 helper 제거

```tsx
// 제거 대상
const loadRooms = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
const loadBuildings = () => qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
const loadBizItems = () => qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
```

→ 모달 함수들이 직접 `qc.invalidateQueries` 호출하므로 helper 불필요.

### 2-6. 제거 대상

- `bizItemSettingsList` useState (useQuery 로 대체)
- `loadBizItemSettings` useCallback (useQuery 로 대체, 단 modal open → setBizItemEdits({}) useEffect 분리 유지)
- `bizItemSaving`, `bizItemSyncing`, `savingBuildings`, `savingPriority`, `roomGradeSaving` useState (mutation.isPending 으로)

---

## 3. queryKey 결정

| API | queryKey | staleTime | 비고 |
|-----|----------|----------|------|
| `roomsAPI.getBizItems()` (modal 안) | `queryKeys.rooms.bizItems()` | 300s | Step #6a 의 bizItemsQuery 와 같은 key → 캐시 공유 |
| 모든 mutation 후 invalidate | `rooms.all()`, `rooms.bizItems()`, `buildings.list()` | — | mutation 별로 영향 받는 카테고리 |

**중요**: bizItemSettingsQuery 와 bizItemsQuery 가 같은 queryKey (`rooms.bizItems()`) → React Query 가 단일 캐시 entry 공유. 둘 다 같은 데이터 표시. 일관성 보장.

---

## 4. 동작 동등성 / 의도된 변화 (압축)

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | bizItem modal 열기 | useEffect → fetch | useQuery enabled 활성화 → fetch (캐시 hit 시 즉시) | 🔵 |
| 2 | bizItem 저장 | updateBizItems + 모달 안 list 다시 fetch | mutation + invalidate bizItems + rooms.all | 🔵 (Step #6a 의 bizItemsQuery 도 자동 갱신) |
| 3 | bizItem 동기화 | syncBizItems + list refetch | mutation + invalidate bizItems + rooms.all | 🔵 |
| 4 | 건물 일괄 저장 (성공) | Promise.allSettled + loadBuildings + loadRooms | mutation onSuccess invalidate buildings + rooms.all | ⚪ (의미 동등) |
| 5 | 건물 일괄 저장 (부분 실패) | toast.error + diag tag + loadBuildings | mutation onSuccess (failures 반환) + 동일 처리 | ⚪ |
| 6 | 건물 일괄 저장 (네트워크 에러) | catch toast | onError toast | ⚪ |
| 7 | priority 저장 | Promise.all + loadRooms | mutation + invalidate rooms.all | ⚪ |
| 8 | room grade 저장 (변경 없음) | items.length===0 → 모달 close | 동일 (mutate 호출 전 가드) | ⚪ |
| 9 | room grade 저장 (변경 있음) | updateRoomGrades + loadRooms | mutation + invalidate rooms.all | ⚪ |
| 10 | 모달 안 작업 진행 중 더블 클릭 | await 만 보호 | isPending 으로 버튼 disabled (기존 disabled 패턴 보존) | ⚪ |
| 11 | bizItemModalOpen → 닫기 → 다시 열기 | 매번 fetch | enabled false → 다시 true 시 캐시 hit | 🔵 |
| 12 | helper 제거 후 다른 함수 영향 | N/A | 다른 함수 (handleSubmit/confirmDelete/reorder) 가 helper 안 씀 (직접 invalidate) | ⚪ |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1: bizItemSettingsQuery 와 bizItemsQuery 의 캐시 공유**
- 둘 다 `queryKeys.rooms.bizItems()` 사용
- React Query: 같은 key 의 query 가 여러 컴포넌트에 있으면 캐시 공유 + 한 곳에서 fetch
- 동작: bizItemsQuery 가 active (Step #6a, 페이지 진입 시 fetch). bizItemSettingsQuery 가 enabled (모달 열림). 같은 key → 같은 data
- **판정**: 의도된 동작. 일관성 ↑.

**⚠️ 후보 2: helper 제거 시점**
- 본 PR 머지 시 helper 삭제 + 모든 호출처 직접 invalidate
- 단위로 본 PR 안에서 같이 처리 → safe
- **판정**: 단위 PR 단순화.

**⚠️ 후보 3: bizItem modal 의 edits reset useEffect**
- Before: loadBizItemSettings 안에서 `setBizItemEdits({})`
- After: 별도 useEffect `if (bizItemModalOpen) setBizItemEdits({})`
- 차이: useQuery refetch 시 edits 안 비워짐 (Before 는 비움)
- 영향: 모달 열려있는 동안 query refetch 발생 (window focus 등) — 사용자가 편집 중 edits 가 비워지면 작업 손실
- **판정**: After 가 사용자 친화적 (편집 보존). 단 fresh data 받아 화면 표시 (rendered list) 는 자동 갱신.

**⚠️ 후보 4: handleBuildingSaveAll 의 mutation 안 buildings 참조**
- mutation 안에서 `buildings.find(...)` — closure 로 capture 된 buildings (useQuery data) 사용. mutation 실행 시점의 buildings 일치.
- React Query 의 data 가 stable reference → closure 의 buildings 가 최신. 단 mutation 호출과 query refetch 사이 약간의 race 가능 — 사용자가 그동안 buildings 안 건드림 (모달 안에 있음). 안전.
- **판정**: 동등.

---

## 5. 영향받지 않음 경로

```
backend/                                # 변경 0
frontend/src/lib/queryKeys.ts           # 그대로
frontend/src/services/api.ts            # 동일
frontend/src/pages/RoomAssignment*      # 변경 0 (cross-invalidate 이미 Step #6a 에서 설정됨)
frontend/src/pages/ (RoomSettings 외)   # 영향 없음
```

검증: `git diff main -- frontend/src/pages/ backend/` = RoomSettings.tsx 한 파일.

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] diff: RoomSettings.tsx 1 파일, ~120 lines 치환
- [ ] helper 3개 (loadRooms/loadBuildings/loadBizItems) 완전 제거
- [ ] 모든 mutation 의 invalidate 범위 명시
- [ ] 수동 검증:
  - [ ] bizItem 모달 — 열기/편집/저장/sync 모두 작동
  - [ ] 건물 모달 — 추가/수정/삭제 + Undo + 일괄 저장 + 부분 실패 처리
  - [ ] priority 모달 — 저장 + UI 갱신
  - [ ] room grade 모달 — 변경 없을 때 close + 변경 시 저장

---

## 7. 후속 의존성

- **마지막 RoomSettings step** — Step #7 (Templates) 와 무관
- **모든 cross-invalidate 검증** — Step #6a + #6b 합쳐서 모든 RoomAssignment 동기화 시나리오 작동

---

## 8. 결정 사항

- [x] **bizItemSettingsQuery enabled** — modal 열림 시만 active
- [x] **bizItemSettingsQuery + bizItemsQuery 캐시 공유** — 같은 queryKey
- [x] **bizItem edits reset → 별도 useEffect** (refetch 시 보존)
- [x] **building manage → 1개 mutation** (Promise.allSettled 본체는 mutationFn 안으로)
- [x] **helper 3개 본 PR 에서 제거** (호출처 직접 invalidate)

---

## 9. 머지 후 다음 액션

1. 커밋
2. Step #7 (Templates) — 가장 큰 페이지 (2522줄, 64 state)
