# 단계 #2: InlineInput display span — focus → focus-visible 수정

> 작성일: 2026-05-16
> 단계: 2 / 11
> 섹션: A. 기초 인프라
> 동작 변화: 🔵 의도된 변화 — 우클릭 시 InlineInput 배경 활성화 버그 수정
> 부모 계획: [dndkit-migration-plan.md](./dndkit-migration-plan.md)

---

## 1. 목적

`InlineInput` display 모드 span의 background 클래스 prefix를 `focus:` → `focus-visible:` 로 교체.
우클릭 시 focus가 발생해 배경만 활성화되고 edit 모드는 진입 안 하는 기존 버그를 수정.

---

## 2. 변경 대상 코드

### 2-1. `frontend/src/pages/RoomAssignment/components/InlineInput.tsx:131`

**Before** (display 모드 span):
```tsx
className={`${compact ? '' : 'w-full block py-1.5'} text-body truncate select-none ${disabled ? '' : 'cursor-text'} outline-none focus:bg-[#F2F4F6] dark:focus:bg-[#2C2C34] focus:rounded ${className || ''}`}
```

**After**:
```tsx
className={`${compact ? '' : 'w-full block py-1.5'} text-body truncate select-none ${disabled ? '' : 'cursor-text'} outline-none focus-visible:bg-[#F2F4F6] dark:focus-visible:bg-[#2C2C34] focus-visible:rounded ${className || ''}`}
```

**변경 의도**:
- 우클릭 시 `:focus`는 매칭되지만 `:focus-visible`은 매칭 안 됨 → 배경 미활성, edit 미진입 ✓
- 키보드 Tab focus: `:focus`와 `:focus-visible` 모두 매칭 → 배경 활성 + onFocus가 `activate()` 호출 → edit 진입 ✓
- 동일 span의 `onFocus` 핸들러(L120-123)가 이미 `e.currentTarget.matches(':focus-visible')` 로 게이트 → 본 변경으로 시각/동작 일관성 확보

### 2-2. 변경하지 않음

- 동일 파일 L84 editing 모드 input의 `focus:bg-[#F2F4F6] focus:rounded focus:px-1 dark:focus:bg-[#2C2C34]` — input 요소는 마우스 클릭으로도 focus가 의도된 동작이라 `:focus-visible` 차이 없음. 유지.

---

## 3. 동작 동등성 / 의도된 변화

| 케이스 | 기존 | 변경 후 | 의도 |
|---|---|---|---|
| **키보드 Tab focus (PC/모바일)** | 배경 활성 + edit 진입 | 배경 활성 + edit 진입 | ✅ 동일 |
| **마우스 단일클릭 (PC/모바일)** | focus 안 됨 (span은 click default focus 없음) | 동일 | ✅ 동일 |
| **우클릭 (PC)** | `:focus` 매칭 → 배경 활성. `:focus-visible` 미매칭 → edit 미진입. **시각/동작 불일치** | `:focus-visible` 미매칭 → 배경 미활성, edit 미진입. **일관** | 🔵 의도된 수정 |
| **터치 (모바일)** | focus 안 됨 (touchend 더블탭 → activate 별도 경로) | 동일 | ✅ 동일 |
| **autoFocus quickAdd** | `committedRef=false → setEditing(true)` 마운트 effect → editing 모드 진입 → display span 미렌더 | 동일 | ✅ 동일 |

---

## 4. 영향받지 않음을 확인할 코드 경로

라인단위 grep 검증 결과:
- **InlineInput display span의 focus 클래스에 의존하는 외부 코드 0** — CSS 매칭은 component 내부.
- `onFocus` 핸들러 (L120-123) — 이미 `:focus-visible`로 게이트. 본 변경과 일관.
- `tabIndex={disabled ? -1 : 0}` (L120) — Tab 순서 보존.
- editing 모드 input (L82-108) — 변경 없음.
- `RoomMemoEditor.tsx` 등 다른 InlineInput 호출처 — props 시그니처 변경 없음.
- 이 변경으로 영향받는 다른 컴포넌트 0.

---

## 5. 검증 체크리스트

- [ ] `git diff` 에 `InlineInput.tsx` 한 파일, 한 라인만 표시됨
- [ ] TypeScript 빌드 오류 없음
- [ ] 브라우저 동작:
  - 키보드 Tab으로 InlineInput display span에 focus → 배경 활성 + edit 진입 (기존과 동일)
  - 마우스 우클릭 → 배경 미활성, edit 미진입 (기존: 배경 활성, edit 미진입)
  - 마우스 더블클릭 → edit 진입 (기존과 동일)
  - 모바일 더블탭 → edit 진입 (기존과 동일)
