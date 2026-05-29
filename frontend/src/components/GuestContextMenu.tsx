import React, { useRef, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Trash2, Link2, X, Zap, XCircle, CalendarPlus, CalendarMinus, Palette, ChevronRight, Calendar, Phone, RotateCcw } from 'lucide-react';
import { GOOGLE_SHEETS_PALETTE } from '../lib/highlight-colors';

interface GuestContextMenuProps {
  position: { x: number; y: number };
  targetCount: number;
  currentSection: 'room' | 'unassigned' | 'party' | 'unstable';
  hasStayGroup: boolean;
  isUnstableCopy?: boolean;
  customColors?: string[];
  onDelete: () => void;
  onLinkStayGroup?: () => void;
  onUnlinkStayGroup?: () => void;
  onSetColor: (color: string | null) => void;
  onCopyToUnstable?: () => void;
  onRemoveFromUnstable?: () => void;
  onExtendStay?: () => void;
  onCancelExtendStay?: () => void;
  onChangeDates?: () => void;
  onCall?: () => void;
  hideDelete?: boolean;
  /**
   * Cancelled 행 전용 — "삭제 취소" 단일 액션 모드.
   * 정의되면 다른 모든 메뉴 항목은 무시하고 restore 버튼 1개만 표시.
   */
  onRestore?: () => void;
  onClose: () => void;
}

export default function GuestContextMenu({
  position,
  targetCount,
  currentSection,
  hasStayGroup,
  isUnstableCopy,
  customColors = [],
  onDelete,
  onLinkStayGroup = undefined,
  onUnlinkStayGroup = undefined,
  onSetColor,
  onCopyToUnstable,
  onRemoveFromUnstable,
  onExtendStay,
  onCancelExtendStay,
  onChangeDates,
  onCall,
  hideDelete,
  onRestore,
  onClose,
}: GuestContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const [adjusted, setAdjusted] = useState<{ x: number; y: number }>(position);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [palettePos, setPalettePos] = useState<{ x: number; y: number; below: boolean }>({ x: 0, y: 0, below: false });
  const paletteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 팔레트가 열릴 때 trigger 위치 기반으로 좌표 계산 (portal로 body에 띄우기 때문에 부모 overflow 영향 X)
  useEffect(() => {
    if (!paletteOpen || !triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const PALETTE_WIDTH = 228;
    const margin = 8;
    const isNarrow = window.innerWidth < 500;
    if (isNarrow) {
      setPalettePos({ x: r.left, y: r.bottom + 4, below: true });
    } else {
      const spaceRight = window.innerWidth - r.right;
      if (spaceRight >= PALETTE_WIDTH + margin) {
        setPalettePos({ x: r.right + 4, y: r.top, below: false });
      } else {
        setPalettePos({ x: r.left - PALETTE_WIDTH - 4, y: r.top, below: false });
      }
    }
  }, [paletteOpen]);

  // Escape 만 자체 처리. outside-click 은 부모(RoomAssignment) 의 backdrop 이 담당.
  //
  // 이전엔 useClickOutside(touchstart/mousedown) 가 document 레벨에서 즉시 발화해
  // backdrop 보다 먼저 onClose 를 호출 → backdrop 이 unmount 되어 underlying drop
  // zone 이 후속 click 을 받아 모바일에서 예약자 이동이 잘못 발생하는 버그가 있었음.
  // 이제 backdrop 의 onClick 만으로 닫게 해 click 이벤트가 backdrop 위에서 완결됨.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    // 모바일 핀치줌 대응: visualViewport (실제 보이는 영역) 기준으로 배치.
    // layout viewport (window.innerWidth) 만 보면 잘림.
    const vv = window.visualViewport;
    const vLeft = vv ? vv.offsetLeft : 0;
    const vTop = vv ? vv.offsetTop : 0;
    const vWidth = vv ? vv.width : window.innerWidth;
    const vHeight = vv ? vv.height : window.innerHeight;
    const margin = 8;

    const x0 = position.x;
    const y0 = position.y;
    const w = rect.width;
    const h = rect.height;

    // 4방향 빈 공간 측정 → 메뉴를 어디 anchor 할지 결정
    const spaceRight = (vLeft + vWidth) - x0;
    const spaceLeft = x0 - vLeft;
    const spaceBottom = (vTop + vHeight) - y0;
    const spaceTop = y0 - vTop;

    // 가로: 오른쪽에 자리 있으면 터치 우측, 아니면 좌측, 둘 다 안 되면 우측 정렬
    let x: number;
    if (spaceRight >= w + margin) {
      x = x0;
    } else if (spaceLeft >= w + margin) {
      x = x0 - w;
    } else {
      x = vLeft + vWidth - w - margin;
    }

    // 세로: 아래쪽 우선, 안 되면 위쪽, 둘 다 안 되면 아래 정렬
    let y: number;
    if (spaceBottom >= h + margin) {
      y = y0;
    } else if (spaceTop >= h + margin) {
      y = y0 - h;
    } else {
      y = vTop + vHeight - h - margin;
    }

    // 최종 clamp — visual viewport 안으로 강제
    x = Math.max(vLeft + margin, Math.min(x, vLeft + vWidth - w - margin));
    y = Math.max(vTop + margin, Math.min(y, vTop + vHeight - h - margin));

    setAdjusted({ x, y });
  }, [position]);

  const plural = targetCount > 1 ? ` (${targetCount}명)` : '';

  const items: { icon: React.ReactNode; label: string; onClick: () => void; disabled: boolean; danger?: boolean }[] = [];

  if (onExtendStay) {
    items.push({
      icon: <CalendarPlus className="h-4 w-4" />,
      label: '내일 연박추가',
      onClick: onExtendStay,
      disabled: false,
    });
  }
  if (onCancelExtendStay) {
    items.push({
      icon: <CalendarMinus className="h-4 w-4" />,
      label: '수동연박 취소',
      onClick: onCancelExtendStay,
      disabled: false,
      danger: true,
    });
  }

  if (hasStayGroup && onUnlinkStayGroup) {
    items.push({
      icon: <Link2 className="h-4 w-4" />,
      label: '연박 해제',
      onClick: onUnlinkStayGroup,
      disabled: false,
    });
  }
  if (!hasStayGroup && onLinkStayGroup) {
    items.push({
      icon: <Link2 className="h-4 w-4" />,
      label: '연박 묶기',
      onClick: onLinkStayGroup,
      disabled: false,
    });
  }

  if (onChangeDates) {
    items.push({
      icon: <Calendar className="h-4 w-4" />,
      label: '예약 날짜 변경',
      onClick: onChangeDates,
      disabled: false,
    });
  }

  // 언스테이블 복사/제거 항목
  if (isUnstableCopy && onRemoveFromUnstable) {
    // 언스테이블 행의 복사본 → "제거"만 보임
    items.length = 0; // 기존 항목 제거 (복사본에는 이동/연박 불필요)
    items.push({
      icon: <XCircle className="h-4 w-4" />,
      label: '언스테이블 복사본 제거',
      onClick: onRemoveFromUnstable,
      disabled: false,
    });
  } else if (currentSection !== 'unstable' && onRemoveFromUnstable) {
    // 상단 예약자에서 이미 복사됨 → "언스테이블 복사본 제거" 표시
    items.push({
      icon: <XCircle className="h-4 w-4" />,
      label: '언스테이블 복사본 제거',
      onClick: onRemoveFromUnstable,
      disabled: false,
    });
  } else if (currentSection !== 'unstable' && onCopyToUnstable) {
    // 객실/미배정/파티만 → "언스 파티참여" 추가
    items.push({
      icon: <Zap className="h-4 w-4" />,
      label: `언스 파티참여${plural}`,
      onClick: onCopyToUnstable,
      disabled: false,
    });
  }

  // Cancelled 행 전용 — "삭제 취소" 단일 액션 모드.
  // RoomAssignment 가 status==='cancelled' 인 row 에 대해 onRestore 만 전달.
  // 다른 모든 액션은 무시하고 restore 버튼 1개만 노출.
  if (onRestore) {
    return createPortal(
      <div
        ref={menuRef}
        style={{
          position: 'fixed',
          left: adjusted.x,
          top: adjusted.y,
          zIndex: 10000,
          WebkitTouchCallout: 'none',
          WebkitUserSelect: 'none',
          userSelect: 'none',
          maxWidth: 'calc(100vw - 16px)',
        } as React.CSSProperties}
        className="w-44 rounded-xl border border-[#E5E8EB] dark:border-gray-800 bg-white dark:bg-[#1E1E24] shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100 select-none"
        onContextMenu={(e) => e.preventDefault()}
      >
        <button
          onClick={(e) => { e.stopPropagation(); onRestore(); }}
          className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#3182F6] hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/15 cursor-pointer transition-colors"
        >
          <RotateCcw className="h-4 w-4" />
          삭제 취소
        </button>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <>
    <div
      ref={menuRef}
      style={{
        position: 'fixed',
        left: adjusted.x,
        top: adjusted.y,
        zIndex: 10000,
        WebkitTouchCallout: 'none',
        WebkitUserSelect: 'none',
        userSelect: 'none',
        // 핀치줌 시 visual viewport 가 너무 작으면 메뉴 너비도 축소.
        // calc 안의 100vw 는 layout viewport 라 일반 케이스엔 영향 없음.
        // 핀치줌은 위 effect 의 visualViewport 측정으로 좌표가 보정되며
        // overflow 시에만 maxWidth 가 작동.
        maxWidth: 'calc(100vw - 16px)',
        maxHeight: 'calc(100vh - 16px)',
        overflowY: 'auto',
      } as React.CSSProperties}
      className="w-48 rounded-xl border border-[#E5E8EB] dark:border-gray-800 bg-white dark:bg-[#1E1E24] shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100 select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((item, i) => (
        <button
          key={i}
          onClick={(e) => { e.stopPropagation(); if (!item.disabled) item.onClick(); }}
          disabled={item.disabled}
          className={`w-full px-3 py-2 text-body flex items-center gap-2 transition-colors ${
            item.disabled
              ? 'text-[#B0B8C1] dark:text-[#4E5968] cursor-not-allowed'
              : item.danger
                ? 'text-[#F04452] hover:bg-[#FFF0F0] dark:hover:bg-[#F04452]/10 cursor-pointer'
                : 'text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer'
          }`}
        >
          {item.icon}
          {item.label}
        </button>
      ))}

      <div className="border-t border-[#E5E8EB] dark:border-gray-800 my-1" />

      {/* Color preset submenu trigger */}
      <div
        ref={triggerRef}
        onMouseEnter={() => { if (paletteTimerRef.current) clearTimeout(paletteTimerRef.current); setPaletteOpen(true); }}
        onMouseLeave={() => { paletteTimerRef.current = setTimeout(() => setPaletteOpen(false), 200); }}
      >
        <button
          className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer transition-colors"
          onClick={(e) => { e.stopPropagation(); setPaletteOpen(!paletteOpen); }}
        >
          <Palette className="h-4 w-4" />
          <span className="flex-1 text-left">컬러 프리셋</span>
          <ChevronRight className="h-3.5 w-3.5 text-[#8B95A1]" />
        </button>
      </div>

      {/* Quick colors */}
      <div className="px-3 py-1.5 flex flex-wrap items-center gap-1.5">
        {customColors.length > 0 ? (
          customColors.map((hex) => (
            <button
              key={hex}
              title={hex}
              onClick={(e) => { e.stopPropagation(); onSetColor(hex); }}
              className="w-5 h-5 rounded-full border border-gray-300 dark:border-gray-600 cursor-pointer hover:scale-110 transition-transform flex-shrink-0"
              style={{ backgroundColor: hex }}
            />
          ))
        ) : (
          <span className="text-caption text-[#B0B8C1] dark:text-[#4E5968]">테이블 설정에서 퀵 컬러를 추가하세요</span>
        )}
        <button
          title="색상 해제"
          onClick={(e) => { e.stopPropagation(); onSetColor(null); }}
          className="w-5 h-5 rounded-full border border-dashed border-gray-300 dark:border-gray-600 cursor-pointer hover:scale-110 transition-transform flex items-center justify-center flex-shrink-0"
        >
          <X className="h-2.5 w-2.5 text-[#8B95A1]" />
        </button>
      </div>

      {!isUnstableCopy && !hideDelete && (
        <>
          <div className="border-t border-[#E5E8EB] dark:border-gray-800 my-1" />

          {onCall && targetCount === 1 && (
            <button
              onClick={(e) => { e.stopPropagation(); onCall(); }}
              className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer transition-colors"
            >
              <Phone className="h-4 w-4" />
              전화걸기
            </button>
          )}

          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="w-full px-3 py-2 text-body flex items-center gap-2 text-[#F04452] hover:bg-[#FFF0F0] dark:hover:bg-[#F04452]/10 cursor-pointer transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            게스트 삭제{plural}
          </button>
        </>
      )}
    </div>
    {paletteOpen && (
      <div
        style={{ position: 'fixed', left: palettePos.x, top: palettePos.y, zIndex: 10001, minWidth: '228px', maxWidth: 'calc(100vw - 16px)' }}
        className="p-2 rounded-xl border border-[#E5E8EB] dark:border-gray-800 bg-white dark:bg-[#1E1E24] shadow-lg animate-in fade-in zoom-in-95 duration-100"
        onMouseEnter={() => { if (paletteTimerRef.current) clearTimeout(paletteTimerRef.current); }}
        onMouseLeave={() => { paletteTimerRef.current = setTimeout(() => setPaletteOpen(false), 200); }}
      >
        <div className="flex flex-col gap-0.5">
          {GOOGLE_SHEETS_PALETTE.map((row, ri) => (
            <div key={ri} className="flex gap-0.5">
              {row.map((hex) => (
                <button
                  key={hex}
                  title={hex}
                  onClick={(e) => { e.stopPropagation(); onSetColor(hex); }}
                  className="w-5 h-5 rounded-sm border border-gray-200 dark:border-gray-700 cursor-pointer hover:scale-125 hover:z-10 transition-transform flex-shrink-0"
                  style={{ backgroundColor: hex }}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="border-t border-[#E5E8EB] dark:border-gray-800 mt-2 pt-1.5 flex justify-center">
          <button
            title="색상 해제"
            onClick={(e) => { e.stopPropagation(); onSetColor(null); }}
            className="text-caption text-[#8B95A1] hover:text-[#191F28] dark:hover:text-white cursor-pointer transition-colors"
          >
            색상 해제
          </button>
        </div>
      </div>
    )}
    </>,
    document.body,
  );
}
