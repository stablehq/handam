# Mobile Layout Step #03b — MobileRoomCard + MobileGuestRow

> 작성일: 2026-05-20
> 부모 plan: [mobile-layout-migration-plan.md](./mobile-layout-migration-plan.md)
> 직전: [Step #03a](./mobile-layout-step-03a-mobile-expand.md) (완료)
> 동작 변화: **모바일 객실 영역만** — 가로 매트릭스 → 세로 카드. PC 0 변화.

## 목표

PC `RoomRow` (가로 grid) → 모바일 카드. 게스트 정보는 옵션 B (사용자 확정): **3줄 컴팩트 모바일 줄**.

## 신규 컴포넌트

### MobileGuestRow (게스트 1명 = 3줄)
```
[○] 홍길동 (24, 남) · 남2 · 파티1차
    010-1234-5678 · 도미토리
    📝 메모... · [SMS 칩들]
```
- props: `GuestRowProps` 동일 — drop-in replacement 가능
- 인라인 편집: name, phone, party_type, genderPeople, notes
- 읽기 전용: naver_room_type, suffix(나이/성별), unstable dot, cancelled time
- 보존: highlight color, selection ring, long-press 컨텍스트 메뉴, drag (PC에선 disabled), SmsCell

### MobileRoomCard (객실 1개 = 카드 1개)
```
┌─ 101호 [📝] · 도미(남) · 4/6명 ─┐
│ [MobileGuestRow]                │  ← 오늘 게스트
│ [MobileGuestRow]                │
│ ─────── 내일 ─────              │
│ [CompactGuestCell expanded=false] ← 내일 미리보기 (간단 텍스트)
└─────────────────────────────────┘
```
- props: `RoomRowProps` + 옵션 `renderMobileGuestRow`
- 스트라이프/그룹 색상 유지
- 도미토리 빈 침대 표시 유지
- 드롭존 (selectionActive 일 때만)

## 부모 (RoomAssignment.tsx) 변경

```tsx
// 신규 closure (parallel to renderGuestRow)
const renderMobileGuestRow = (res, showGrip, zone) => (
  <MobileGuestRow key={res.id} res={res} showGrip={showGrip}
    isSelected={selectedGuestIds.has(res.id)} zone={zone} {...sharedRowProps}/>
);

// 기존 renderRoomRow 를 isMobile 분기로 확장
const renderRoomRow = (entry, rowIndex) => {
  // ... groupInfo / groupColor 계산 ...
  if (isMobile) {
    return <MobileRoomCard ... renderMobileGuestRow={renderMobileGuestRow}/>;
  }
  return <RoomRow ... renderGuestRow={renderGuestRow}/>;
};
```

## MobileLayout 변경

- 컬럼 헤더 섹션 (line 137-180 in current MobileLayout) **제거**
- resize guide line (line 134-136) **제거** (컬럼 리사이즈가 모바일에선 무의미)
- 나머지 JSX (sticky date nav, BuildingGroup loop, zones) 유지
- BuildingGroup 의 renderRoomRow 가 parent 로부터 분기된 closure 받음 → 자동으로 카드 렌더

## 검증

- TypeScript / build 통과
- PC: 시각 변화 0 (DesktopLayout 안 건드림, parent 의 renderRoomRow 도 isMobile=false 분기에서 동일)
- 모바일: 객실 영역이 세로 카드 리스트로. 컬럼 헤더 사라짐. zones 는 아직 PC-style (Step #04 에서 처리).
