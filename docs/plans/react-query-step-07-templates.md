# 단계 #7 사전조사 — Templates 페이지 React Query 마이그레이션

> 부모: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #7"
> 분류: 🔵 의도된 변화 (캐시 + cross-invalidate)
> 변경 규모: 1개 파일 (2522줄), 치환 ~200 lines
> 선행: Step #1~#6b 머지됨

---

## 1. 목적

Templates 의 5개 fetch + 7개 mutation 을 React Query 통일. **가장 큰 페이지 (64 state)** — query 대상과 form/UI state 정확히 분리.

### 다루는 것

- 5 useQuery: `templates.list`, `templateSchedules.list`, `templates.variables`, `buildings.list`, `templateSchedules.customTypes`
- 7 useMutation: template create/update (통합), template delete, template reorder (optimistic), schedule create/update (통합), schedule delete, schedule run, sample examples (lazy)
- schedule preview 는 useState + 직접 호출 유지 (단발성 fetch + 모달 표시)
- buildings.list 는 RoomSettings 와 같은 queryKey → 캐시 공유

### 다루지 않는 것

- Form/UI state (template form 28개, schedule form 30개 등) — 그대로
- 64개 state 중 query 대상 (templates/schedules/availableVariables/buildings/customTypeOptions/sampleExamples) 외 모두 그대로
- 검색/필터 (없음 — 단순 list 표시)

---

## 2. 변경 대상 코드 (압축)

### 2-1. import

**Before**: `import React, { useState, useEffect, useRef } from 'react';`
**After**: `import React, { useState, useEffect, useRef } from 'react';` (useRef 유지 — reorderingRef 가드용)
+ `import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';`
+ `import { queryKeys } from '@/lib/queryKeys';`

### 2-2. 5 useQuery (init useEffect 대체)

```tsx
const qc = useQueryClient();

const templatesQuery = useQuery<Template[]>({
  queryKey: queryKeys.templates.list(),
  queryFn: () => templatesAPI.getAll().then(r => r.data),
  staleTime: 300_000,
});
const templates = templatesQuery.data ?? [];
const loadingTemplates = templatesQuery.isFetching;

const schedulesQuery = useQuery<TemplateSchedule[]>({
  queryKey: queryKeys.templateSchedules.list(),
  queryFn: () => templateSchedulesAPI.getAll().then(r => r.data),
  staleTime: 30_000,  // 실행 결과 자주 갱신
});
const schedules = schedulesQuery.data ?? [];
const loadingSchedules = schedulesQuery.isFetching;

const variablesQuery = useQuery<any>({
  queryKey: queryKeys.templates.variables(),
  queryFn: () => templatesAPI.getAvailableVariables().then(r => r.data),
  staleTime: 600_000,  // 정적 데이터
});
const availableVariables = variablesQuery.data ?? null;

const buildingsQuery = useQuery<Building[]>({
  queryKey: queryKeys.buildings.list(),  // RoomSettings 와 공유
  queryFn: () => buildingsAPI.getAll().then(r => r.data),
  staleTime: 300_000,
});
const buildings = buildingsQuery.data ?? [];

const customTypesQuery = useQuery<any[]>({
  queryKey: queryKeys.templateSchedules.customTypes(),
  queryFn: () => templateSchedulesAPI.getCustomTypes().then(r => r.data),
  staleTime: Infinity,  // 시스템 상수 (tenant-agnostic)
});
const customTypeOptions = customTypesQuery.data ?? [];

// 기존 useEffect [fetchTemplates(), fetchSchedules(), fetchAvailableVariables(), fetchBuildings(), customTypes] 제거
// (useEffect 가 init 만 했었고, 그 함수 본체도 다 제거)

// Error logging (Step #2 패턴)
useEffect(() => { if (templatesQuery.error) { console.error(templatesQuery.error); toast.error('템플릿 목록을 불러오지 못했습니다'); } }, [templatesQuery.error]);
useEffect(() => { if (schedulesQuery.error) { console.error(schedulesQuery.error); toast.error('스케줄 목록을 불러오지 못했습니다'); } }, [schedulesQuery.error]);
```

### 2-3. Template mutations (3개)

```tsx
const invalidateTemplates = () => {
  qc.invalidateQueries({ queryKey: queryKeys.templates.all() });
  qc.invalidateQueries({ queryKey: queryKeys.templateSchedules.list() });  // schedule 의 template_id 표시 갱신
};

const saveTemplateMutation = useMutation({
  mutationFn: ({ id, data }: { id: number | null; data: any }) =>
    id != null ? templatesAPI.update(id, data) : templatesAPI.create(data),
  onSuccess: (_, vars) => {
    toast.success(vars.id != null ? '템플릿이 수정되었습니다' : '템플릿이 생성되었습니다');
    setTemplateDialogOpen(false);
    invalidateTemplates();
  },
  onError: (err: any) => toast.error(err.response?.data?.detail ?? '템플릿 저장 실패'),
});
const savingTemplate = saveTemplateMutation.isPending;

const deleteTemplateMutation = useMutation({
  mutationFn: (id: number) => templatesAPI.delete(id),
  onSuccess: () => {
    toast.success('템플릿이 삭제되었습니다');
    invalidateTemplates();
  },
  onError: (err: any) => toast.error(err.response?.data?.detail ?? '템플릿 삭제 실패'),
  onSettled: () => setDeleteTemplateTarget(null),
});

// Template reorder — Optimistic (기존 setTemplates 와 동등). reorderingRef 가드 유지.
const reorderTemplatesMutation = useMutation({
  mutationFn: (ids: number[]) => templatesAPI.reorder(ids),
  onMutate: async (ids) => {
    await qc.cancelQueries({ queryKey: queryKeys.templates.list() });
    const previous = qc.getQueryData<Template[]>(queryKeys.templates.list());
    qc.setQueryData<Template[]>(queryKeys.templates.list(), (prev) => {
      if (!prev) return prev;
      const map = new Map(prev.map(t => [t.id, t]));
      return ids.map(id => map.get(id)).filter(Boolean) as Template[];
    });
    return { previous };
  },
  onError: (err: any, _vars, ctx) => {
    if (ctx?.previous) qc.setQueryData(queryKeys.templates.list(), ctx.previous);
    toast.error(err.response?.data?.detail ?? '순서 저장 실패');
  },
  onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.templates.list() }),
});

const handleSaveTemplate = () => {
  ... validation 보존 ...
  const data = {...};
  saveTemplateMutation.mutate({ id: editingTemplate?.id ?? null, data });
};

const handleDeleteTemplate = (t: Template) => deleteTemplateMutation.mutate(t.id);

const handleDragEnd = (event: DragEndEvent) => {
  const { active, over } = event;
  if (!over || active.id === over.id) return;
  if (reorderingRef.current) {
    toast.info('이전 변경이 처리 중입니다. 잠시 후 다시 시도해주세요.', { id: 'template-reorder-busy' });
    return;
  }
  const oldIndex = templates.findIndex(t => t.id === active.id);
  const newIndex = templates.findIndex(t => t.id === over.id);
  if (oldIndex < 0 || newIndex < 0) return;
  const reordered = arrayMove(templates, oldIndex, newIndex);

  reorderingRef.current = true;
  reorderTemplatesMutation.mutate(
    reordered.map(t => t.id),
    { onSettled: () => { reorderingRef.current = false; } }
  );
};
```

### 2-4. Schedule mutations (3개) + preview (단순 fetch 유지)

```tsx
const saveScheduleMutation = useMutation({
  mutationFn: ({ id, payload }: { id: number | null; payload: any }) =>
    id != null ? templateSchedulesAPI.update(id, payload) : templateSchedulesAPI.create(payload),
  onSuccess: (_, vars) => {
    toast.success(vars.id != null ? '스케줄이 수정되었습니다' : '스케줄이 생성되었습니다');
    setScheduleDialogOpen(false);
    qc.invalidateQueries({ queryKey: queryKeys.templateSchedules.list() });
  },
  onError: (err: any) => toast.error(err.response?.data?.detail ?? '스케줄 저장 실패'),
});
const savingSchedule = saveScheduleMutation.isPending;

const deleteScheduleMutation = useMutation({
  mutationFn: (id: number) => templateSchedulesAPI.delete(id),
  onSuccess: () => {
    toast.success('스케줄이 삭제되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.templateSchedules.list() });
  },
  onError: (err: any) => toast.error(err.response?.data?.detail ?? '스케줄 삭제 실패'),
  onSettled: () => setDeleteScheduleTarget(null),
});

const runScheduleMutation = useMutation({
  mutationFn: (id: number) => templateSchedulesAPI.run(id),
  onSuccess: (res) => {
    toast.success(`실행 완료: ${res.data.sent_count}명 발송, ${res.data.failed_count}명 실패`, { duration: 5000 });
    qc.invalidateQueries({ queryKey: queryKeys.templateSchedules.list() });
  },
  onError: () => toast.error('실행 실패'),
});

const handleSaveSchedule = () => {
  ... validation 보존 ...
  saveScheduleMutation.mutate({ id: editingSchedule?.id ?? null, payload: buildSchedulePayload() });
};
const handleDeleteSchedule = (s: TemplateSchedule) => deleteScheduleMutation.mutate(s.id);
const handleRunSchedule = (id: number) => {
  const tid = toast.loading('실행 중...');
  runScheduleMutation.mutate(id, {
    onSuccess: (res) => toast.success(`실행 완료: ${res.data.sent_count}명 발송, ${res.data.failed_count}명 실패`, { id: tid, duration: 5000 }),
    onError: () => toast.error('실행 실패', { id: tid }),
  });
};
// handlePreviewTargets — useState + 직접 fetch 유지 (단발성 + 모달 표시)
```

### 2-5. loadSampleExamples (lazy)

기존: `loadSampleExamples` 함수 — 직접 fetch + setState. 단발성 lazy.
After: 그대로 유지 (lazy + 단순 — mutation 으로 감쌀 가치 적음). 또는 useMutation 으로 변환.
**결정**: useMutation 으로 — 일관성 + isPending 활용.

```tsx
const loadSamplesMutation = useMutation({
  mutationFn: () => reservationsAPI.getAll({ limit: 20, status: 'confirmed' }),
  onSuccess: (res) => {
    const reservations = res.data.items ?? res.data;
    if (!reservations || reservations.length === 0) return;
    const pick = reservations[Math.floor(Math.random() * reservations.length)];
    setSampleExamples({...});
  },
});
const loadSampleExamples = () => loadSamplesMutation.mutate();
```

### 2-6. 제거 대상

- `[templates, setTemplates]`, `[schedules, setSchedules]`, `[buildings, setBuildings]`, `[availableVariables, setAvailableVariables]`, `[customTypeOptions, setCustomTypeOptions]` useState
- `[loadingTemplates, setLoadingTemplates]`, `[loadingSchedules, setLoadingSchedules]`, `[savingTemplate, setSavingTemplate]`, `[savingSchedule, setSavingSchedule]` useState
- 4개 fetch 함수 (fetchTemplates, fetchSchedules, fetchAvailableVariables, fetchBuildings) — useQuery 가 책임
- init useEffect

---

## 3. queryKey + invalidation

| API | queryKey | staleTime | invalidate by |
|-----|----------|----------|---------------|
| templatesAPI.getAll | `queryKeys.templates.list()` | 300s | Template CRUD/reorder |
| templateSchedulesAPI.getAll | `queryKeys.templateSchedules.list()` | 30s | Schedule CRUD/run, Template CRUD (template_id 표시) |
| templatesAPI.getAvailableVariables | `queryKeys.templates.variables()` | 600s | — (정적, 변경 없음) |
| buildingsAPI.getAll | `queryKeys.buildings.list()` | 300s | RoomSettings step #6b 의 building mutation |
| templateSchedulesAPI.getCustomTypes | `queryKeys.templateSchedules.customTypes()` | Infinity | — (시스템 상수) |

**buildings.list 캐시 공유**: RoomSettings 와 같은 queryKey → RoomSettings 에서 건물 변경 시 Templates 도 자동 갱신.

---

## 4. 동작 동등성 / 의도된 변화 (압축)

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 | 5 fetch 병렬 | 동일 | ⚪ |
| 2 | Template 추가/수정/삭제 | + fetchTemplates | mutation + invalidateTemplates() (templates + schedules) | 🔵 |
| 3 | Template reorder 성공 | setTemplates + reorder API (catch 시 fetchTemplates) | optimistic mutation (onMutate setQueryData, onError ctx.previous) | ⚪ |
| 4 | Template reorder 실패 | toast + fetchTemplates 롤백 | onError ctx.previous 로 원복 + toast | ⚪ |
| 5 | Template reorder 중 다시 드래그 | reorderingRef.current 가드 → toast.info | 동일 (ref 가드 유지) | ⚪ |
| 6 | Schedule 추가/수정/삭제 | + fetchSchedules | mutation + invalidate schedules | ⚪ |
| 7 | Schedule run (즉시 발송) | toast.loading + fetchSchedules | mutation + per-call onSuccess (toast.loading 동등) + invalidate | ⚪ |
| 8 | Schedule preview | 직접 fetch + setPreviewTargets + 모달 | 동일 (단발성, mutation 안 함) | ⚪ |
| 9 | sample examples | 직접 fetch + setState | useMutation (일관성) | ⚪ |
| 10 | buildings 변경 (RoomSettings) | 영향 없음 (Templates 의 buildings useState 가 stale) | Templates 의 buildings 자동 갱신 (cache share) | 🔵 |
| 11 | customTypes — staleTime Infinity | 매 마운트 fetch | 한 번만 fetch (Infinity) | 🔵 (서버 부하 ↓) |
| 12 | 페이지 재방문 | 매번 5 fetch | 캐시 hit (staleTime 가드) | 🔵 |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1: reorderingRef 가드**
- Before: 동기 ref 로 즉시 가드
- After: ref 유지 + mutation onSettled 에서 false
- **판정**: 동등. mutation 의 onError 도 onSettled 도 ref 해제 보장.

**⚠️ 후보 2: invalidateTemplates 가 schedules 도 invalidate**
- Template 변경 시 schedule 의 template_id 표시도 갱신해야 — 의도된 동작
- 추가 fetch 발생 (schedule list refetch). 무시 가능.

**⚠️ 후보 3: customTypes staleTime Infinity**
- 시스템 상수라 변경 없음. Infinity 안전.
- 단 백엔드 변경 시 frontend reload 까지 stale. **백엔드 customTypes 추가 시 사용자 reload 필요** (기존도 마찬가지).
- **판정**: 동등.

**⚠️ 후보 4: handleRunSchedule 의 toast.loading per-call**
- mutation 의 onSuccess 는 default 인데 mutate 호출 시 추가 callback 전달 (per-call). React Query 가 둘 다 호출.
- onSuccess: 1) default invalidate, 2) per-call toast 갱신
- onError: 1) default toast, 2) per-call toast 갱신
- **위험**: per-call toast 가 default toast 와 중복. → per-call 만 사용하도록 default 의 toast 제거 (단 invalidate 는 유지)
- **수정**: runScheduleMutation 의 default onSuccess 에 toast 제외 → invalidate 만. per-call 에 toast.

**⚠️ 후보 5: handleDeleteTemplate 의 setDeleteTemplateTarget(null) 시점**
- Before: finally 에서. 즉 성공/실패 무관.
- After: onSettled 에서. 동등.

---

## 5. 영향받지 않음

```
backend/, frontend/src/lib/queryKeys.ts, frontend/src/services/api.ts, 다른 pages (Templates 외)
```

RoomSettings 의 buildings.list cache 공유 — 이미 Step #6 머지된 상태. Templates 의 추가는 read-only consumer.

검증: `git diff main -- frontend/src/pages/ backend/` = Templates.tsx 한 파일.

---

## 6. 검증 체크리스트

- [ ] TS / build / lint 통과
- [ ] diff: Templates.tsx 1 파일, ~200 lines 치환
- [ ] 외부 영향 0
- [ ] 수동 검증:
  - [ ] 페이지 로드 → 5개 데이터 표시
  - [ ] Template 추가/수정/삭제 → 자동 갱신 (templates + schedules)
  - [ ] Template DnD reorder → optimistic + 실패 시 원복
  - [ ] reorder 진행 중 다시 드래그 → "처리 중" 토스트
  - [ ] Schedule 추가/수정/삭제 → 자동 갱신
  - [ ] Schedule run → toast.loading + 결과 toast + schedule list 갱신
  - [ ] Schedule preview → 모달 표시
  - [ ] Sample examples 버튼 → 무작위 예시 표시
  - [ ] 페이지 재방문 → 캐시 hit

---

## 7. 후속

- 마지막 단일 페이지 step 1개 남음 (Step #8 PartyCheckin)
- buildings.list cache share 검증 (RoomSettings 와)

---

## 8. 결정 사항

- [x] **buildings.list 캐시 공유** — RoomSettings 와 동일 queryKey
- [x] **customTypes staleTime Infinity** — 시스템 상수
- [x] **Template reorder Optimistic** + reorderingRef 가드 보존
- [x] **invalidateTemplates 도 schedules 포함** — schedule 의 template_id 표시 갱신
- [x] **Schedule preview useState 유지** — 단발성, mutation 가치 적음
- [x] **Sample examples useMutation 변환** — 일관성
- [x] **handleRunSchedule toast.loading per-call** — default onSuccess 에 toast 제외 (invalidate 만)
