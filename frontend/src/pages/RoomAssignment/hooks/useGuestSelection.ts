import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import type { Reservation } from '../types';

interface UseGuestSelectionProps {
  selectedDate: Dayjs;
  reservations: Reservation[];
  nextDayReservations: Reservation[];
}

/**
 * 그립 클릭 기반 게스트 선택 모드 + 250ms deselect 지연 + ESC 해제 + 토스트.
 *
 * Phase D-2: 선택 모드 핵심 흐름. mobileContextMenuOpen / longPress 관련은 D-3 에서.
 */
export function useGuestSelection({
  selectedDate,
  reservations,
  nextDayReservations,
}: UseGuestSelectionProps) {
  const [selectedGuestIds, setSelectedGuestIds] = useState<Set<number>>(new Set());
  const selectionActive = selectedGuestIds.size > 0;

  // 단일 선택된 자기 자신을 다시 클릭했을 때 더블클릭 가능성 위해 250ms 지연 후 해제.
  const deselectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelDeselect = useCallback(() => {
    if (deselectTimerRef.current) {
      clearTimeout(deselectTimerRef.current);
      deselectTimerRef.current = null;
    }
  }, []);

  // 선택 모드 토스트 (선택 활성 동안 무한 표시) — 멀티선택 제거로 항상 단일 게스트.
  useEffect(() => {
    const TOAST_ID = 'selection-mode';
    if (selectionActive) {
      const id = [...selectedGuestIds][0];
      const name = reservations.find(r => r.id === id)?.customer_name;
      const msg = name
        ? `${name} — 이동할 방을 클릭하세요`
        : '이동할 방을 클릭하세요';
      toast.info(msg, {
        id: TOAST_ID,
        duration: Infinity,
        position: 'top-center',
        action: {
          label: '✕ 취소',
          onClick: () => setSelectedGuestIds(new Set()),
        },
      });
    } else {
      toast.dismiss(TOAST_ID);
    }
  }, [selectionActive, selectedGuestIds, reservations]);

  // 날짜 전환 시 선택 해제
  useEffect(() => {
    setSelectedGuestIds(new Set());
  }, [selectedDate]);

  // 날짜 전환/언마운트 시 deselect 타이머 정리 (stale callback 방지)
  useEffect(() => () => cancelDeselect(), [selectedDate, cancelDeselect]);

  // 더 이상 존재하지 않는 ID 자동 제거
  useEffect(() => {
    setSelectedGuestIds(prev => {
      const validIds = new Set([
        ...reservations.map(r => r.id),
        ...nextDayReservations.map(r => r.id),
      ]);
      const next = new Set([...prev].filter(id => validIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [reservations, nextDayReservations]);

  // ESC: 선택 해제 (Ctrl+Z 는 본체의 undo 핸들러가 별도 처리)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedGuestIds(new Set());
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const onGripClick = useCallback((e: React.MouseEvent | React.PointerEvent, resId: number) => {
    const pe = e as React.PointerEvent;
    if (pe.button !== 0 && pe.pointerType === 'mouse') return;
    e.preventDefault();
    e.stopPropagation();

    const isAlreadySelectedAlone = selectedGuestIds.has(resId) && selectedGuestIds.size === 1;

    if (isAlreadySelectedAlone) {
      // 동일 행 재클릭이면 진행 중 deselect 취소만 (선택 유지)
      if (deselectTimerRef.current) {
        clearTimeout(deselectTimerRef.current);
        deselectTimerRef.current = null;
        return;
      }
      // 그 외엔 250ms 지연 후 해제 (그 사이 더블클릭 들어오면 cancelDeselect 로 취소되어 편집 진입)
      deselectTimerRef.current = setTimeout(() => {
        setSelectedGuestIds(new Set());
        deselectTimerRef.current = null;
      }, 250);
      return;
    }

    // 다른 행 클릭 또는 첫 선택 — 항상 그 행 하나만 선택 (멀티선택 제거됨)
    setSelectedGuestIds(new Set([resId]));
  }, [selectedGuestIds]);

  return {
    selectedGuestIds,
    setSelectedGuestIds,
    selectionActive,
    cancelDeselect,
    onGripClick,
  };
}
