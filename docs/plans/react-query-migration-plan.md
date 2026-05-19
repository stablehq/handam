# React Query 통일 — 단계 분해 계획

> 작성일: 2026-05-19
> 상태: 사용자 검토 대기
> 부모 설계: [react-query-migration-design.md](./react-query-migration-design.md)

---

## 원칙

1. **기존 의도된 동작 보존** — 어떤 사용자 가시 동작도 마이그레이션으로 변하면 안 됨. 예외: §"의도된 변화" 명시한 항목 (캐시/invalidation 으로 인한 UX 개선).
2. **각 단계는 별도 PR + 별도 사전조사 문서** — `docs/plans/react-query-step-NN-<slug>.md`.
3. **각 사전조사 문서에 Before/After 라인 인용 + 동작 동등성 근거 + 시나리오 매트릭스 + 코너케이스 명시**.
4. **각 단계는 직전 단계와 독립** — 단계 #N 롤백해도 시스템 동작 (예외: step #1 인프라는 후속 모든 step 의존성).
5. **백엔드 코드 변경 0** — 본 작업 전 범위 frontend 전용.

---

## 의도된 동작 변화 (= 해결 대상)

설계안 §5 참조. 4가지:

| # | 시나리오 | 해결 효과 |
|---|---------|----------|
| 1 | 같은 페이지 재방문 시 매번 서버 호출 | staleTime 캐시로 즉시 표시 |
| 2 | Mutation 후 관련 화면 수동 새로고침 필요 | invalidateQueries 로 자동 갱신 |
| 3 | 페이지마다 fetch 패턴 다름 (학습/유지 비용) | 동일 훅 패턴 통일 |
| 4 | useEffect deps 회귀 위험 (reload 가 가려줌) | queryKey 자동 의존 → 영구 차단 |

---

## 단계 분해 (총 9개)

⚪ = 동작 변화 없음 (인프라/리팩토링) / 🔵 = 의도된 변화 (UX/캐시 개선) / ⚫ = 정리.

### Step #1 — 인프라: queryKeys.ts 보강 ⚪

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| `queryKeys.ts` 에 8개 카테고리 추가 (dashboard, activityLogs, salesReport, partyHosts, partyCheckin, buildings, 기존 reservations/rooms/templates 메서드 확장) | `frontend/src/lib/queryKeys.ts` | 추가 ~40 lines |

**동작 동등성**: 어떤 페이지도 새 key 를 아직 사용 안 함 (선언만). 모든 SELECT/render 동작 동일.

**사전조사**: `react-query-step-01-querykeys-expansion.md`

---

### Step #2 — Dashboard 마이그레이션 🔵

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| `Dashboard.tsx` 의 2개 useEffect+useState fetch 를 useQuery 2개로 교체 | `frontend/src/pages/Dashboard.tsx` | 치환 ~30 lines |

**의도된 변화**: 페이지 재방문 시 staleTime 30s 이내 캐시 즉시 표시.

**복잡도**: 🟢 단순 — mutation 없음, 의존성 단순. **본보기 step**.

**사전조사**: `react-query-step-02-dashboard.md`

---

### Step #3 — ActivityLogs 마이그레이션 🔵

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| 3개 useEffect (검색/필터/loadStats) → 2개 useQuery + `useDebouncedValue` | `frontend/src/pages/ActivityLogs.tsx` | 치환 ~50 lines |
| (필요 시) `useDebouncedValue` hook 신규 | `frontend/src/hooks/useDebouncedValue.ts` (신규) | 추가 ~15 lines |

**의도된 변화**: 검색어 debounce + 필터 변경 시 자동 캐시 분리. mutation 없음 (read-only 페이지).

**코너케이스**:
- `useCallback(loadLogs, deps)` 의 deps 순환 → useQuery 로 옮기면 자동 해결
- 검색어 즉시 입력 시 thrash → debounce 200~300ms

**사전조사**: `react-query-step-03-activitylogs.md`

---

### Step #4 — SalesReport 마이그레이션 🔵

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| sales-report GET + partyHosts CRUD 를 useQuery + useMutation 3개로 교체 | `frontend/src/pages/SalesReport.tsx` | 치환 ~80 lines |
| **cross-category invalidation 도입** — partyHost create/delete 후 `salesReport.report()` 도 invalidate (현재 누락 — UX 개선) | 동상 | 추가 ~5 lines |

**의도된 변화**:
- 매출 기간 변경 시 캐시 키 분리
- partyHost 추가/삭제 후 매출 표 자동 갱신 (현재는 수동 새로고침 필요)

**코너케이스**:
- date_from/date_to 가 queryKey 에 포함 → 기간별 캐시 다수 (gcTime 5min 적정)
- partyHost CRUD 의 optimistic update 여부 — Simple 채택 (UX 부담 낮음)

**사전조사**: `react-query-step-04-salesreport.md`

---

### Step #5 — Reservations 마이그레이션 🔵

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| 5개 endpoint + 페이지네이션 + 필터 6개 → 1 useQuery (filters 객체 key) + 4 mutation | `frontend/src/pages/Reservations.tsx` | 치환 ~150 lines |

**의도된 변화**:
- 필터 조합별 캐시 분리 → 같은 필터 재방문 시 즉시 표시
- create/update/delete 후 `reservations.all()` invalidate → 모든 페이지/필터 자동 갱신
- syncNaver 후 전체 invalidate

**코너케이스**:
- **🔴 캐시 폭발** — 필터 6개 + page = 수십 조합. gcTime 짧게 (5min, 기본 유지) + staleTime 30s 적정.
- **🔴 RoomAssignment 의 reservations.list(date) 와 cross-invalidate** — create/update 후 둘 다 무효화 필요. `reservations.all()` 가 그 역할.
- **🟡 검색어 debounce** — searchQuery 변경 시 즉시 fetch 회피.

**사전조사**: `react-query-step-05-reservations.md`

---

### Step #6 — RoomSettings 분할 마이그레이션 🔵

가장 복잡 (1427줄, 27 state, 4 모달). **분할 권장**:

#### Step #6a — RoomSettings 기본 (rooms 목록 + CRUD)

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| `rooms.list()` + create/update/delete/reorder → useQuery + useMutation | `frontend/src/pages/RoomSettings.tsx` | 치환 ~100 lines |

**코너케이스**:
- **🔴 RoomAssignment 의 `queryKeys.rooms.list()` 와 공유 캐시** — 객실 변경 시 두 페이지 모두 invalidate 필요. queryKey 동일 사용으로 자동 처리.
- **🟡 DnD reorder** — Optimistic 적용 (UX). 실패 시 원복.

#### Step #6b — RoomSettings 모달 4종

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| biz_items / 건물 / room grade 모달의 fetch + mutation → 모달별 useQuery (`enabled: modalOpen`) + useMutation | `frontend/src/pages/RoomSettings.tsx` | 치환 ~150 lines |

**코너케이스**:
- **🟡 모달 닫고 다시 열 때 fresh data** — `enabled: modalOpen` + invalidation on close (또는 `staleTime: 0`).
- **🟡 건물 일괄 작업** (`Promise.allSettled` 으로 다수 create/update/delete) — 한 mutation 으로 묶기 vs 각각 mutation. **단순화 위해 한 mutation 으로 묶고 마지막에 invalidate**.

**사전조사**: `react-query-step-06a-roomsettings-basic.md`, `react-query-step-06b-roomsettings-modals.md`

---

### Step #7 — Templates 마이그레이션 🔵

가장 큰 페이지 (2522줄, 64 state). 단일 step 으로 진행 (복잡도 높지만 modal 분할이 어려운 구조).

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| 4개 fetch (templates/schedules/variables/buildings/customTypes) → 5개 useQuery + 다수 mutation | `frontend/src/pages/Templates.tsx` | 치환 ~200 lines |

**코너케이스**:
- **🔴 64 state** — 대부분 폼 입력 state (query 아님). query 대상 정확히 식별 후 분리.
- **🟡 template + schedule 간 의존** — schedule mutation 후 template invalidate 도 필요? 확인.
- **🟡 sample examples** (`loadSampleExamples`) — 사용자 클릭 시 호출 (lazy). useQuery 의 `enabled` + `refetch` 또는 useMutation 으로.

**사전조사**: `react-query-step-07-templates.md`

---

### Step #8 — PartyCheckin 마이그레이션 🔵

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| 8개 endpoint (partyCheckin/sales/host/auction/review/invites/partyHosts/reservations) → useQuery 다수 + mutation 다수 | `frontend/src/pages/PartyCheckin.tsx` | 치환 ~200 lines |

**코너케이스**:
- **🟡 탭 전환** — sales 탭 활성 시만 sales fetch (`enabled: activeTab === 'sales'`).
- **🟡 hasUnstable 분기** — `getList(date, 'unstable')` 조건부 호출 (`enabled: hasUnstable`).
- **🟡 다수 모달** — invite editing / sales create / cancel checkin 등. 각 mutation 의 invalidation 범위 정확히.
- **🟡 partyCheckin.toggle** — Optimistic 적용 (UX, 체크박스 즉시 반응 필요).

**사전조사**: `react-query-step-08-partycheckin.md`

---

### Step #9 — (선택) CI lint / 회귀 방지 ⚪

| 작업 | 변경 파일 | 코드 변경량 |
|------|----------|------------|
| 새 페이지가 `useEffect + await api.xxx()` 옛 패턴으로 회귀 못 하게 ESLint custom rule 또는 grep 기반 lint | `.eslintrc` 또는 `scripts/lint-react-query.sh` | 추가 ~30 lines |

**선택 사항**. 미래에 새 페이지 만들 때 자동 차단. (직전 사고와 다른 종류의 회귀 방지)

**사전조사**: `react-query-step-09-ci-lint.md` (선택)

---

## 단계간 의존성

```
Step #1 (인프라) ──┬─→ Step #2 (Dashboard)         ────┐
                  ├─→ Step #3 (ActivityLogs)       ────┤
                  ├─→ Step #4 (SalesReport)        ────┤
                  ├─→ Step #5 (Reservations)       ────┤
                  ├─→ Step #6a (RoomSettings 기본) ────┤
                  ├─→ Step #6b (RoomSettings 모달) ──→─┤ (6b 는 6a 이후)
                  ├─→ Step #7 (Templates)          ────┤
                  └─→ Step #8 (PartyCheckin)       ────┘
                                                       │
                                                       ▼
                                              (선택) Step #9 (CI lint)
```

- **Step #1 은 모든 후속의 선행 의존성** — 다른 step 들이 신규 queryKey 카테고리 참조
- **Step #2~#8 은 서로 독립** — 어떤 순서로도 진행 가능. 권장 순서: 단순→복잡 (Dashboard→ActivityLogs→SalesReport→Reservations→RoomSettings→Templates→PartyCheckin)
- **롤백 안전성**: 각 step 롤백 시 해당 페이지만 옛 방식으로 복귀. 다른 페이지 무관.

---

## 사전조사 문서 템플릿 (mutator-step-01 양식 그대로)

각 step 별로 `docs/plans/react-query-step-NN-<slug>.md` 생성. 8 섹션 권장:

```markdown
# 단계 N: <페이지명> React Query 마이그레이션

## 1. 목적
- 다루는 것 / 다루지 않는 것 매트릭스

## 2. 변경 대상 코드
### 2-1. 페이지명.tsx — fetch 부분
**Before** (현재 useEffect+useState):
```tsx
...
```
**After** (useQuery):
```tsx
...
```

### 2-2. 페이지명.tsx — mutation 부분
(반복)

## 3. queryKey 결정 — 라인 단위
- 새 카테고리 정의 (Step #1 의 어떤 key 사용)
- staleTime / gcTime 결정 근거

## 4. 동작 동등성 / 의도된 변화
- 시나리오 매트릭스 (12~20개)
- ⚪/🔵/⚠️ 분류

## 5. 영향받지 않음 경로 (다른 페이지 / 백엔드)

## 6. 검증 체크리스트
- syntax / TS 타입 / dev server 시각 검증 / 회귀 시나리오 5건

## 7. 후속 의존성

## 8. 결정 보류 / 머지 후 다음 액션
```

---

## 미결 검토 항목

설계안 §6 미결 항목 일부 — 본 step 사전조사에서 결정:

- [ ] **테넌트 전환 reload 제거** — 본 계획 §비범위. 후속 별도 PR 권장. 모든 page step 완료 후 검토.
- [ ] **CI lint (Step #9)** — 선택 사항. 사용자 결정 필요.
- [ ] **Optimistic update 범위** — 본 계획에서 PartyCheckin.toggle + RoomSettings DnD reorder 만 Optimistic. 다른 곳은 Simple. 추가 후보 있는지 step 사전조사에서 검토.

---

## 다음 액션

1. 본 분해안 + 설계안 검토 합의
2. Step #1 사전조사 (`react-query-step-01-querykeys-expansion.md`) 작성
3. Step #1 코드 변경 PR → 머지
4. Step #2 (Dashboard, 본보기) 사전조사 + 코드 → 머지
5. Step #3~#8 순차 진행 (각 사전조사 + 검토 + 코드 + 머지)
6. (선택) Step #9 CI lint
