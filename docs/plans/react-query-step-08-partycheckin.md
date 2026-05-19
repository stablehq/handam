# 단계 #8 사전조사 — PartyCheckin 페이지 React Query 마이그레이션 (마지막 단일 페이지)

> 부모: [react-query-migration-plan.md](./react-query-migration-plan.md) §"Step #8"
> 분류: 🔵 의도된 변화 (캐시 + toggle Optimistic)
> 변경 규모: 1개 파일, 치환 ~200 lines
> 선행: Step #1~#7 머지됨

---

## 1. 목적

PartyCheckin 의 2개 fetch 함수 (fetchGuests, fetchSalesData) + 다수 mutation (toggle/add/delete/upsert) 를 React Query 통일. **마지막 단일 페이지 step** — fix 시리즈 종결.

### 다루는 것

- **Queries** (8개):
  - guests stable: `partyCheckin.guests(date, 'stable')`
  - guests unstable: `partyCheckin.guests(date, 'unstable')` (enabled: hasUnstable)
  - sales: `partyCheckin.sales(date)` (enabled: activeTab === 'sales')
  - host: `partyCheckin.host(date)` (enabled: activeTab === 'sales' && canManageHost)
  - auction: `partyCheckin.auction(date)` (enabled: 같음)
  - review: `partyCheckin.review(date)` (enabled: 같음)
  - invites: `partyCheckin.invites(date)` (enabled: 같음)
  - partyHosts: `partyHosts.list()` (enabled: canManageHost)
- **Mutations**:
  - partyCheckin.toggle → useMutation **Optimistic** (UX 중요)
  - reservationsAPI.create (게스트 추가) → useMutation
  - onsiteSalesAPI.create / delete → useMutation
  - dailyHostAPI.upsert / dailyReviewAPI.upsert / onsiteAuctionAPI.upsert → handleCardSave 통합 mutation
  - onsiteFemaleInviteAPI.create / update / delete → 별도 mutation

### 다루지 않는 것

- UI/Modal state (addModal/cancelModal/deleteModal) — 그대로
- form input state (newItemName/newAmount/hostName 등) — 그대로
- pendingInvites/editedInvites/inviteEditing 등 편집 state — 그대로

---

## 2. 변경 대상 코드 (압축)

### 2-1. import + qc

```tsx
import { useState, useEffect } from 'react';   // useCallback 제거
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/queryKeys';
...
const qc = useQueryClient();
```

### 2-2. Guests queries (stable + unstable)

```tsx
const guestsStableQuery = useQuery<PartyGuest[]>({
  queryKey: queryKeys.partyCheckin.guests(selectedDate, 'stable'),
  queryFn: () => partyCheckinAPI.getList(selectedDate, 'stable').then(r => r.data),
  staleTime: 30_000,
});
const guestsUnstableQuery = useQuery<PartyGuest[]>({
  queryKey: queryKeys.partyCheckin.guests(selectedDate, 'unstable'),
  queryFn: () => partyCheckinAPI.getList(selectedDate, 'unstable').then(r => r.data),
  staleTime: 30_000,
  enabled: hasUnstable,
});
const guests = guestsStableQuery.data ?? [];
const unstableGuests = guestsUnstableQuery.data ?? [];
const loading = guestsStableQuery.isFetching || guestsUnstableQuery.isFetching;

useEffect(() => {
  if (guestsStableQuery.error || guestsUnstableQuery.error)
    toast.error('파티 예약자 목록을 불러오지 못했습니다');
}, [guestsStableQuery.error, guestsUnstableQuery.error]);
```

### 2-3. Sales tab queries (enabled: activeTab === 'sales')

```tsx
const salesActive = activeTab === 'sales';

const salesQuery = useQuery<Sale[]>({
  queryKey: queryKeys.partyCheckin.sales(selectedDate),
  queryFn: () => onsiteSalesAPI.getList(selectedDate).then(r => r.data ?? []),
  staleTime: 30_000,
  enabled: salesActive,
});
const sales = salesQuery.data ?? [];
const salesLoading = salesQuery.isFetching;

const hostQuery = useQuery<any>({
  queryKey: queryKeys.partyCheckin.host(selectedDate),
  queryFn: () => dailyHostAPI.get(selectedDate).then(r => r.data),
  staleTime: 30_000,
  enabled: salesActive && canManageHost,
});
const auctionQuery = useQuery<any>({
  queryKey: queryKeys.partyCheckin.auction(selectedDate),
  queryFn: () => onsiteAuctionAPI.get(selectedDate).then(r => r.data),
  staleTime: 30_000,
  enabled: salesActive && canManageHost,
});
const reviewQuery = useQuery<any>({
  queryKey: queryKeys.partyCheckin.review(selectedDate),
  queryFn: () => dailyReviewAPI.get(selectedDate).then(r => r.data),
  staleTime: 30_000,
  enabled: salesActive && canManageHost,
});
const invitesQuery = useQuery<InviteRow[]>({
  queryKey: queryKeys.partyCheckin.invites(selectedDate),
  queryFn: () => onsiteFemaleInviteAPI.list(selectedDate).then(r => r.data ?? []),
  staleTime: 30_000,
  enabled: salesActive && canManageHost,
});

const invites = invitesQuery.data ?? [];

// 기존 fetchSalesData 의 동기화 효과 (hostName/auction*/reviewCount/inviteEditing/pendingInvites/editedInvites/cardEditing 초기화)
// — useEffect 로 변환. 데이터 로드 완료 시 form state 초기화.
useEffect(() => {
  if (!salesActive || !canManageHost) return;
  if (hostQuery.isFetching || auctionQuery.isFetching || reviewQuery.isFetching || invitesQuery.isFetching) return;

  const host = hostQuery.data;
  const fetchedHost = host?.host_username ?? '';
  setHostName(fetchedHost);

  const auc = auctionQuery.data;
  setAuction(auc);
  if (auc) {
    setAuctionItemName(auc.item_name);
    setAuctionAmount(String(auc.final_amount));
    setAuctionWinner(auc.winner_name);
    setAuctionPaymentMethod((auc.payment_method as PaymentMethod) ?? '카드');
  } else {
    setAuctionItemName(''); setAuctionAmount(''); setAuctionWinner(''); setAuctionPaymentMethod('카드');
  }

  const rev = reviewQuery.data;
  setReviewCount(rev ? String(rev.count) : '');
  setCardEditing(!fetchedHost && !auc && !rev);

  const fetchedInvites = invitesQuery.data ?? [];
  const editingMode = fetchedInvites.length === 0;
  setInviteEditing(editingMode);
  setPendingInvites(editingMode ? [{ tempId: Date.now() + Math.random(), host: '', count: '' }] : []);
  setEditedInvites({});
}, [
  salesActive, canManageHost, selectedDate,
  hostQuery.data, auctionQuery.data, reviewQuery.data, invitesQuery.data,
  hostQuery.isFetching, auctionQuery.isFetching, reviewQuery.isFetching, invitesQuery.isFetching,
]);
```

**중요**: 기존 fetchSalesData 의 부수효과 (hostName / auction* / reviewCount / cardEditing / inviteEditing / pendingInvites / editedInvites 초기화) 는 useEffect 로 분리. data 변경 시 자동 초기화 — query refetch 시도 동일 효과.

**위험**: data 변경 시마다 hostName 등 form state 가 초기화됨. 사용자가 편집 중이면 입력 사라질 수 있음. 단 사용자가 편집 모드 (`cardEditing=true`) 진입 후엔 같은 selectedDate 에서 데이터 변경 trigger 없음 (mutation 이 query invalidate 하면 발생하지만 — invalidate 후 새 데이터로 form 재 초기화는 의도된 동작).

### 2-4. partyHosts query (모달용)

```tsx
const partyHostsQuery = useQuery<any[]>({
  queryKey: queryKeys.partyHosts.list(),
  queryFn: () => partyHostsAPI.list().then(r => r.data ?? []),
  staleTime: 300_000,
  enabled: canManageHost,
});
const hosts = partyHostsQuery.data ?? [];

// 기존: useEffect on [canManageHost] — useQuery enabled 로 대체
```

### 2-5. Toggle mutation (Optimistic)

```tsx
const toggleMutation = useMutation({
  mutationFn: (guestId: number) => partyCheckinAPI.toggle(guestId, selectedDate),
  onMutate: async (guestId) => {
    await qc.cancelQueries({ queryKey: queryKeys.partyCheckin.guests(selectedDate, 'stable') });
    const previousStable = qc.getQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'stable'));
    const previousUnstable = qc.getQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'unstable'));
    // optimistic toggle
    const toggleIn = (arr: PartyGuest[] | undefined) =>
      arr?.map(g => g.id === guestId ? { ...g, checked_in: !g.checked_in, checked_in_at: g.checked_in ? null : new Date().toISOString() } : g);
    qc.setQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'stable'), (prev) => toggleIn(prev) ?? prev);
    qc.setQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'unstable'), (prev) => toggleIn(prev) ?? prev);
    return { previousStable, previousUnstable, guestId };
  },
  onError: (_err, _guestId, ctx) => {
    if (ctx?.previousStable !== undefined) qc.setQueryData(queryKeys.partyCheckin.guests(selectedDate, 'stable'), ctx.previousStable);
    if (ctx?.previousUnstable !== undefined) qc.setQueryData(queryKeys.partyCheckin.guests(selectedDate, 'unstable'), ctx.previousUnstable);
    toast.error('처리 중 오류가 발생했습니다');
  },
  onSuccess: (res, guestId, _ctx) => {
    // 서버 응답으로 정확한 값 반영 (optimistic + 서버 일치 보장)
    const { checked_in, checked_in_at } = res.data;
    const sync = (arr: PartyGuest[] | undefined) =>
      arr?.map(g => g.id === guestId ? { ...g, checked_in, checked_in_at } : g);
    qc.setQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'stable'), (prev) => sync(prev) ?? prev);
    qc.setQueryData<PartyGuest[]>(queryKeys.partyCheckin.guests(selectedDate, 'unstable'), (prev) => sync(prev) ?? prev);
    // toast — 기존: guest.customer_name 사용. mutation 안에선 guest 정보 X — context 통해 또는 별도 args
    // 단순화: 토스트 호출은 호출처(doToggle wrapper)에서.
  },
});
const toggling = toggleMutation.isPending ? toggleMutation.variables : null;

const doToggle = (guest: PartyGuest) => {
  toggleMutation.mutate(guest.id, {
    onSuccess: (res) => {
      const { checked_in } = res.data;
      toast.success(`${guest.customer_name}님 입장 ${checked_in ? '완료' : '취소'}`);
    },
  });
};
```

### 2-6. Add guest (예약자 추가) mutation

```tsx
const addGuestMutation = useMutation({
  mutationFn: async (vars: { payload: any; immediateCheckin: boolean }) => {
    const res = await reservationsAPI.create(vars.payload);
    if (vars.immediateCheckin) {
      try { await partyCheckinAPI.toggle(res.data.id, selectedDate); } catch { /* 입장 실패도 추가는 성공 */ }
    }
    return res;
  },
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.guests(selectedDate, 'stable') });
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.guests(selectedDate, 'unstable') });
    qc.invalidateQueries({ queryKey: queryKeys.reservations.all() });
  },
  onError: () => toast.error('게스트 추가에 실패했습니다'),
});
```

### 2-7. Sales add/delete mutations

```tsx
const addSaleMutation = useMutation({
  mutationFn: (vars: { item_name: string; amount: number; payment_method: PaymentMethod }) =>
    onsiteSalesAPI.create({ date: selectedDate, ...vars }),
  onSuccess: () => {
    setNewItemName(''); setNewAmount(''); setNewPaymentMethod('카드');
    toast.success('판매 기록이 추가되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.sales(selectedDate) });
  },
  onError: () => toast.error('판매 기록 추가에 실패했습니다'),
});

const deleteSaleMutation = useMutation({
  mutationFn: (id: number) => onsiteSalesAPI.delete(id),
  onSuccess: () => {
    toast.success('판매 기록이 삭제되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.sales(selectedDate) });
  },
  onError: () => toast.error('삭제에 실패했습니다'),
  onSettled: () => setDeleteModal({ open: false, id: null, name: '' }),
});
```

### 2-8. Card save mutation (host + review + auction 통합)

```tsx
const cardSaveMutation = useMutation({
  mutationFn: async () => {
    const promises: Promise<unknown>[] = [];
    promises.push(dailyHostAPI.upsert({ date: selectedDate, host_username: hostName }));
    if (reviewCount !== '' && !isNaN(Number(reviewCount)) && Number(reviewCount) >= 0) {
      promises.push(dailyReviewAPI.upsert({ date: selectedDate, count: Number(reviewCount) }));
    }
    if (auctionAmount !== '' && !isNaN(Number(auctionAmount)) && Number(auctionAmount) >= 0) {
      promises.push(onsiteAuctionAPI.upsert({
        date: selectedDate,
        item_name: auctionItemName.trim() || '경매',
        final_amount: Number(auctionAmount),
        winner_name: auctionWinner.trim() || '-',
        payment_method: auctionPaymentMethod,
      }));
    }
    await Promise.all(promises);
  },
  onSuccess: () => {
    setCardEditing(false);
    toast.success('저장되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.host(selectedDate) });
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.auction(selectedDate) });
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.review(selectedDate) });
    qc.invalidateQueries({ queryKey: queryKeys.salesReport.all() });  // 매출 보고서도 영향
  },
  onError: () => toast.error('저장에 실패했습니다'),
});
const cardSaving = cardSaveMutation.isPending;

const handleCardSave = () => {
  if (!hostName) { toast.error('진행자를 선택해주세요'); return; }
  cardSaveMutation.mutate();
};
```

### 2-9. Female invite mutations (create / update / delete)

기존 `handleInviteSave`, `handleSavedInviteSave`, `handleSavedInviteDelete` 등을 useMutation 으로:

```tsx
const inviteSaveMutation = useMutation({
  mutationFn: async (vars: { creates: any[]; updates: { id: number; data: any }[] }) => {
    await Promise.all([
      ...vars.creates.map(c => onsiteFemaleInviteAPI.create({ date: selectedDate, ...c })),
      ...vars.updates.map(u => onsiteFemaleInviteAPI.update(u.id, u.data)),
    ]);
  },
  onSuccess: () => {
    toast.success('저장되었습니다');
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.invites(selectedDate) });
    qc.invalidateQueries({ queryKey: queryKeys.salesReport.all() });  // 매출 보고서도 영향
  },
  onError: () => toast.error('저장에 실패했습니다'),
});
const inviteSaving = inviteSaveMutation.isPending;

const deleteInviteMutation = useMutation({
  mutationFn: (id: number) => onsiteFemaleInviteAPI.delete(id),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: queryKeys.partyCheckin.invites(selectedDate) });
    qc.invalidateQueries({ queryKey: queryKeys.salesReport.all() });
  },
});
```

### 2-10. 제거 대상

- `[guests, setGuests]`, `[unstableGuests, setUnstableGuests]`, `[loading, setLoading]`, `[toggling, setToggling]` (toggleMutation.variables 로)
- `[sales, setSales]`, `[salesLoading, setSalesLoading]`
- `[hosts, setHosts]`, `[invites, setInvites]`, `[inviteSaving, setInviteSaving]`, `[cardSaving, setCardSaving]`
- `fetchGuests`, `fetchSalesData` useCallback
- 3개 useEffect (fetchGuests/fetchSalesData/partyHosts.list) — useQuery enabled 로 대체

---

## 3. queryKey + invalidation

| Mutation | invalidate |
|----------|------------|
| toggle | (optimistic 직접 setQueryData; 별도 invalidate 안 함 — 서버 응답 sync 로 충분) |
| add guest | `partyCheckin.guests(date, 'stable')` + `'unstable'` + `reservations.all()` |
| add sale | `partyCheckin.sales(date)` |
| delete sale | `partyCheckin.sales(date)` |
| card save | `partyCheckin.host/auction/review(date)` + `salesReport.all()` |
| invite save/delete | `partyCheckin.invites(date)` + `salesReport.all()` |

**Cross-invalidate to SalesReport**: cardSave 와 invite 변경이 매출 보고서에 영향 → `salesReport.all()` 도 invalidate.

---

## 4. 동작 동등성 / 의도된 변화 (압축)

| # | 시나리오 | Before | After | 판정 |
|---|---------|--------|-------|------|
| 1 | 첫 로드 (checkin 탭) | fetchGuests → 2 fetch | 2 useQuery (stable + enabled unstable) | ⚪ |
| 2 | sales 탭 진입 | fetchSalesData → 4-5 fetch | 4-5 useQuery enabled 활성화 → fetch | ⚪ |
| 3 | sales → checkin → sales (재진입) | 매번 fetch | 30s 이내 캐시 hit | 🔵 |
| 4 | selectedDate 변경 | fetchGuests + fetchSalesData (if sales tab) | queryKey 변경 → 자동 fetch | ⚪ |
| 5 | 입장 토글 (성공) | partyCheckin.toggle + setGuests 부분 갱신 | optimistic + onSuccess sync | ⚪ (UX 동등) |
| 6 | 입장 토글 (실패) | toast error | optimistic onError 원복 + toast | 🔵 (원복 추가) |
| 7 | 게스트 추가 | reservationsAPI.create + (option) toggle + fetchGuests | mutation + invalidate guests + reservations.all | 🔵 (RoomAssignment/Reservations 도 자동 갱신) |
| 8 | 판매 추가 | sales [res.data, ...prev] (optimistic-like) | mutation + invalidate sales | ⚠️ optimistic 손실 — 서버 응답 후 fetch 으로 갱신. UX 약간 다름. |
| 9 | 판매 삭제 | sales prev.filter (optimistic-like) | mutation + invalidate | ⚠️ optimistic 손실 |
| 10 | 카드 저장 (host + review + auction) | Promise.all + setCardEditing(false) | mutation + invalidate 3개 카테고리 + salesReport.all | 🔵 SalesReport 자동 갱신 |
| 11 | invite 저장 | Promise.all + reload | mutation + invalidate invites + salesReport | 🔵 |
| 12 | 카드 저장 후 hostName/auction 등 form 초기화 | fetchSalesData 가 처리 | invalidate → 새 fetch → useEffect 가 form 초기화 | ⚪ |

### 4-1. 잠재 사이드이펙트

**⚠️ 후보 1: sales 추가/삭제 optimistic 손실**
- Before: `setSales(prev => [res.data, ...prev])` (성공 후 즉시 추가 — optimistic-like)
- After: invalidate 만 → 서버 응답 후 fetch → 약간 지연 (네트워크 round-trip)
- 차이: 사용자가 추가 버튼 누르면 list 가 즉시 갱신 vs 200~500ms 후 갱신
- **결정**: Simple 채택 (Optimistic 추가는 복잡). UX 차이 작음.

**⚠️ 후보 2: hostName/auction* form 초기화 useEffect 의 deps 폭발**
- 12개 deps. data + isFetching 모두 포함
- 단 React Query 의 data 는 stable reference (구조 같으면). isFetching 은 boolean. 변경 시만 발화.
- **위험**: refetchOnWindowFocus 발생 시 isFetching: true → false → useEffect 두 번 발화. form 초기화 두 번 — 사용자가 편집 중이면 입력 손실 가능.
- **해결**: cardEditing=false 일 때만 동기화 (편집 중이면 초기화 안 함)
```tsx
useEffect(() => {
  if (!salesActive || !canManageHost) return;
  if (cardEditing) return;  // 편집 중이면 동기화 안 함 (편집 보호)
  ...
}, [...]);
```
- 단 첫 로드 시 (cardEditing 초기값 true 라면 안 됨)... cardEditing 의 의미: 데이터 있으면 false, 없으면 true.
- 더 명확한 해결: useEffect 안에서 비교 후 변경 시만 setState. 또는 ref 로 한 번만 초기화.
- **결정**: 단순화 위해 useEffect deps 그대로 + cardEditing 가드 추가.

**⚠️ 후보 3: toggleMutation.variables 가 toggling state 대체**
- Before: setToggling(id) 명시
- After: `toggleMutation.isPending ? toggleMutation.variables : null` — variables 는 mutate 호출 시 인자 (guestId)
- 단 isPending 이 false 되어도 variables 가 잠깐 남을 수 있음. React Query 가 reset 처리.
- **판정**: 동등.

**⚠️ 후보 4: handleCardSave 의 setAuction 호출**
- Before: onsiteAuctionAPI.upsert().then(res => setAuction(res.data))
- After: invalidate → useQuery refetch → useEffect 로 form 동기화
- 차이: 약간의 지연 (network round-trip). UX 차이 작음.

---

## 5. 영향받지 않음 경로

```
backend/, frontend/src/lib/, frontend/src/services/, RoomAssignment 등 다른 페이지
```

cross-invalidate 영향:
- guests/sales invalidate → 이 페이지만
- card/invite 변경 → SalesReport (cross-page sync, 의도)

---

## 6. 검증 체크리스트

- [ ] TS / build / lint
- [ ] diff: PartyCheckin.tsx 1 파일, ~200 lines
- [ ] useCallback import 제거
- [ ] 수동 검증:
  - [ ] checkin 탭 — guests 표시 + 토글 동작 (optimistic — 즉시 반응, 실패 시 원복)
  - [ ] sales 탭 진입 — sales/host/auction/review/invites 로드
  - [ ] 게스트 추가 + 즉시 입장 옵션
  - [ ] 판매 추가/삭제
  - [ ] 카드 저장 — host + review + auction 동시
  - [ ] invite 추가/수정/삭제
  - [ ] selectedDate 변경 — 모든 데이터 새 date 로
  - [ ] 카드 저장 후 SalesReport 자동 갱신 (cross-invalidate)

---

## 7. 후속

- **Phase 1 종결** — 모든 페이지 React Query 통일 완료
- (선택) reload 제거 별도 PR — 사용자가 별도 PR 결정

---

## 8. 결정 사항

- [x] **partyCheckin.toggle Optimistic** — UX 중요 (즉시 반응)
- [x] **sales 탭 enabled 분기** — 활성 시만 fetch
- [x] **hasUnstable / canManageHost 조건부 query** — enabled 패턴
- [x] **card save / invite 변경 → salesReport.all invalidate** — cross-page sync
- [x] **form state 동기화 useEffect** — cardEditing 가드 (편집 중 보호)
- [x] **sales add/delete Simple** — Optimistic 안 함 (UX 차이 작음, 복잡도 ↓)
