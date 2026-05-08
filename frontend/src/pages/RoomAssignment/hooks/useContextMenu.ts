import { useCallback, useEffect, useRef, useState } from 'react';

export interface ContextMenuState {
  x: number;
  y: number;
  targetIds: number[];
  zone?: string;
}

interface UseContextMenuProps {
  canOpen: boolean; // 다른 모달이 떠있으면 false
  selectedGuestIds: Set<number>;
}

/**
 * 게스트 컨텍스트 메뉴 외피 (state + 열기 + 닫기 + long-press refs).
 *
 * Phase D-3: 메뉴 항목 빌더(contextMenuActions useMemo) 는 본체에 잔존.
 * 빌더가 의존하는 핸들러들이 Phase G/I 에서 정리되면 함께 청소 가능.
 */
export function useContextMenu({ canOpen, selectedGuestIds }: UseContextMenuProps) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [mobileContextMenuOpen, setMobileContextMenuOpen] = useState(false);
  const mobileContextBtnRef = useRef<HTMLButtonElement>(null);

  // long-press 타이머 — renderGuestRow 의 onTouchStart/Move/End/Cancel 핸들러가 직접 read/write.
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFiredRef = useRef(false);

  // 언마운트 시 long-press 타이머 정리
  useEffect(() => () => {
    if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
  }, []);

  // 메뉴 외부 클릭 / 스크롤 / ESC 시 닫기 — open 직후 300ms 가드 (open 이벤트와 즉시 발화하는 click 충돌 방지)
  useEffect(() => {
    if (!contextMenu) return;
    const openTime = Date.now();
    const close = () => { if (Date.now() - openTime > 300) setContextMenu(null); };
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') setContextMenu(null); };
    document.addEventListener('click', close);
    document.addEventListener('scroll', close, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('scroll', close, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [contextMenu]);

  // contextMenu 가 닫히면 모바일 메뉴 토글도 자동 해제 (두 상태 동기화)
  useEffect(() => {
    if (!contextMenu) setMobileContextMenuOpen(false);
  }, [contextMenu]);

  const onGuestContextMenu = useCallback((e: React.MouseEvent, resId: number, zone?: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!canOpen) return;

    const targetIds =
      selectedGuestIds.size > 0 && selectedGuestIds.has(resId)
        ? [...selectedGuestIds]
        : [resId];

    setContextMenu({ x: e.clientX, y: e.clientY, targetIds, zone });
  }, [canOpen, selectedGuestIds]);

  return {
    contextMenu,
    setContextMenu,
    mobileContextMenuOpen,
    setMobileContextMenuOpen,
    mobileContextBtnRef,
    longPressTimerRef,
    longPressFiredRef,
    onGuestContextMenu,
  };
}
