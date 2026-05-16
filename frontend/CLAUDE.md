# Frontend — Design Guidelines

프론트엔드는 **Toss Invest 디자인 시스템** 기반 + **Flowbite React** 컴포넌트 라이브러리를 사용합니다. 새 페이지나 컴포넌트 작성 시 아래 규칙을 따르세요.

> 루트 [`../CLAUDE.md`](../CLAUDE.md) 의 프로젝트 전반 가이드도 함께 참고.

## 핵심 파일
- `src/index.css`: 디자인 토큰 (타이포그래피, 색상, 컴포넌트 클래스)
- `src/components/FlowbiteTheme.tsx`: Flowbite 커스텀 테마 오버라이드

## 색상 팔레트 (Toss-inspired)

| 토큰 | 값 | 용도 |
|------|------|------|
| Primary Blue | `#3182F6` | 주요 액션, 활성 상태, 링크 |
| Blue Light | `#E8F3FF` | Blue 배경 (뱃지, 활성 사이드바) |
| Success | `#00C9A7` | 확정, 성공, 완료 |
| Warning | `#FF9F00` | 대기, 주의 |
| Error | `#F04452` | 취소, 삭제, 에러 |
| Text Primary | `#191F28` | 제목, 본문 (dark: `white`) |
| Text Secondary | `#4E5968` | 보조 텍스트 (dark: `gray-300`) |
| Text Tertiary | `#8B95A1` | 라벨, 비활성 (dark: `gray-500`) |
| Text Disabled | `#B0B8C1` | 플레이스홀더, 비활성 (dark: `gray-600`) |
| Border | `#E5E8EB` | 입력 필드 테두리, 구분선 |
| Background | `#F2F4F6` | 카드 배경, 호버 (dark: `#2C2C34`) |
| Surface | `#F8F9FA` | stat-card 배경 (dark: `#1E1E24`) |

## 타이포그래피 (CSS 커스텀 클래스)

| 클래스 | 크기 | 행간 | 굵기 | 용도 |
|--------|------|------|------|------|
| `text-display` | 28px | 36px | bold | Hero, 대시보드 대형 숫자 |
| `text-title` | 22px | 30px | bold | 페이지 제목 (`.page-title`) |
| `text-heading` | 18px | 26px | semibold | 섹션 제목, 모달 제목 |
| `text-subheading` | 15px | 22px | semibold | 카드 제목, 네비 브랜드 |
| `text-body` | 14px | 20px | regular | **본문 기본값** |
| `text-label` | 13px | 18px | medium | 서브타이틀, 보조 본문 |
| `text-caption` | 12px | 16px | medium | 테이블 헤더, 캡션, 도움말 |
| `text-overline` | 11px | 16px | semibold | 카테고리 라벨 |
| `text-tiny` | 10px | 14px | regular | 타임스탬프, 뱃지 |

## 버튼 규칙 (Flowbite `<Button>`)

| 위치 | `size` | `color` | 아이콘 크기 | 예시 |
|------|--------|---------|-------------|------|
| 페이지 헤더 액션 | `sm` | `blue` 또는 `light` | `h-3.5 w-3.5` | 예약 등록, 네이버 동기화, 객실안내 |
| 테이블 인라인 액션 | `xs` | `light` 또는 `failure` | `h-3.5 w-3.5` | 수정, 삭제 버튼 |
| 모달 푸터 | (기본) | `blue` + `light` | — | 저장/취소 |
| 삭제 확인 모달 | (기본) | `failure` + `light` | — | 삭제/취소 |

**규칙:**
- 버튼 내 아이콘은 `mr-1.5` 간격으로 텍스트 앞에 배치
- 아이콘 전용 버튼(테이블 내)은 `mr` 없이 아이콘만
- 로딩 시 `<Spinner size="sm" className="mr-2" />` + "저장 중..." 텍스트

## 아이콘 (Lucide React)

| 컨텍스트 | 크기 | 비고 |
|----------|------|------|
| 버튼 내부 (sm/xs) | `h-3.5 w-3.5` | 가장 많이 사용 |
| 독립 아이콘 (필터 등) | `h-4 w-4` | 검색, 닫기, 네비게이션 |
| stat-card 아이콘 | `size={18}` (lucide prop) | `.stat-icon` 컨테이너 안 |
| 빈 상태 일러스트 | `size={40}` 또는 `h-10 w-10` | `.empty-state` 안 |

## 간격 (Gap) 규칙

| 컨텍스트 | gap | 비고 |
|----------|-----|------|
| 페이지 헤더 ↔ 콘텐츠 | `space-y-6` | 최상위 레이아웃 |
| 버튼 그룹 (헤더) | `gap-2` | 수평 버튼 나열 |
| 테이블 인라인 버튼 | `gap-1` | 수정/삭제 버튼 쌍 |
| stat-card 그리드 | `gap-3` | `grid-cols-2 sm:3 lg:5` |
| 폼 필드 간격 | `gap-4` | 모달 내 수직 폼 |
| 필터 바 항목 | `gap-3` | `.filter-bar` 내부 |
| 카드 내부 요소 | `gap-3` | stat-icon ↔ 텍스트 |

## Badge 규칙 (Flowbite `<Badge>`)

| 용도 | `size` | `color` |
|------|--------|---------|
| 상태 표시 (확정/대기/취소) | `sm` | `success` / `warning` / `failure` |
| 출처 라벨 (네이버/수동) | `xs` | `success` / `gray` |
| 정보 표시 (객실, 태그) | `sm` | `info` / `purple` / `gray` |

## 모달 (Flowbite `<Modal>`)

| 용도 | `size` | 비고 |
|------|--------|------|
| 일반 폼 (생성/수정) | `md` | 대부분의 CRUD 모달 |
| 복잡한 폼 | `lg` | 여러 섹션이 있는 폼 |
| 삭제 확인 | `md` + `popup` | 아이콘 + 텍스트 + 버튼 중앙 정렬 |

## 컴포넌트 클래스 (index.css)

| 클래스 | 용도 |
|--------|------|
| `.page-title` | 페이지 제목 (`text-title font-bold`) |
| `.page-subtitle` | 페이지 설명 (`text-label text-[#8B95A1]`) |
| `.stat-card` | 통계 카드 컨테이너 (`rounded-2xl bg-[#F8F9FA] p-5`) |
| `.stat-value` | 통계 숫자 (`text-title font-bold tabular-nums`) |
| `.stat-label` | 통계 라벨 (`text-caption text-[#8B95A1]`) |
| `.stat-icon` | 통계 아이콘 래퍼 (`h-10 w-10 rounded-xl`) |
| `.section-card` | 섹션 카드 (`rounded-2xl border bg-white`) |
| `.section-header` | 섹션 헤더 (`px-5 py-4 flex justify-between`) |
| `.filter-bar` | 필터 바 (`flex flex-wrap gap-3 p-4`) |
| `.empty-state` | 빈 상태 (`flex flex-col items-center py-16`) |
| `.guest-card` | 게스트 드래그 카드 (`cursor-grab rounded-xl`) |
| `.room-cell` | 객실 드롭 영역 (`border-2 border-dashed`) |

## 다크 모드 패턴

- 배경: `dark:bg-[#17171C]` (body), `dark:bg-[#1E1E24]` (카드/셀)
- 호버: `dark:hover:bg-[#2C2C34]` 또는 `dark:hover:bg-[#35353E]`
- 테두리: `dark:border-gray-800` (기본), `dark:border-gray-600` (입력 필드)
- 텍스트: `dark:text-white` (제목), `dark:text-gray-100` (본문), `dark:text-gray-500` (보조)
- 뱃지/칩 배경: `dark:bg-[색상]/15` 패턴 (예: `dark:bg-[#3182F6]/15`)

## 페이지 레이아웃 패턴

```
<div className="space-y-6">
  {/* 헤더: 제목 + 액션 버튼 */}
  <div className="flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 className="page-title">페이지 제목</h1>
      <p className="page-subtitle">설명 텍스트</p>
    </div>
    <div className="flex items-center gap-2">
      <Button color="light" size="sm">...</Button>
      <Button color="blue" size="sm">...</Button>
    </div>
  </div>

  {/* stat-card 그리드 (선택) */}
  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
    <div className="stat-card">...</div>
  </div>

  {/* 메인 콘텐츠 */}
  <div className="section-card">...</div>
</div>
```

## 숫자 표시
- 숫자에는 `tabular-nums` 클래스 적용 (고정폭 숫자)
- 단위는 `<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">건</span>` 형태

## 반올림(Border Radius) 규칙
- 카드, 모달: `rounded-2xl` (16px)
- 버튼, 뱃지, 입력: `rounded-lg` (8px)
- stat-icon: `rounded-xl` (12px)
- 채팅 버블: `rounded-[20px]` + 꼬리 `rounded-bl-[4px]`
