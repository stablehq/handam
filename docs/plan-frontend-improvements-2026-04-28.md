# 프론트엔드 개선 계획안 (2026-04-28)

이 문서는 RoomAssignment + 전체 frontend 검증 결과를 바탕으로 수립한 변경 계획안입니다. 코드 변경은 아직 적용되지 않았으며, 본 문서는 codex 리뷰용으로 작성되었습니다.

## 배경

`frontend/src` 19개 파일에 대해 architect 에이전트로 사이드이펙트·중복·반응형·다크모드를 검증한 결과 🔴 보안 1건, 🟠 운영 사고 가능 8건, 🟡 다수가 발견됨. RoomAssignment.tsx + PartyCheckin.tsx 는 별도 검증되어 본 계획에서는 제외.

이미 별도 검증 사이클(architect)을 통해 각 변경안에 대해 사이드이펙트·대안·롤백 가능성을 점검했고, **3건 재검토(#3 작업 불필요, #14 제안 부적절, #5 진단 오류) + 7건 수정 후 진행 + 13건 진행 OK** 로 분류됨.

전체 묶음을 5개 phase 로 나누어 진행 예정. 본 문서는 그 plan 자체를 리뷰 대상으로 함.

---

## Phase 1: 보안 + 자잘 UX 개선 (예상 2시간)

### 1.1 Login.tsx — 평문 비밀번호 저장 제거 🔴 보안

**현재**: `Login.tsx:45` 에서 "로그인 정보 기억" 체크 시 `localStorage.setItem('sms-saved-credentials', JSON.stringify({username, password}))`. XSS / 공용 PC / 브라우저 확장에서 비밀번호 평문 노출 위험.

**변경**:
- 비밀번호 저장 제거. username 만 저장.
- 자동 로그인은 기존 refresh token 기반(`api.ts:67`, `auth-store.ts:21-33` 의 `loadFromStorage()`) 그대로 유지.
- 기존 사용자 데이터 마이그레이션: `localStorage` 의 `sms-saved-credentials` 에서 password 필드만 strip 하는 1회성 코드를 `App.tsx` mount 시 실행.

**검증된 사이드이펙트**: 기존 사용자의 저장된 자동 입력은 username 만 남으므로, 다음 방문 시 비번을 다시 입력해야 함. UX 약간 저하지만 보안 우선.

### 1.2 Settings.tsx — 두 fetch 의 loading state race 🟠

**현재**: `Settings.tsx:42-78` 에서 `fetchStatus` 와 `fetchUnstableStatus` 가 같은 `setLoading(false)` 를 finally 에서 호출. 빠른 쪽이 끝나면 늦은 쪽이 진행 중인데도 UI 가 "로딩 완료" 로 표시.

**변경**: 둘을 `Promise.all` 로 묶고 단일 `setLoading` 으로 감쌈. (분리하는 옵션도 있으나, 지금 UI 가 단일 스피너 사용이라 묶는 게 더 단순.)

### 1.3 Layout.tsx — TenantSwitcher 바깥 클릭 닫기 🟠

**현재**: `Layout.tsx:148-220` 의 테넌트 드롭다운이 외부 클릭으로 안 닫힘. collapsed/expanded 두 분기 모두 해당.

**변경**: 신규 `useClickOutside(ref, handler)` 커스텀 훅 추출 → TenantSwitcher 양쪽 분기에 적용. 이 훅은 #1.4 와도 공유.

### 1.4 GuestContextMenu.tsx — 자체 닫기 + onClose 누락 수정 🟠

**현재**:
- `GuestContextMenu.tsx:24` 에서 `onClose` prop 정의되지만 `line 27-45` destructuring 에서 누락 → dead code.
- 메뉴 자체에 Escape / 외부 클릭 핸들러 없음. 부모(`RoomAssignment.tsx`) 의 backdrop 으로만 닫힘.

**변경**:
- `onClose` destructuring 에 추가하는 선행 작업.
- `useClickOutside` (1.3 과 공유) + `useEffect` 로 `keydown` Escape 리스너 추가 → onClose 호출.
- 주의: 컴포넌트가 `createPortal` 로 body 에 렌더링됨(`line 144`). palette submenu(`line 186-219`) 가 별도 portal 위치에 있을 경우 outside click 판정에서 잘못 잡힐 수 있음 — `menuRef.contains` 체크에서 palette 영역도 포함되도록 ref 범위 신중히 설계.

### 1.5 App.tsx — 404 catch-all 라우트 🟢

**변경**: `App.tsx:43-74` 의 `<Routes>` 안에 `<Route path="*" element={<NotFound />} />` 추가. NotFound 컴포넌트 신규 생성 (한 화면, "페이지를 찾을 수 없음 [메인]"). 인증 후 route 안에 둠 — 미인증 404 는 ProtectedRoute 가 /login 으로 리다이렉트.

### 1.6 SalesReport.tsx — 다크모드 하드코딩 정리 🟢

**현재**: `SalesReport.tsx:389-410` 의 `<tr>` 에 `style={{background:'#F8F9FB'}}` 인라인 9곳 반복. 다크모드에서 그대로 라이트 회색.

**변경**: 9곳 공통 className 변수 `DETAIL_ROW_BG = "bg-[#F8F9FB] dark:bg-[#2C2C34]"` 로 추출 → `<tr className={DETAIL_ROW_BG}>` 패턴.

### 1.7 UserManagement.tsx — 역할/상태 색 다크 가독성 🟢

**현재**: `UserManagement.tsx:29-38` 의 `ROLE_COLORS`, `STATUS_COLORS` 가 hex 문자열 객체. `line 212, 217` 에서 `style={{color: ROLE_COLORS[role]}}` 인라인 사용 → `dark:` variant 적용 불가.

**변경**: hex 객체 → Tailwind 클래스 객체 (`{ staff: 'text-[#8B95A1] dark:text-[#B0B8C1]' }`). 인라인 style → className 바인딩. STATUS_COLORS 도 같은 패턴으로 수정.

---

## Phase 2: 운영 안정 (예상 2시간)

### 2.1 services/api.ts — refresh 실패 시 페이지 강제 리로드 제거 🟠

**현재**: `api.ts:73, 104` 에서 토큰 갱신 실패 / 인증 만료 시 `window.location.href = '/login'`. 풀 페이지 리로드로 작성 중 폼 / 메모 다 손실.

**변경 (검증 후 수정안)**:
- navigate 함수 주입 패턴 대신 **`useAuthStore.getState().logout()` 호출** + 기존 `ProtectedRoute` 가 `isAuthenticated=false` 감지하여 자동으로 /login 으로 리다이렉트하는 흐름 활용.
- 결합도 낮고 (axios 모듈에 React Router 주입 안 해도 됨), 이미 존재하는 메커니즘 재사용.
- 옵션: toast.error('세션이 만료되었습니다') 로 사용자에 알림.

**남는 risk**: `logout()` 이 store 만 갱신하고 즉시 컴포넌트 트리 리렌더가 일어나야 ProtectedRoute 가 동작. React 18 batching 안에서 안전.

### 2.2 ActivityLogs.tsx — 검색어 디바운스 🟠

**현재 진단 정정**: 처음에는 "자동 fetch 가 안 됨" 으로 판단했으나 architect 재검토 결과 **이미 자동 fetch 동작 중**. `loadLogs` useCallback 의 deps 에 `searchQuery` 가 있어 searchQuery 변경 → loadLogs 재생성 → useEffect(`[loadLogs]`) 발동.

**진짜 문제**: 키스트로크마다 즉시 fetch — 빠르게 타이핑 시 서버 부담.

**변경**: `useDeferredValue` 또는 `debouncedSearch` state(300ms) 추가. `loadLogs` deps 는 디바운스된 값 사용.

### 2.3 main.tsx — ErrorBoundary 추가 🟢

**현재**: `main.tsx:7-15` 에 Sentry 동적 import 있지만 ErrorBoundary 없음. React 미처리 에러 시 화이트아웃.

**변경 (검증 후 수정안)**:
- 직접 ErrorBoundary 클래스 컴포넌트 작성 대신 **`@sentry/react` 의 `Sentry.ErrorBoundary`** 사용. init 타이밍 자체 체크가 내장.
- Sentry 가 optional 이라 fallback ErrorBoundary 클래스도 병행 (Sentry DSN 없을 때).
- `<ErrorBoundary fallback={<ErrorFallback/>}>App</ErrorBoundary>` 구조.

### 2.4 Templates.tsx — 모달 모바일 키보드 가림 🟡

**현재**: `Templates.tsx:1233` `<Modal className="h-[75vh]">` 고정 높이.

**변경**: `vh` 대신 `dvh` (dynamic viewport height) 사용 → `max-h-[calc(100dvh-100px)]`. iOS 키보드 올라와도 모달 콘텐츠가 키보드에 가리지 않음.

---

## Phase 3: 인증/테넌트 인프라 — 묶음 처리 필수 (예상 3시간)

⚠️ 이 phase 의 3개 항목은 **반드시 함께 진행**. 키 변경 마이그레이션 일관성 때문.

### 3.1 auth-store.ts ↔ api.ts — 토큰 이중 진실 정리 🟠

**현재**: 토큰이 Zustand store + localStorage 양쪽에 저장됨. `api.ts:12, 67, 94-95` 가 localStorage 직접 read/write. 동기화 어긋날 가능성.

**변경 (검증 후 수정안)**:
- Zustand `persist` middleware 도입.
- **마이그레이션 함수 필수**: `persist({ migrate, version: 2 })` 옵션으로 기존 키 (`sms-token`, `sms-refresh-token`, `sms-user`) 를 읽어 새 단일 키로 변환 후 기존 키 삭제. 이걸 안 하면 운영 중 모든 사용자가 강제 로그아웃됨.
- `api.ts` 의 interceptor 가 토큰 갱신 시 `useAuthStore.getState().setTokens(...)` 호출로 store 경유 갱신 → persist 가 자동으로 localStorage 동기화.
- localStorage 직접 read/write 코드 모두 제거.

### 3.2 auth-store.ts — 다중 탭 동기화 🟢

**변경**: `window.addEventListener('storage', ...)` 로 다른 탭의 logout 감지 → 자기 탭도 store.logout() 호출.

**주의**: storage 이벤트는 변경한 탭에서는 발화 안 함(브라우저 스펙). 자기 탭 로그아웃은 기존 logout() 함수로 처리.

**의존성**: 3.1 과 같이 진행 — 키 이름이 달라지므로 단독 구현 시 재작업 필요.

### 3.3 tenant-store.ts — 하드코딩 fallback + 검증 🟢

**현재**:
- `tenant-store.ts:35` 에서 API 실패 시 `currentTenantId = '1'` 강제 fallback.
- `line 26-29` stored ID 가 응답 list 에 있는지 검증 없음 (지워진 테넌트 ID 가 그대로 남을 수 있음).

**변경 (검증 후 수정안)**:
- `loadTenants` 응답 받은 후: stored ID 가 list 에 있으면 사용, 없으면 `list[0]?.id`, list 도 비어있으면 `null`.
- 실패 시 toast 만 표시하고 강제 fallback 제거.
- **null 가드 동반 추가 필수**: `currentTenantId=null` 일 때 `api.ts` interceptor 가 `X-Tenant-Id` 헤더 못 박음 → 백엔드 `get_tenant_scoped_db()` 가 실패. ProtectedRoute 또는 interceptor 에 null 가드 추가해서 전체 앱 동작 불능 방지.
- 옵션: null 일 때 "테넌트 선택 불가" 안내 화면.

---

## Phase 4: 견고성 (예상 2시간)

### 4.1 RoomSettings.tsx — 빌딩 일괄 저장 부분 실패 🟠

**현재**: `RoomSettings.tsx:404-419` 에서 삭제 → 생성 → 수정 순서로 순차 await. 중간 실패 시 부분 저장.

**변경 (검증 후 수정안)**:
- 단순 `Promise.allSettled` 가 아니라 **단계별 allSettled** (삭제 단계 일괄 → 생성 단계 일괄 → 수정 단계 일괄) — 순서 의존성 보존.
- 각 단계 후 실패 항목 toast 보고. 부분 저장은 그대로 (롤백 안 함, 사용자가 인지하고 재시도).
- 장기 권장: 백엔드 `PUT /api/buildings/batch` 트랜잭션 엔드포인트 (이번 phase 에선 보류).

### 4.2 RoomSettings.tsx — 드래그 시 N개 동시 PUT → 1회 🟡

**현재**: `RoomSettings.tsx:510, 523-525` 에서 드래그 한 번에 `Promise.all` 로 모든 객실 sort_order 병렬 PUT.

**변경**:
- 백엔드 신규 엔드포인트 `PUT /api/rooms/reorder` (`{ order: [room_id 배열] }` 받음, 트랜잭션 내 일괄 갱신).
- 기존 `PUT /api/rooms/{id}` 는 유지 (다른 update 용).
- 프론트는 1번 호출로 단순화.
- 주의: 다른 사용자와 동시 편집 race — 트랜잭션 + 마지막 쓰기 우선.

### 4.3 Templates.tsx — 드래그 race condition 🟡

**현재**: `Templates.tsx:699-716` 옵티미스틱 + 실패 시 `fetchTemplates()` 롤백. 빠른 재드래그 시 응답 순서 꼬임.

**변경 (검증 후 수정안)**:
- `boolean` state 보다 `useRef<boolean>` 가드 — 리렌더 없이 진행 중 체크.
- 진행 중에 새 드래그 시작하면 `toast.info('처리 중')` + 무시.

### 4.4 TableSettingsModal.tsx — 색상 팝업 stale 위치 🟡

**현재 진단 정정**: 처음에는 relative/absolute 자식으로 변경 제안했으나, **검증 결과 부적절**.
- 이유: 색상 팝업은 `createPortal` 사용 중 (`line 539, 542-545`). Portal 의 목적은 "modal 의 `overflow:hidden` 회피". relative 로 바꾸면 그 문제 부활.

**변경 (검증 후 수정안)**:
- Portal 유지.
- `ResizeObserver` 또는 `@floating-ui/react` 로 위치 동적 추적.
- 모달 body scroll 시 popup 좌표 자동 갱신.
- 작업: ResizeObserver 가 더 가벼움 (라이브러리 추가 없음). 단, scroll 이벤트 + 모달 close 시 cleanup 신경.

### 4.5 Layout.tsx — 헤더 복붙 정리 🟡

**현재**: `Layout.tsx:463-489` (admin) vs `515-541` (staff) 헤더가 ~30줄씩 거의 복붙. `handleLogout` 도 양쪽 정의.

**변경**:
- 공통 `HeaderActions` 컴포넌트 추출 (ThemeToggle, logout, user badge).
- 차이는 좌측 영역뿐 (admin: MobileSidebar, staff: S 로고) → props 분기.
- `handleLogout` 단일 정의로 통일.

---

## Phase 5: 장기 정리 (별도 작업, 예상 8~10시간)

### 5.1 services/api.ts — `any` 남발 🟡

**현재**: API 함수 시그니처에 `data: any` 다수 (line 121, 135, 169, 233, 247, 248).

**변경 (검증 후 수정안)**:
- 가성비 순서: `roomsAPI.update` (다양한 필드 조합) → `reservationsAPI.create/update` (핵심 비즈니스) → `templatesAPI.update` → buildings/auth (필드 적음).
- 기존 `Create` 타입의 `Partial<>` 래핑이 가장 효율적.
- openapi-typescript 자동 생성은 별도 결정 (FastAPI OpenAPI JSON → TS 타입).

### 5.2 Templates.tsx — 2,470줄 분리 🟡

**변경 (검증 후 수정안)**:
- **2단계 접근**:
  1. `useTemplatesPage()` 커스텀 훅 추출 (상태 + 핸들러). 이 단계로 prop drilling 회피 사전 차단.
  2. 컴포넌트 분리:
     ```
     pages/Templates/
     ├── index.tsx (탭 컨테이너, App.tsx import 호환)
     ├── TemplatesTab.tsx
     ├── SchedulesTab.tsx
     ├── TemplateEditModal.tsx
     ├── ScheduleEditModal.tsx
     └── shared/VariablePicker.tsx
     ```
- import path: `pages/Templates.tsx` → `pages/Templates/index.tsx` 자동 해석. `App.tsx:13` 수정 불필요.
- 의존성 많음: `templatesAPI`, `templateSchedulesAPI`, `buildingsAPI`, `reservationsAPI`, `useTenantStore` — 훅으로 묶어서 깔끔히.

---

## 작업하지 않을 항목

다음 검증 결과 사용자가 명시적으로 제외:

- **모바일 테이블 가로 스크롤** (`overflow-x-auto`): ActivityLogs/Reservations/RoomSettings 12컬럼 테이블 — **현재 PC 전용 사용 시나리오라 의도된 동작**. 변경 안 함.
- **PartyCheckin.tsx**: 모바일 STAFF 전용 페이지. 본 검증 범위에서 제외.
- **RoomAssignment.tsx**: 별도 검증 사이클로 처리 완료. 본 계획에서 제외.

---

## 실행 순서 권장

1. **Phase 1** (보안 1건 + UX 6건) — 가성비 가장 높음. 한 번에 commit + 배포.
2. **Phase 2** (운영 안정 4건) — 별도 commit.
3. **Phase 3** (인증/테넌트 묶음) — 마이그레이션 동반, 단일 commit 으로. 배포 후 운영 모니터링 필요.
4. **Phase 4** (견고성) — 백엔드 reorder 엔드포인트 신설 포함, 풀 스택 수정.
5. **Phase 5** (장기) — 별도 작업으로 시간 날 때.

---

## 리뷰 요청 사항

본 문서를 codex 가 코드 리뷰 관점으로 검토 시:

1. **Phase 별 의존성 / 충돌** — 묶음 처리 필요 항목이 빠지지 않았는지 (예: 3.1 + 3.2 + 3.3)
2. **마이그레이션 안전성** — 특히 #3.1 의 zustand persist migrate 함수가 운영 중 사용자에 영향 없는지
3. **누락된 사이드이펙트** — architect 검증에서 놓친 부분
4. **더 단순한 대안** — 본 계획에서 over-engineered 인 항목
5. **Phase 1 / 2 / 3 의 작업 순서가 적절한지** — 어느 phase 를 먼저 묶는 게 합리적인지
