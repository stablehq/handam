import React from 'react';
import { createPortal } from 'react-dom';
import { BedDouble, UserRoundPlus, Undo2, Menu, Phone, Trash2 } from 'lucide-react';
import { Tooltip } from '@/components/ui/tooltip';
import { Spinner } from '@/components/ui/spinner';

interface QuickMenuBarProps {
  // 자동 배정
  autoAssigning: boolean;
  onAutoAssign: () => void;
  // 파티 게스트 추가
  onPartyAdd: () => void;
  // 되돌리기
  canUndo: boolean;
  onUndo: () => void;
  // 모바일 + 선택 모드
  isMobile: boolean;
  selectionActive: boolean;
  selectedCount: number;
  mobileContextBtnRef: React.RefObject<HTMLButtonElement>;
  mobileContextMenuOpen: boolean;
  onToggleMobileContext: () => void;
  onCallSelected: () => void;
  onDeleteSelected: () => void;
}

/**
 * 객실 배정 페이지 하단 고정 Quick Menu.
 *
 * createPortal 로 document.body 직속 렌더 + transform 없는 중앙정렬.
 * ancestor 의 transform/filter/contain 등이 fixed positioning 의
 * containing block 을 가로채는 모바일 브라우저 버그를 회피.
 * 래퍼는 viewport 폭(left-0 right-0)을 잡고 flex justify-center 로 안쪽
 * 카드를 중앙. 래퍼 pointer-events-none, 카드 only pointer-events-auto.
 */
export function QuickMenuBar({
  autoAssigning,
  onAutoAssign,
  onPartyAdd,
  canUndo,
  onUndo,
  isMobile,
  selectionActive,
  selectedCount,
  mobileContextBtnRef,
  mobileContextMenuOpen,
  onToggleMobileContext,
  onCallSelected,
  onDeleteSelected,
}: QuickMenuBarProps) {
  return createPortal(
    <div className="fixed bottom-4 left-0 right-0 z-50 flex justify-center pointer-events-none">
      <div className="rounded-2xl shadow-lg bg-white dark:bg-[#1E1E24] border border-[#E5E8EB] dark:border-gray-800 px-4 py-2.5 pointer-events-auto">
        <div className="flex items-center gap-3">
          <span className="text-[9px] font-bold tracking-widest leading-tight text-[#B0B8C1] dark:text-[#4E5968]">QUICK<br/>MENU</span>
          <Tooltip content={autoAssigning ? '배정 중...' : '객실 자동 배정'} placement="top">
            <div className="inline-block">
              <button
                onClick={onAutoAssign}
                disabled={autoAssigning}
                className="h-10 w-10 flex items-center justify-center rounded-full bg-[#3182F6] text-white hover:bg-[#1B64DA] active:bg-[#1554B5] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                {autoAssigning ? <Spinner size="sm" /> : <BedDouble className="h-[18px] w-[18px]" />}
              </button>
            </div>
          </Tooltip>
          <Tooltip content="파티 게스트 추가" placement="top">
            <div className="inline-block">
              <button
                onClick={onPartyAdd}
                className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] transition-colors cursor-pointer"
              >
                <UserRoundPlus className="h-[18px] w-[18px]" />
              </button>
            </div>
          </Tooltip>
          <Tooltip content={isMobile ? '되돌리기' : '되돌리기 (Ctrl+Z)'} placement="top">
            <div className="inline-block">
              <button
                onClick={onUndo}
                disabled={!canUndo}
                className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <Undo2 className="h-[18px] w-[18px]" />
              </button>
            </div>
          </Tooltip>
          {selectionActive && isMobile && (
            <>
              <div className="w-px h-6 bg-[#E5E8EB] dark:bg-gray-700" />
              <Tooltip content="컨텍스트 메뉴" placement="top">
                <div className="inline-block">
                  <button
                    ref={mobileContextBtnRef}
                    onClick={onToggleMobileContext}
                    className={`h-10 w-10 flex items-center justify-center rounded-full border transition-colors cursor-pointer ${
                      mobileContextMenuOpen
                        ? 'bg-[#3182F6] border-[#3182F6] text-white'
                        : 'bg-white dark:bg-[#2C2C34] border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB]'
                    }`}
                  >
                    <Menu className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip
                content={
                  selectedCount !== 1
                    ? '1명 선택 시만 전화 가능'
                    : '선택한 게스트에게 전화'
                }
                placement="top"
              >
                <div className="inline-block">
                  <button
                    onClick={onCallSelected}
                    disabled={selectedCount !== 1}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-[#00C9A7]/10 text-[#00C9A7] border border-[#00C9A7]/20 hover:bg-[#00C9A7]/20 active:bg-[#00C9A7]/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <Phone className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
              <Tooltip content="게스트 삭제" placement="top">
                <div className="inline-block">
                  <button
                    onClick={onDeleteSelected}
                    className="h-10 w-10 flex items-center justify-center rounded-full bg-[#F04452]/10 text-[#F04452] border border-[#F04452]/20 hover:bg-[#F04452]/20 active:bg-[#F04452]/30 transition-colors cursor-pointer"
                  >
                    <Trash2 className="h-[18px] w-[18px]" />
                  </button>
                </div>
              </Tooltip>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
