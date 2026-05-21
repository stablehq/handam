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
 * Step #06c (2026-05-20): 모바일 selection 컨텍스트 버튼 제거 — mobileContextMenuOpen /
 * mobileContextBtnRef / 동기화 effect 폐기. long-press 컨텍스트 메뉴만 유지.
 */
export function useContextMenu({ canOpen, selectedGuestIds }: UseContextMenuProps) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

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
    longPressTimerRef,
    longPressFiredRef,
    onGuestContextMenu,
  };
}
