import type { Dayjs } from 'dayjs';
import { useGuestSelection } from './useGuestSelection';
import { useHoverZone, type HoverZoneState } from './useHoverZone';
import { useIsDesktop } from '../../../hooks/use-desktop';
import type { Reservation } from '../types';

interface UseSelectionSystemProps {
  selectedDate: Dayjs;
  reservations: Reservation[];
  nextDayReservations: Reservation[];
}

const EMPTY_SET = new Set<number>();
const NONE_HOVER: HoverZoneState = { type: 'none' };
const NOOP_SET_STATE: React.Dispatch<React.SetStateAction<Set<number>>> = () => {};
const NOOP_SET_HOVER: (s: HoverZoneState) => void = () => {};
const NOOP_GRIP: (e: React.MouseEvent | React.PointerEvent, resId: number) => void = () => {};
const NOOP_VOID: () => void = () => {};

/**
 * useGuestSelection + useHoverZone 통합 래퍼.
 *
 * - **PC** (isDesktop=true): fixture 반환 → cascade 비활성을 값 자체로 강화.
 *   (단계 #1~#10에서 PC selectionActive가 false로 유지되는 것과 결과 동일)
 * - **모바일**: 실제 훅 결과 반환 → 기존 클릭-선택 시스템 보존.
 *
 * 미래 모바일 자체 레이아웃 도입 시 `<RoomAssignmentDesktop>` 진입점에서 이 훅 대신
 * fixture 상수를 import하면 selection 시스템 일괄 제거 가능.
 *
 * hook order 보장: useGuestSelection / useHoverZone 모두 항상 호출. 분기는 반환값에만 적용.
 */
export function useSelectionSystem(props: UseSelectionSystemProps) {
  const isDesktop = useIsDesktop();
  const selection = useGuestSelection(props);
  const hover = useHoverZone();

  if (isDesktop) {
    return {
      selectedGuestIds: EMPTY_SET,
      setSelectedGuestIds: NOOP_SET_STATE,
      selectionActive: false,
      cancelDeselect: NOOP_VOID,
      onGripClick: NOOP_GRIP,
      hover: NONE_HOVER,
      setHover: NOOP_SET_HOVER,
      clearHover: NOOP_VOID,
    };
  }

  return {
    selectedGuestIds: selection.selectedGuestIds,
    setSelectedGuestIds: selection.setSelectedGuestIds,
    selectionActive: selection.selectionActive,
    cancelDeselect: selection.cancelDeselect,
    onGripClick: selection.onGripClick,
    hover: hover.hover,
    setHover: hover.setHover,
    clearHover: hover.clearHover,
  };
}
