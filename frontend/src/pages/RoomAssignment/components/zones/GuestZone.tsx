import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { Reservation } from '../../types';
import type { HoverZoneState } from '../../hooks/useHoverZone';
import { useGuestDropTarget } from '../../hooks/useGuestDropTarget';
import { ROOM_ROW_HEIGHT, ROOM_ROW_HEIGHT_EMPTY } from '../../utils/layoutConstants';
import { useIsDesktop } from '../../../../hooks/use-desktop';

export interface GuestZoneProps {
  // 좌측 라벨
  title: string;
  /** 라벨 옆 카운트 (cancelled 같이 카운트 표시 필요한 zone). */
  count?: number;
  titleColorClass: string;

  // 드롭 동작
  /** false 면 드롭 비활성 (unstable / cancelled). */
  accept: boolean;
  /** 드롭 받을 zoneId (accept 일 때 필수). */
  zoneId?: string;
  /** 다음날 컬럼 드롭 받을 zoneId (있으면 다음날 컬럼도 드롭존). */
  nextZoneId?: string;
  /** 호버 시 zone 전체 배경 클래스 (예: 'bg-[#FF9500]/50 dark:bg-[#FF9500]/8'). */
  hoverBgClass?: string;

  // 빈 상태
  /** guests 비었을 때 호버하면 표시할 안내. */
  emptyMessage?: string;
  /** 빈 상태 텍스트 색상. */
  emptyMessageColorClass?: string;
  /** guests + nextDayGuests 모두 비었을 때 zone 자체 숨김 (unstable / cancelled). */
  hideWhenEmpty?: boolean;

  // 외형 변경자
  /** 추가 zone 컨테이너 클래스 (예: 'opacity-60'). */
  zoneClassName?: string;

  // 데이터
  guests: Reservation[];
  nextDayGuests: Reservation[];

  // 호버 상태 (useHoverZone 결과 그대로 전달)
  hover: HoverZoneState;
  setHover: (s: HoverZoneState) => void;
  clearHover: () => void;

  // 드롭 클릭 (본체의 onDropZoneClick)
  onDropZoneClick: (e: React.MouseEvent) => void;

  // 레이아웃
  selectionActive: boolean;
  nextDayExpanded: boolean;
  NEXT_DAY_EXPANDED_WIDTH: number;
  nextDayColWidth: number;
  GUEST_COLS: string;

  // 행 렌더러
  /** 본체의 renderGuestRow (GuestRow + sharedRowProps 묶음) 그대로 전달. */
  renderGuestRow: (res: Reservation, showGrip: boolean, zone?: string) => React.ReactNode;
  /** renderGuestRow 의 zone 인자 (예: 'unstable', 'cancelled'). */
  rowZone?: string;
  /** 다음날 컬럼의 게스트 렌더러 — body 가 CompactGuestCell + sharedNextProps 묶어 전달. */
  renderCompactCell: (guest: Reservation) => React.ReactNode;
}

/**
 * 4개 zone (unassigned/party/unstable/cancelled) 의 공통 외형 골격.
 *
 * Phase F-1: C-3 결정의 핵심 적용.
 * - 외피(라벨/리스트/드롭존/빈 상태/다음날 칼럼) 표준화
 * - 차이점은 props 로 (drop accept, color, empty msg 등)
 */
export function GuestZone({
  title, count, titleColorClass,
  accept, zoneId, nextZoneId, hoverBgClass,
  emptyMessage, emptyMessageColorClass, hideWhenEmpty,
  zoneClassName,
  guests, nextDayGuests,
  hover, setHover, clearHover,
  onDropZoneClick,
  selectionActive, nextDayExpanded, NEXT_DAY_EXPANDED_WIDTH, nextDayColWidth, GUEST_COLS,
  renderGuestRow, rowZone,
  renderCompactCell,
}: GuestZoneProps) {
  // 모두 비어있고 hideWhenEmpty 면 자체 숨김
  if (hideWhenEmpty && guests.length === 0 && nextDayGuests.length === 0) {
    return null;
  }

  const isDesktop = useIsDesktop();
  // 메인 zone 의 드롭존 동작 — 게스트 선택 시에만 활성.
  const main = useGuestDropTarget({
    zoneId: zoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!zoneId && selectionActive,
  });

  // 다음날 컬럼의 드롭존 동작 (펼침 + nextZoneId 있을 때만)
  const next = useGuestDropTarget({
    zoneId: nextZoneId ?? '',
    hover, setHover, clearHover,
    enabled: accept && !!nextZoneId && nextDayExpanded && selectionActive,
  });

  // dnd-kit useDroppable — PC 드래그용. id는 항상 unique 필요 → zoneId 없으면 noop fallback.
  const dropMain = useDroppable({
    id: zoneId || `__noop-zone-${title}-main`,
    disabled: !isDesktop || !accept || !zoneId,
  });
  const dropNext = useDroppable({
    id: nextZoneId || `__noop-zone-${title}-next`,
    disabled: !isDesktop || !accept || !nextZoneId || !nextDayExpanded,
  });
  const isMainOver = main.isDragOver || dropMain.isOver;
  const isNextOver = next.isDragOver || dropNext.isOver;

  return (
    <div
      className={`group flex select-none transition-colors ${
        accept && isMainOver
          ? hoverBgClass ?? ''
          : guests.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
      } ${selectionActive && accept ? 'cursor-pointer' : ''} ${zoneClassName ?? ''}`}
      style={{ minHeight: `${guests.length === 0 && nextDayGuests.length === 0 ? ROOM_ROW_HEIGHT_EMPTY : Math.max(guests.length, nextDayGuests.length) * ROOM_ROW_HEIGHT}px` }}
      {...main.dropZoneProps}
      onClick={accept ? onDropZoneClick : undefined}
    >
      {/* main droppable wrapper — 라벨 + 게스트 리스트만 포함 (next 영역 분리로 collision detection 우선순위 충돌 회피) */}
      <div ref={dropMain.setNodeRef} className="relative flex flex-1 min-w-0">
        {accept && isMainOver && (
          <div className={`absolute inset-0 pointer-events-none z-[5] ${hoverBgClass ?? 'bg-[#3182F6]/15 dark:bg-[#3182F6]/20'}`} />
        )}
        {/* 좌측 라벨 */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-38 pl-3 pr-2 border-r border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24]">
          <span className={`font-semibold ${titleColorClass} text-body`}>{title}</span>
          {typeof count === 'number' && (
            <span className="text-caption text-[#B0B8C1]">{count}</span>
          )}
        </div>

        {/* 게스트 리스트 (오늘) */}
        <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b border-[#E5E8EB] dark:border-[#2C2C34]">
          {guests.length > 0 ? (
            guests.map((res) => renderGuestRow(res, true, rowZone))
          ) : (
            <div className="flex items-center cursor-default" style={{ height: ROOM_ROW_HEIGHT_EMPTY }}>
              <div className="flex-1 grid items-center" style={{ gridTemplateColumns: GUEST_COLS }}>
                <div className={`overflow-hidden truncate col-span-full text-body ${emptyMessageColorClass ?? 'text-[#B0B8C1]'} italic px-1.5`}>
                  {accept && isMainOver ? (emptyMessage ?? '') : ''}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 다음날 컬럼 */}
      <div
        ref={dropNext.setNodeRef}
        className={`relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200 ${
          isNextOver ? hoverBgClass ?? '' : ''
        } ${selectionActive && accept && nextDayExpanded ? 'cursor-pointer' : ''}`}
        style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : nextDayColWidth, minHeight: `${nextDayGuests.length === 0 ? ROOM_ROW_HEIGHT_EMPTY : nextDayGuests.length * ROOM_ROW_HEIGHT}px` }}
        {...next.dropZoneProps}
        onClick={accept && nextDayExpanded ? onDropZoneClick : undefined}
      >
        {accept && isNextOver && (
          <div className={`absolute inset-0 pointer-events-none z-[5] ${hoverBgClass ?? 'bg-[#3182F6]/15 dark:bg-[#3182F6]/20'}`} />
        )}
        <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
          {nextDayGuests.length > 0 ? (
            nextDayGuests.map((guest) => (
              <div
                key={`next-zone-${guest.id}`}
                className={`flex items-center px-1 ${!nextDayExpanded ? 'justify-center' : ''}`}
                style={{ height: ROOM_ROW_HEIGHT }}
              >
                {renderCompactCell(guest)}
              </div>
            ))
          ) : (
            <div className="flex items-center px-1" style={{ height: ROOM_ROW_HEIGHT_EMPTY }}>
              <span className={`text-caption ${emptyMessageColorClass ?? 'text-[#B0B8C1]'} italic`}>
                {accept && isNextOver ? (emptyMessage ?? '') : ''}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
