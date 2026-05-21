/**
 * 4개 zone (unassigned/party/unstable/cancelled) — 모바일(<768px) 카드 변형.
 *
 * Mobile Layout Step #04 (2026-05-20): GuestZone 의 가로 레이아웃(좌측 라벨 + 본문 + 우측 다음날)을
 * 세로 카드(헤더 + 게스트 리스트 + 옵션 내일 미리보기) 로 재구성.
 *
 * Props: `GuestZoneProps` 동일 — drop-in. 호출자(zone 래퍼) 변경 없음.
 *
 * 동작 보존:
 *  - useGuestDropTarget / useDroppable (PC 드래그) — 모바일에선 selectionActive 일 때만 활성
 *  - hideWhenEmpty
 *  - hoverBgClass / accept / count
 *  - renderGuestRow 로 게스트 1명 렌더 (sharedZoneProps 의 renderGuestRow 가 isMobile 일 때 MobileGuestRow 를 호출하므로 자동으로 컴팩트 행 렌더)
 *  - renderCompactCell 로 내일 게스트 텍스트 표시
 */

import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { useGuestDropTarget } from '../../hooks/useGuestDropTarget';
import { useIsDesktop } from '../../../../hooks/use-desktop';
import type { GuestZoneProps } from './GuestZone';

export function MobileGuestZone({
  title, count, titleColorClass,
  accept, zoneId, nextZoneId, hoverBgClass,
  emptyMessage, emptyMessageColorClass, hideWhenEmpty,
  zoneClassName,
  guests, nextDayGuests,
  hover, setHover, clearHover,
  onDropZoneClick,
  selectionActive, nextDayExpanded,
  // GUEST_COLS / NEXT_DAY_EXPANDED_WIDTH / nextDayColWidth 는 모바일에서 사용 안 함 (수신만)
  GUEST_COLS: _GUEST_COLS,
  NEXT_DAY_EXPANDED_WIDTH: _NEXT_DAY_EXPANDED_WIDTH,
  nextDayColWidth: _nextDayColWidth,
  renderGuestRow, rowZone,
  renderCompactCell,
}: GuestZoneProps) {
  // 모두 비어있고 hideWhenEmpty 면 자체 숨김
  if (hideWhenEmpty && guests.length === 0 && nextDayGuests.length === 0) {
    return null;
  }

  const isDesktop = useIsDesktop();

  const main = useGuestDropTarget({
    zoneId: zoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!zoneId && selectionActive,
  });
  const next = useGuestDropTarget({
    zoneId: nextZoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!nextZoneId && nextDayExpanded && selectionActive,
  });
  // Step #06a: 모바일도 드롭 활성.
  const dropMain = useDroppable({
    id: zoneId || `__noop-zone-${title}-main`,
    disabled: !accept || !zoneId,
  });
  const dropNext = useDroppable({
    id: nextZoneId || `__noop-zone-${title}-next`,
    disabled: !accept || !nextZoneId || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;

  return (
    <div
      className={`select-none transition-colors border-b border-[#E5E8EB] dark:border-[#2C2C34] ${
        accept && isMainOver
          ? hoverBgClass ?? ''
          : guests.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
      } ${selectionActive && accept ? 'cursor-pointer' : ''} ${zoneClassName ?? ''}`}
      {...main.dropZoneProps}
      onClick={accept ? onDropZoneClick : undefined}
    >
      {/* main droppable wrapper */}
      <div ref={dropMain.setNodeRef} className="relative">
        {accept && isMainOver && (
          <div className={`absolute inset-0 pointer-events-none z-[5] ${hoverBgClass ?? 'bg-[#3182F6]/15 dark:bg-[#3182F6]/20'}`} />
        )}

        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[#F2F4F6] dark:border-[#2C2C34]">
          <span className={`font-semibold ${titleColorClass} text-body`}>{title}</span>
          {typeof count === 'number' && (
            <span className="text-caption text-[#B0B8C1]">({count})</span>
          )}
        </div>

        {/* Today guests — 비어있을 때는 본문 비움 (drop hint 텍스트 제거, drag 시각 효과로 충분) */}
        <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
          {guests.map((res) => renderGuestRow(res, true, rowZone))}
        </div>

        {/* 내일 섹션은 모바일에서 숨김 (요청). */}
      </div>
    </div>
  );
}
