/**
 * 게스트 한 줄 — 모바일(<768px) 컴팩트 3줄 레이아웃.
 *
 * Mobile Layout Step #03b (2026-05-20): GuestRow 의 가로 grid 를 세로 3줄로 재구성.
 * 같은 props (`GuestRowProps`) 받아 drop-in replacement 가능.
 *
 * 레이아웃:
 *   [○] 이름 (suffix) · 남2 · 파티타입
 *       전화번호 · 예약객실
 *       메모(편집 가능) · [SMS 칩들]
 *
 * 보존:
 *  - 인라인 편집: customer_name / phone / party_type / genderPeople / notes
 *  - 읽기 전용: naver_room_type, suffix(나이/성별), unstable dot, cancelled time
 *  - highlight color (preset + custom hex)
 *  - selection ring (long-press 후 표시)
 *  - long-press 컨텍스트 메뉴 (500ms)
 *  - drag (PC 에선 활성, 모바일 disabled)
 *  - SmsCell
 *  - long-stay 강조 배경
 *  - cancelled 시 line-through + 취소 시각 표시
 */

import React, { useState } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import { GripVertical, ChevronDown, ChevronUp } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { normalizeUtcString } from '../../../../lib/utils';
import {
  PRESET_HIGHLIGHT_STYLES,
  isCustomHexColor,
  getCustomBgStyle,
  getCustomTextClass,
  isLightColor,
} from '@/lib/highlight-colors';
import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import { InlineInput } from '../InlineInput';
import { SmsCell } from '../SmsCell';
import type { GuestRowProps } from './GuestRow';

export function MobileGuestRow({
  res,
  showGrip,
  isSelected,
  zone,
  selectionActive,
  isDarkMode,
  // GUEST_COLS 는 모바일 레이아웃에서 사용 안 함 (수신은 함 — drop-in 호환)
  GUEST_COLS: _GUEST_COLS,
  templateLabels,
  selectedDate,
  quickAddedId,
  onGripClick,
  onGuestContextMenu,
  handleFieldSave,
  handleSmsToggle,
  handleSmsAssign,
  handleSmsRemove,
  cancelDeselect,
  onInputDeactivate,
  longPressTimerRef,
  longPressFiredRef,
}: GuestRowProps) {
  // Step #06d: 모바일 행 펼침/접힘 상태 — 우측 chevron 버튼으로 토글. 펼치면 예약객실/메모/SMS 표시.
  const [expanded, setExpanded] = useState(false);
  const genderPeople = formatGenderPeople(res);
  const suffix = formatGuestSuffix(res);
  const longStay = !!res.is_long_stay;
  const isCancelled = res.status === 'cancelled';

  // 연박(2박+) 인 경우 현재 몇 박째인지 표시 (예: "2/3"). 1박은 미표시.
  // 두 경로 모두 처리:
  //  - 경로 A: 한 record 에 다박 (check_out - check_in > 1) → date diff 로 계산
  //  - 경로 B: 1박씩 split + stay_group 묶음 → backend 가 계산해서 보낸 stay_group_total_nights / stay_group_night_offset 사용
  const stayProgress = (() => {
    if (!res.check_in_date) return null;
    const inDate = dayjs(res.check_in_date);

    // 경로 B: stay_group 이 있고 backend 가 총박수 계산해서 보낸 경우
    if (res.stay_group_id && res.stay_group_total_nights && res.stay_group_total_nights >= 2) {
      const recordNight = selectedDate.startOf('day').diff(inDate.startOf('day'), 'day') + 1;
      const offset = res.stay_group_night_offset ?? 0;
      const currentNight = offset + recordNight;
      const totalNights = res.stay_group_total_nights;
      if (currentNight < 1 || currentNight > totalNights) return null;
      return `${currentNight}/${totalNights}`;
    }

    // 경로 A: 단일 record date diff
    if (!res.check_out_date) return null;
    const outDate = dayjs(res.check_out_date);
    const totalNights = outDate.diff(inDate, 'day');
    if (totalNights < 2) return null;
    const currentNight = selectedDate.startOf('day').diff(inDate.startOf('day'), 'day') + 1;
    if (currentNight < 1 || currentNight > totalNights) return null;
    return `${currentNight}/${totalNights}`;
  })();

  // Step #06a: 모바일도 드래그 활성.
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `guest-${res.id}`,
    disabled: isCancelled,
  });

  const isCustomHex = isCustomHexColor(res.highlight_color);
  const highlightStyle = !isCustomHex && res.highlight_color
    ? PRESET_HIGHLIGHT_STYLES[res.highlight_color]
    : null;
  const hasCustomText = isCustomHex || !!highlightStyle?.text;
  const isDarkHexBg = isCustomHex && !isLightColor(res.highlight_color!);
  const subtleText = isDarkHexBg
    ? 'text-[#191F28] dark:text-white'
    : 'text-[#8B95A1] dark:text-[#4E5968]';
  const cellText = isCancelled
    ? 'text-[#F04452] line-through opacity-60'
    : hasCustomText
      ? 'text-inherit'
      : 'text-[#191F28] dark:text-white';

  const containerBgClass = isCancelled
    ? 'bg-[#FFEBEE] dark:bg-[#F04452]/10'
    : isSelected
      ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/15 ring-1 ring-inset ring-[#3182F6]/30'
      : isCustomHex
        ? `${getCustomTextClass(res.highlight_color!)} hover:brightness-[0.97] dark:hover:brightness-110`
        : highlightStyle
          ? `${highlightStyle.bg} ${highlightStyle.hover} ${highlightStyle.text || ''}`
          : longStay
            ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15 hover:bg-[#FFE4CC] dark:hover:bg-[#FF9500]/20'
            : 'hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/8';

  return (
    <div
      key={res.id}
      className={`group/guest relative flex flex-col gap-0.5 px-1 py-2 transition-colors duration-150 cursor-pointer ${
        isDragging ? 'opacity-40' : ''
      } ${containerBgClass}`}
      style={isCustomHex && !isSelected ? getCustomBgStyle(res.highlight_color!, isDarkMode) : undefined}
      onContextMenu={(e) => {
        if (isCancelled) return;
        if (document.activeElement instanceof HTMLInputElement) return;
        onGuestContextMenu(e, res.id, zone);
      }}
      onTouchStart={(e) => {
        if (isCancelled) return;
        const target = e.target as HTMLElement;
        if (target.closest('input, textarea, button, a, [role="button"], [data-interactive]')) return;
        longPressFiredRef.current = false;
        const t = e.touches[0];
        const x = t.clientX;
        const y = t.clientY;
        if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
        longPressTimerRef.current = setTimeout(() => {
          longPressFiredRef.current = true;
          longPressTimerRef.current = null;
          onGuestContextMenu(
            { preventDefault: () => {}, stopPropagation: () => {}, clientX: x, clientY: y } as React.MouseEvent,
            res.id,
            zone,
          );
          setTimeout(() => { longPressFiredRef.current = false; }, 1000);
        }, 500);
      }}
      onTouchMove={() => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
      }}
      onTouchEnd={(e) => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
        if (longPressFiredRef.current) {
          e.preventDefault();
        }
      }}
      onTouchCancel={() => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
      }}
      onClick={(e: React.MouseEvent) => {
        // Step #06b: selection 제거. long-press 합성 click 만 가드.
        if (longPressFiredRef.current) {
          longPressFiredRef.current = false;
          e.stopPropagation();
        }
      }}
    >
      {/* 연박 진행 (예: "2/3") — row 우측 상단 absolute. 1박은 비표시. 배경 없이 텍스트, 주황 톤.
          가로 정렬·row 높이 영향 X. py-2(8px) top padding 공간에 떠있음. */}
      {stayProgress && (
        <span className="absolute top-1 right-1.5 text-tiny tabular-nums font-medium text-[#FF8800] dark:text-[#FFB366] leading-none pointer-events-none select-none">
          {stayProgress}
        </span>
      )}
      {/* Line 1 row: grip + 셀 + arrow 가 하나의 items-center 가로 flex.
          row 루트는 flex-col 이라 펼침 영역이 sibling 으로 아래 stack →
          grip/arrow 는 line 1 anchor 에만 묶여 펼쳐도 위치 안 바뀜. */}
      {/* 평탄 구조: 모든 자식 형제. 간격은 각 자식의 ml-[Npx] 로 명시.
          padding 4px [ grip 6px 이름 3px 전화 3px 파티 3px 성별 3px chevron ] padding 4px
          row 루트의 px-1 = 4px 가 좌우 padding 역할.
          (2/3) 칩은 row 우측 상단에 absolute → 가로 정렬·row 높이 모두 영향 X. */}
      <div className="flex items-center min-w-0">
        {/* Selection grip (좌측). Step #06b: selection 시스템 제거로 grip 의 onClick 도 제거 — drag 만 활성. */}
        {showGrip && !isCancelled && (
          <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            className={`flex items-center justify-center w-6 h-5 flex-shrink-0 cursor-grab active:cursor-grabbing touch-none text-[#B0B8C1] dark:text-[#4E5968] transition-colors duration-200 ${
              isSelected
                ? 'text-[#3182F6] dark:text-[#3182F6]'
                : longStay
                  ? 'group-hover/guest:text-[#FFB366]'
                  : 'group-hover/guest:text-[#3182F6]'
            }`}
          >
            {/* Step #06a: 모바일도 GripVertical (drag 핸들). */}
            <GripVertical size={18} strokeWidth={1.5} />
          </div>
        )}

        {/* 이름 + unstable dot — 자연 너비 우선(shrink-0). 전화번호가 먼저 줄어듦.
            items-baseline 으로 dot 도 텍스트 baseline 에 맞춤. grip 있으면 ml-1.5(6px). */}
        <span className={`flex items-baseline gap-1 flex-shrink-0 ${showGrip && !isCancelled ? 'ml-1.5' : ''}`}>
          {/* visitor 가 별도로 있으면 visitor 정보만 노출(편집도 visitor 필드로). */}
          {(() => {
            const useVisitor = !!(res.visitor_name && res.visitor_name !== res.customer_name);
            return (
              <InlineInput
                value={useVisitor ? (res.visitor_name || '') : res.customer_name}
                field={useVisitor ? 'visitor_name' : 'customer_name'}
                resId={res.id}
                onSave={handleFieldSave}
                className={`font-medium text-label ${cellText}`}
                placeholder="이름"
                autoFocus={res.id === quickAddedId}
                disabled={isCancelled}
                compact
                onActivate={cancelDeselect} onDeactivate={onInputDeactivate}
                singleClick
              />
            );
          })()}
          {res.has_unstable_booking && (
            <span
              className="inline-block h-[6px] w-[6px] rounded-full bg-[#7B61FF] flex-shrink-0"
              title="언스테이블 파티 예약 확인"
            />
          )}
        </span>
        {/* Phone — 이름 우선 정책. 남는 공간 차지, 좁으면 truncate. */}
        <div className="flex-1 min-w-[64px] overflow-hidden text-center ml-[3px]">
          {(() => {
            const useVisitorPhone = !!(res.visitor_phone && res.visitor_phone !== res.phone);
            return (
              <InlineInput
                value={useVisitorPhone ? (res.visitor_phone || '') : res.phone}
                field={useVisitorPhone ? 'visitor_phone' : 'phone'}
                resId={res.id}
                onSave={handleFieldSave}
                className={`${cellText} tabular-nums text-label text-center`}
                placeholder="연락처"
                compact
                onActivate={cancelDeselect} onDeactivate={onInputDeactivate}
                singleClick
              />
            );
          })()}
        </div>
        {/* Party — 최소 33px, 가운데 정렬 */}
        <div className="min-w-[33px] flex-shrink-0 text-center ml-[3px]">
          <InlineInput
            value={res.party_type || ''}
            field="party_type"
            resId={res.id}
            onSave={handleFieldSave}
            className={`${cellText} font-medium text-label text-center`}
            placeholder="-"
            compact
            onActivate={cancelDeselect} onDeactivate={onInputDeactivate}
            singleClick
          />
        </div>
        {/* Gender — 최소 42px, 가운데 정렬 */}
        <div className="min-w-[42px] flex-shrink-0 text-center ml-[3px]">
          <InlineInput
            value={genderPeople}
            field="genderPeople"
            resId={res.id}
            onSave={handleFieldSave}
            className={`${cellText} font-medium text-label text-center`}
            placeholder="-"
            compact
            onActivate={cancelDeselect} onDeactivate={onInputDeactivate}
            singleClick
          />
        </div>

        {/* 우측 펼침/접힘 토글 — 같은 row wrapper 안에 위치해야 line 1 anchor 유지 */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((prev) => !prev);
          }}
          className={`flex items-center justify-center w-5 h-5 flex-shrink-0 ml-[3px] ${
            stayProgress ? 'translate-y-[2px]' : ''
          } text-[#8B95A1] dark:text-[#4E5968] hover:text-[#3182F6] dark:hover:text-[#3182F6] transition-colors cursor-pointer`}
          aria-label={expanded ? '접기' : '펼치기'}
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {/* 펼침 영역 — line 1 row 의 sibling. row 루트가 flex-col 이라 아래로 stack.
          grip 이 있으면 pl-[30px] (grip w-6 + ml-1.5 = 30px) 로 line 1 이름 셀과 좌측 정렬. */}
      {expanded && (
        <div className={showGrip && !isCancelled ? 'pl-[30px]' : ''}>
          {/* Line 2: suffix / 객실타입 / 메모 — 컬럼 레이아웃 (점 구분자 X) */}
          <div className="flex items-center gap-2 min-w-0">
            <span className={`text-label ${subtleText} min-w-[64px] flex-shrink-0 truncate`}>
              {suffix || ''}
            </span>
            <span className={`text-label ${subtleText} min-w-[40px] flex-shrink-0 truncate`}>
              {res.naver_room_type || ''}
            </span>
            <div className="flex-1 min-w-0 overflow-hidden">
              {isCancelled && res.cancelled_at ? (
                <span className="text-label text-[#F04452]">
                  {new Date(normalizeUtcString(res.cancelled_at)).toLocaleTimeString('ko-KR', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                  })}{' '}
                  취소
                </span>
              ) : (
                <InlineInput
                  value={res.notes || ''}
                  field="notes"
                  resId={res.id}
                  onSave={handleFieldSave}
                  className={`${cellText} text-label`}
                  placeholder="메모 입력하기"
                  onActivate={cancelDeselect} onDeactivate={onInputDeactivate}
                  singleClick
                />
              )}
            </div>
          </div>

          {/* Line 3: SMS 칩 */}
          <div className="flex items-center min-w-0">
            <SmsCell
              reservation={res}
              templateLabels={templateLabels}
              selectedDate={selectedDate.format('YYYY-MM-DD')}
              onToggle={handleSmsToggle}
              onAssign={handleSmsAssign}
              onRemove={handleSmsRemove}
            />
          </div>
        </div>
      )}
    </div>
  );
}
